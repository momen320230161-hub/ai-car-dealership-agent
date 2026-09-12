"""Meaningful multi-node LangGraph sales orchestrator."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.agent.grounding import choose_grounded_result
from app.agent.llm import AgentLLM, AgentLLMError, DeterministicAgentLLM
from app.agent.rendering import (
    render_business_action,
    render_catalog,
    render_error,
    render_knowledge,
)
from app.agent.schemas import sanitize_understanding
from app.agent.state import AgentState
from app.rag.embeddings import EmbeddingProvider
from app.services.catalog_service import CatalogService
from app.services.conversation_context_service import (
    ConversationContext,
    ConversationContextError,
    ConversationContextService,
)
from app.services.conversation_state_service import ConversationStateService
from app.services.rag_service import RAGRetrievalError, RAGService
from app.services.recommendation_service import (
    RecommendationService,
    VisibleRecommendationError,
)

logger = logging.getLogger(__name__)

CatalogIntent = Literal["catalog_search", "car_details", "car_compare", "car_selection"]
Route = Literal["catalog_node", "rag_node", "business_gate", "general_node"]

GRAPH_NODES = (
    "input_guard",
    "load_context",
    "understand_request",
    "update_state",
    "route_request",
    "catalog_node",
    "rag_node",
    "business_gate",
    "general_node",
    "compose_response",
    "persist_context",
)


@dataclass(frozen=True, slots=True)
class AgentResponse:
    session_id: str | None
    response: str
    intent: str
    route: str
    visible_recommendations: list[dict[str, Any]]
    recommendation_snapshot_id: int | None
    selected_car_id: int | None
    errors: tuple[str, ...]
    graph_trace: tuple[str, ...]


class SalesOrchestrator:
    """Application entry point that coordinates existing deterministic services."""

    def __init__(
        self,
        session: Session,
        llm: AgentLLM,
        embedding_provider: EmbeddingProvider,
        *,
        max_message_length: int = 4000,
        recent_message_limit: int = 12,
        recommendation_limit: int = 3,
        rag_top_k: int = 4,
        rag_max_top_k: int = 20,
        rag_min_score: float | None = None,
        context_service: ConversationContextService | None = None,
        state_service: ConversationStateService | None = None,
        recommendation_service: RecommendationService | None = None,
        catalog_service: CatalogService | None = None,
        rag_service: RAGService | None = None,
    ):
        if max_message_length < 1:
            raise ValueError("max_message_length must be positive")
        if recommendation_limit < 1:
            raise ValueError("recommendation_limit must be positive")
        self.session = session
        self.llm = llm
        self.max_message_length = max_message_length
        self.recommendation_limit = recommendation_limit
        self.context = context_service or ConversationContextService(
            session, recent_message_limit=recent_message_limit
        )
        self.state_updates = state_service or ConversationStateService(session)
        self.recommendations = recommendation_service or RecommendationService(session)
        self.catalog = catalog_service or CatalogService(session)
        self.rag = rag_service or RAGService(
            session,
            embedding_provider,
            default_top_k=rag_top_k,
            max_top_k=rag_max_top_k,
            default_min_score=rag_min_score,
        )
        self.graph = self._build_graph()

    def _build_graph(self):
        builder = StateGraph(AgentState)
        builder.add_node("input_guard", self._input_guard)
        builder.add_node("load_context", self._load_context)
        builder.add_node("understand_request", self._understand_request)
        builder.add_node("update_state", self._update_state)
        builder.add_node("route_request", self._route_request)
        builder.add_node("catalog_node", self._catalog_node)
        builder.add_node("rag_node", self._rag_node)
        builder.add_node("business_gate", self._business_gate)
        builder.add_node("general_node", self._general_node)
        builder.add_node("compose_response", self._compose_response)
        builder.add_node("persist_context", self._persist_context)

        builder.add_edge(START, "input_guard")
        builder.add_edge("input_guard", "load_context")
        builder.add_conditional_edges(
            "load_context",
            self._after_context,
            {"understand_request": "understand_request", "compose_response": "compose_response"},
        )
        builder.add_edge("understand_request", "update_state")
        builder.add_edge("update_state", "route_request")
        builder.add_conditional_edges(
            "route_request",
            self._selected_route,
            {
                "catalog_node": "catalog_node",
                "rag_node": "rag_node",
                "business_gate": "business_gate",
                "general_node": "general_node",
            },
        )
        for node in ("catalog_node", "rag_node", "business_gate", "general_node"):
            builder.add_edge(node, "compose_response")
        builder.add_edge("compose_response", "persist_context")
        builder.add_edge("persist_context", END)
        return builder.compile(name="AutoDriveSalesOrchestrator")

    def handle_message(self, session_id: uuid.UUID | str | None, message: Any) -> AgentResponse:
        initial: AgentState = {
            "session_id": str(session_id) if session_id is not None else None,
            "user_message": message,
            "errors": [],
            "trace": [],
            "persisted": False,
        }
        try:
            result = self.graph.invoke(initial)
        except Exception:
            self.session.rollback()
            logger.exception("Sales orchestrator graph execution failed")
            return AgentResponse(
                session_id=initial["session_id"],
                response=render_error(None),
                intent="general",
                route="general",
                visible_recommendations=[],
                recommendation_snapshot_id=None,
                selected_car_id=None,
                errors=("orchestrator_failed",),
                graph_trace=tuple(initial["trace"]),
            )
        catalog_result = result.get("catalog_result") or {}
        return AgentResponse(
            session_id=result.get("session_id"),
            response=result.get("response", render_error(None)),
            intent=result.get("intent", "general"),
            route=result.get("route", "general"),
            visible_recommendations=(
                catalog_result.get("cars", [])
                if catalog_result.get("type") == "recommendations"
                else []
            ),
            recommendation_snapshot_id=catalog_result.get("snapshot_id"),
            selected_car_id=result.get("selected_car_id"),
            errors=tuple(
                ([result["guard_error"]] if result.get("guard_error") else [])
                + result.get("errors", [])
            ),
            graph_trace=tuple(result.get("trace", [])),
        )

    def _input_guard(self, state: AgentState) -> AgentState:
        update = self._trace(state, "input_guard")
        message = state.get("user_message")
        error = None
        normalized = ""
        if not isinstance(message, str):
            error = "unsupported_input"
        else:
            normalized = " ".join(message.split())
            if not normalized:
                error = "blank_input"
            elif len(message) > self.max_message_length:
                error = "message_too_long"
            elif any(
                marker in normalized.casefold()
                for marker in (
                    "ignore previous instructions",
                    "system prompt",
                    "gemini_api_key",
                    "api key",
                    "تجاهل التعليمات",
                    "اعرض البرومبت",
                    "كلمة السر",
                )
            ):
                error = "sensitive_request"
        update.update({"normalized_message": normalized, "guard_error": error})
        return update

    def _load_context(self, state: AgentState) -> AgentState:
        update = self._trace(state, "load_context")
        try:
            context = self.context.load_or_create(state.get("session_id"))
            update.update(self._context_update(context))
        except (ConversationContextError, ValueError, SQLAlchemyError):
            update["errors"] = self._errors(state, "context_failed")
        return update

    def _after_context(
        self, state: AgentState
    ) -> Literal["understand_request", "compose_response"]:
        if state.get("guard_error") or "context_failed" in state.get("errors", []):
            return "compose_response"
        return "understand_request"

    def _understand_request(self, state: AgentState) -> AgentState:
        update = self._trace(state, "understand_request")
        try:
            understanding = self.llm.understand(
                state["normalized_message"],
                recent_messages=state.get("recent_messages", []),
                preferences=state.get("preferences", {}),
            )
            understanding = sanitize_understanding(
                understanding, state["normalized_message"]
            )
            update.update(
                {
                    "intent": understanding.intent,
                    "extracted_preferences": understanding.preference_updates.model_dump(
                        exclude_none=True
                    ),
                    "car_reference": understanding.car_reference,
                    "comparison_references": understanding.comparison_references,
                    "explicit_car_id": understanding.explicit_car_id,
                    "knowledge_category_hint": understanding.knowledge_category_hint,
                }
            )
        except (AgentLLMError, ValueError, TypeError):
            update.update(
                {
                    "intent": "general",
                    "extracted_preferences": {},
                    "errors": self._errors(state, "understanding_failed"),
                }
            )
        return update

    def _update_state(self, state: AgentState) -> AgentState:
        update = self._trace(state, "update_state")
        preferences = state.get("extracted_preferences", {})
        if not preferences or "understanding_failed" in state.get("errors", []):
            return update
        try:
            session_id = uuid.UUID(state["session_id"])
            self.state_updates.update_preferences(session_id, preferences)
            update.update(self._context_update(self.context.load(session_id)))
        except (ConversationContextError, LookupError, ValueError, SQLAlchemyError):
            update["errors"] = self._errors(state, "state_update_failed")
        return update

    def _route_request(self, state: AgentState) -> AgentState:
        update = self._trace(state, "route_request")
        intent = state.get("intent", "general")
        if "understanding_failed" in state.get("errors", []) or "state_update_failed" in state.get(
            "errors", []
        ):
            route: Route = "general_node"
        elif intent in {"catalog_search", "car_details", "car_compare", "car_selection"}:
            route = "catalog_node"
        elif intent == "knowledge_question":
            route = "rag_node"
        elif intent in {"test_drive", "cancel_test_drive", "sales_lead"}:
            route = "business_gate"
        else:
            route = "general_node"
        update["route"] = route.removesuffix("_node")
        update["selected_route"] = route
        return update

    @staticmethod
    def _selected_route(state: AgentState) -> Route:
        return state.get("selected_route", "general_node")  # type: ignore[return-value]

    def _catalog_node(self, state: AgentState) -> AgentState:
        update = self._trace(state, "catalog_node")
        try:
            session_id = uuid.UUID(state["session_id"])
            intent: CatalogIntent = state.get("intent", "catalog_search")  # type: ignore[assignment]
            if intent == "catalog_search":
                snapshot = self.recommendations.recommend_and_snapshot(
                    session_id,
                    state.get("preferences", {}),
                    limit=self.recommendation_limit,
                )
                if snapshot is None:
                    update["catalog_result"] = {"type": "no_results"}
                else:
                    context = self.context.load(session_id)
                    update.update(self._context_update(context))
                    active = context.active_snapshot or {"items": []}
                    update["catalog_result"] = {
                        "type": "recommendations",
                        "cars": active["items"],
                        "snapshot_id": active.get("id"),
                    }
            elif intent == "car_details":
                car_id, position = self._resolve_detail_target(state, session_id)
                car = self.catalog.get_car_details(car_id)
                if car is None:
                    raise VisibleRecommendationError("The requested car is unavailable")
                update["catalog_result"] = {
                    "type": "car_details",
                    "car": self._json_safe(car),
                    "position": position,
                }
            elif intent == "car_selection":
                reference = state.get("car_reference")
                if reference is None:
                    raise VisibleRecommendationError("A visible position is required")
                car = self.recommendations.select_visible_car(session_id, reference)
                update.update(
                    {
                        "selected_car_id": car.id,
                        "catalog_result": {
                            "type": "selection",
                            "car": self._json_safe(self.catalog.serialize_details(car)),
                        },
                    }
                )
            else:
                references = state.get("comparison_references", [])
                comparison = self.recommendations.compare_visible(session_id, references)
                update["catalog_result"] = {
                    "type": "comparison",
                    "positions": list(references),
                    "cars": self._json_safe(comparison["cars"]),
                }
        except (VisibleRecommendationError, LookupError, ValueError, SQLAlchemyError):
            self.session.rollback()
            update["errors"] = self._errors(state, "catalog_unavailable")
        return update

    def _resolve_detail_target(
        self, state: AgentState, session_id: uuid.UUID
    ) -> tuple[int, int | None]:
        reference = state.get("car_reference")
        if reference is not None:
            item = self.recommendations.resolve_visible_item(session_id, reference)
            return item.car_id, item.position
        explicit_car_id = state.get("explicit_car_id")
        if explicit_car_id is not None:
            return explicit_car_id, None
        selected_car_id = state.get("selected_car_id")
        if selected_car_id is not None:
            return selected_car_id, None
        raise VisibleRecommendationError("No selected or visibly referenced car")

    def _rag_node(self, state: AgentState) -> AgentState:
        update = self._trace(state, "rag_node")
        try:
            results = self.rag.retrieve(state["normalized_message"])
            serialized = [
                {
                    "document_id": str(result.document_id),
                    "title": result.title,
                    "category": result.category,
                    "chunk_id": result.chunk_id,
                    "chunk_index": result.chunk_index,
                    "content": result.content,
                    "similarity": result.similarity,
                }
                for result in results
            ]
            grounded = choose_grounded_result(state["normalized_message"], serialized)
            update.update(
                {
                    "retrieved_knowledge": serialized,
                    "grounded_knowledge": grounded,
                    "knowledge_supported": grounded is not None,
                }
            )
        except (RAGRetrievalError, ValueError, SQLAlchemyError):
            self.session.rollback()
            update.update(
                {
                    "retrieved_knowledge": [],
                    "grounded_knowledge": None,
                    "knowledge_supported": False,
                    "errors": self._errors(state, "rag_failed"),
                }
            )
        return update

    def _business_gate(self, state: AgentState) -> AgentState:
        update = self._trace(state, "business_gate")
        update["action_status"] = {
            "status": "deferred_to_phase5",
            "intent": state.get("intent", "general"),
        }
        return update

    def _general_node(self, state: AgentState) -> AgentState:
        update = self._trace(state, "general_node")
        update["general_context"] = {"kind": "conversation_only"}
        return update

    def _compose_response(self, state: AgentState) -> AgentState:
        update = self._trace(state, "compose_response")
        guard_error = state.get("guard_error")
        errors = state.get("errors", [])
        if guard_error:
            response = render_error(guard_error)
        elif errors:
            response = render_error(errors[0])
        elif state.get("route") == "catalog":
            response = render_catalog(state.get("catalog_result"))
        elif state.get("route") == "rag":
            response = render_knowledge(
                state.get("knowledge_supported", False), state.get("grounded_knowledge")
            )
        elif state.get("route") == "business_gate":
            response = render_business_action(state.get("intent", "general"))
        else:
            try:
                response = self.llm.compose_general(
                    state.get("normalized_message", ""),
                    verified_context=state.get("general_context", {}),
                )
            except AgentLLMError:
                response = DeterministicAgentLLM().compose_general(
                    state.get("normalized_message", ""), verified_context={}
                )
                update["errors"] = self._errors(state, "composition_failed")
        update["response"] = response
        return update

    def _persist_context(self, state: AgentState) -> AgentState:
        update = self._trace(state, "persist_context")
        if state.get("persisted") or not state.get("session_id"):
            return update
        try:
            self.context.persist_turn(
                state["session_id"], state.get("user_message"), state["response"]
            )
            update["persisted"] = True
        except (ConversationContextError, ValueError, SQLAlchemyError):
            update["errors"] = self._errors(state, "persistence_failed")
        return update

    @staticmethod
    def _context_update(context: ConversationContext) -> AgentState:
        return {
            "session_id": str(context.session_id),
            "preferences": context.preferences,
            "selected_car_id": context.selected_car_id,
            "active_snapshot": context.active_snapshot,
            "pending_action": context.pending_action,
            "recent_messages": context.recent_messages,
        }

    @staticmethod
    def _errors(state: AgentState, code: str) -> list[str]:
        return [*state.get("errors", []), code]

    @staticmethod
    def _trace(state: AgentState, node: str) -> AgentState:
        return {"trace": [*state.get("trace", []), node]}

    @classmethod
    def _json_safe(cls, value: Any) -> Any:
        return ConversationContextService._json_safe(value)
