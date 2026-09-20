"""Meaningful multi-node LangGraph sales orchestrator."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.agent.business_rendering import render_business_action
from app.agent.catalog_qualification import qualify_catalog_search
from app.agent.grounding import choose_grounded_result
from app.agent.llm import AgentLLM, AgentLLMError, DeterministicAgentLLM
from app.agent.rendering import (
    render_catalog,
    render_error,
    render_knowledge,
)
from app.agent.schemas import sanitize_understanding
from app.agent.state import AgentState
from app.models.conversation import ConversationSession
from app.rag.embeddings import EmbeddingProvider
from app.services.business_action_parsing import parse_business_fields
from app.services.business_action_workflow_service import (
    BusinessActionWorkflowError,
    BusinessActionWorkflowService,
)
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
        business_action_service: BusinessActionWorkflowService | None = None,
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
        self.business_actions = business_action_service or BusinessActionWorkflowService(
            session,
            recommendations=self.recommendations,
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
            contextual_understanding = getattr(self.llm, "understand_with_context", None)
            if callable(contextual_understanding):
                understanding = contextual_understanding(
                    state["normalized_message"],
                    recent_messages=state.get("recent_messages", []),
                    preferences=state.get("preferences", {}),
                    conversation_context=self._safe_understanding_context(state),
                )
            else:
                understanding = self.llm.understand(
                    state["normalized_message"],
                    recent_messages=state.get("recent_messages", []),
                    preferences=state.get("preferences", {}),
                )
            understanding = sanitize_understanding(understanding, state["normalized_message"])
            update.update(
                {
                    "intent": understanding.intent,
                    "extracted_preferences": understanding.preference_updates.model_dump(
                        exclude_unset=True
                    ),
                    "llm_dialogue_action": understanding.dialogue_action,
                    "llm_preference_clears": list(understanding.preference_clears),
                    "llm_budget_change": understanding.budget_change,
                    "pending_field_answer": understanding.pending_field_answer,
                    "requested_car_fields": list(understanding.requested_car_fields),
                    "llm_condition_preference_order": list(
                        understanding.condition_preference_order
                    ),
                    "visible_reference_selector": (
                        understanding.visible_reference_selector.model_dump()
                    ),
                    "reference_target": understanding.reference_target.model_dump(),
                    "understanding_confidence": understanding.confidence,
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

    @staticmethod
    def _safe_understanding_context(state: AgentState) -> dict[str, Any]:
        """Expose conversation control state to the LLM without pending contact values."""
        snapshot = state.get("active_snapshot") or {}
        visible: list[dict[str, Any]] = []
        for item in list(snapshot.get("items") or []):
            car = item.get("car") or {}
            visible.append(
                {
                    "position": item.get("position"),
                    "brand": car.get("brand"),
                    "model": car.get("model"),
                    "year": car.get("year"),
                    "condition": car.get("condition"),
                    "body_type": car.get("body_type"),
                    "transmission": car.get("transmission"),
                    "fuel_type": car.get("fuel_type"),
                    "price_egp": car.get("price_egp"),
                    "mileage_km": car.get("mileage_km"),
                }
            )

        selected: dict[str, Any] | None = None
        selected_car_id = state.get("selected_car_id")
        if selected_car_id is not None:
            for item in list(snapshot.get("items") or []):
                try:
                    matches = int(item.get("car_id")) == int(selected_car_id)
                except (TypeError, ValueError):
                    matches = False
                if not matches:
                    continue
                car = item.get("car") or {}
                selected = {
                    "position": item.get("position"),
                    "brand": car.get("brand"),
                    "model": car.get("model"),
                    "year": car.get("year"),
                    "condition": car.get("condition"),
                    "body_type": car.get("body_type"),
                    "transmission": car.get("transmission"),
                    "fuel_type": car.get("fuel_type"),
                    "price_egp": car.get("price_egp"),
                    "mileage_km": car.get("mileage_km"),
                }
                break
        if selected_car_id is not None and selected is None:
            # The durable selected-car state remains authoritative even when no
            # active visible snapshot is available. Do not expose/guess a car ID;
            # the catalog node resolves the persisted ID deterministically later.
            selected = {"selected": True}

        pending = state.get("pending_action") or {}
        pending_type = str(pending.get("type") or "")
        fields = dict(pending.get("fields") or {})
        required_by_action = {
            "test_drive": {"car_id", "customer_name", "phone", "preferred_date", "preferred_time"},
            "sales_lead": {"customer_name", "phone"},
            "cancel_test_drive": {"request_id"},
        }
        required = required_by_action.get(pending_type, set())
        collected = sorted(name for name, value in fields.items() if value not in (None, ""))
        missing = sorted(name for name in required if fields.get(name) in (None, ""))

        dialogue = state.get("dialogue_state") or {}
        return {
            "dialogue_goal": dialogue.get("catalog_goal"),
            "visible_recommendations": visible,
            "selected_car": selected,
            "pending_action": (
                {
                    "type": pending_type,
                    "collected_fields": collected,
                    "missing_fields": missing,
                }
                if pending_type
                else None
            ),
        }

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
        pending_action = state.get("pending_action")
        has_pending_business = isinstance(pending_action, dict) and pending_action.get("type") in {
            "test_drive",
            "cancel_test_drive",
            "sales_lead",
        }

        is_pending_followup = False
        if has_pending_business:
            intent_type = str(pending_action.get("type") or "")
            parsed = parse_business_fields(
                state.get("normalized_message", ""),
                allow_bare_name=(intent_type in {"test_drive", "sales_lead"}),
            )
            if parsed.as_json_fields():
                is_pending_followup = True

        if "understanding_failed" in state.get("errors", []) or "state_update_failed" in state.get(
            "errors", []
        ):
            route: Route = "general_node"
        elif intent in {"test_drive", "cancel_test_drive", "sales_lead"}:
            route = "business_gate"
        elif has_pending_business and (
            is_pending_followup
            or intent in {"general", "car_details", "car_selection"}
            or (intent == "catalog_search" and not state.get("extracted_preferences"))
        ):
            route = "business_gate"
        elif intent in {"catalog_search", "car_details", "car_compare", "car_selection"}:
            route = "catalog_node"
        elif intent == "knowledge_question":
            route = "rag_node"
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
                message_text = state.get("normalized_message", "").casefold()
                is_pagination = any(
                    term in message_text
                    for term in ("تاني", "تانيه", "ثانية", "غيرهم", "غير دول", "مزيد", "صفحة تانية")
                )
                qualification = qualify_catalog_search(
                    state.get("preferences", {}), state.get("normalized_message", "")
                )
                if not qualification.ready and not is_pagination:
                    update["catalog_result"] = {
                        "type": "clarification",
                        "message": qualification.message,
                        "missing": list(qualification.missing),
                    }
                    return update

                if is_pagination:
                    snapshot = self.recommendations.recommend_next_batch_and_snapshot(
                        session_id,
                        state.get("preferences", {}),
                        limit=self.recommendation_limit,
                    )
                else:
                    snapshot = self.recommendations.recommend_and_snapshot(
                        session_id,
                        state.get("preferences", {}),
                        limit=self.recommendation_limit,
                    )
                if snapshot is None:
                    prefs = state.get("preferences", {})
                    relaxed = self.catalog.recommend_with_relaxation(
                        prefs, limit=self.recommendation_limit
                    )
                    if relaxed["type"] == "price_relaxation":
                        cars = relaxed["cars"]
                        snapshot = self.recommendations.create_visible_snapshot(
                            session_id, cars, prefs
                        )
                        context = self.context.load(session_id)
                        update.update(self._context_update(context))
                        update["catalog_result"] = {
                            "type": "relaxed_suggestion",
                            "reason": "price",
                            "cars": [
                                self.catalog.serialize_details(c) if hasattr(c, "brand") else c
                                for c in cars
                            ],
                            "original_max_price": relaxed["original_max_price"],
                            "cheapest_price": relaxed["cheapest_price"],
                            "snapshot_id": snapshot.id,
                        }
                    elif relaxed["type"] == "condition_relaxation":
                        found_car = relaxed["cars"][0]
                        if found_car.condition == "used":
                            cond_label = "مستعملة"
                        elif found_car.condition == "new":
                            cond_label = "جديدة"
                        else:
                            cond_label = str(found_car.condition)
                        car_name = f"{found_car.brand} {found_car.model}".strip()
                        update["catalog_result"] = {
                            "type": "fallback_condition",
                            "car_name": car_name,
                            "available_condition_text": cond_label,
                        }
                    else:
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
                target = self._resolve_detail_target(state, session_id)
                if isinstance(target, dict) and target.get("type") == "clarification":
                    update["catalog_result"] = target
                    return update
                car_id, position = target
                car = self.catalog.get_car_details(car_id)
                if car is None:
                    raise VisibleRecommendationError("The requested car is unavailable")
                if position is not None:
                    try:
                        self.recommendations.select_visible_car(session_id, position)
                    except Exception:
                        pass
                else:
                    try:
                        session_obj = self.session.get(ConversationSession, session_id)
                        if session_obj:
                            session_obj.selected_car_id = car_id
                            self.session.commit()
                    except Exception:
                        self.session.rollback()
                update["selected_car_id"] = car_id
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
                if len(references) < 2:
                    active = state.get("active_snapshot")
                    if not active or not active.get("items"):
                        context = self.context.load(session_id)
                        active = context.active_snapshot
                    if active and active.get("items"):
                        items = active["items"]
                        if len(items) == 2:
                            references = [1, 2]
                        elif len(items) > 2:
                            update["catalog_result"] = {
                                "type": "clarification",
                                "message": "اختار رقمين من القائمة للمقارنة (مثلاً: قارن 1 و 2).",
                            }
                            return update
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
    ) -> tuple[int, int | None] | dict[str, Any]:
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
        active = state.get("active_snapshot")
        if not active or not active.get("items"):
            context = self.context.load(session_id)
            active = context.active_snapshot
        if active and active.get("items"):
            items = active["items"]
            if len(items) == 1:
                return items[0]["car_id"], items[0]["position"]
            positions = [str(item["position"]) for item in items]
            options = " ولا ".join(positions)
            return {
                "type": "clarification",
                "message": f"تقصد رقم كام من القائمة؟ {options}؟",
            }
        raise VisibleRecommendationError("No selected or visibly referenced car")

    def _rag_node(self, state: AgentState) -> AgentState:
        update = self._trace(state, "rag_node")
        try:
            category_hint = state.get("knowledge_category_hint")
            results = self.rag.retrieve(
                state["normalized_message"],
                category=category_hint or None,
            )
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

            # Soft hint fallback: if category hint yielded no grounded result,
            # retry unfiltered retrieval
            if grounded is None and category_hint:
                unfiltered_results = self.rag.retrieve(
                    state["normalized_message"],
                    category=None,
                )
                unfiltered_serialized = [
                    {
                        "document_id": str(result.document_id),
                        "title": result.title,
                        "category": result.category,
                        "chunk_id": result.chunk_id,
                        "chunk_index": result.chunk_index,
                        "content": result.content,
                        "similarity": result.similarity,
                    }
                    for result in unfiltered_results
                ]
                unfiltered_grounded = choose_grounded_result(
                    state["normalized_message"], unfiltered_serialized
                )
                if unfiltered_grounded is not None:
                    serialized = unfiltered_serialized
                    grounded = unfiltered_grounded

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
        try:
            session_id = uuid.UUID(state["session_id"])
            intent = state.get("intent", "general")
            car_reference = state.get("car_reference")
            message = state.get("normalized_message", "")

            plan = self.business_actions.prepare_action(
                session_id,
                intent,
                message,
                car_reference=car_reference,
                field_hint=state.get("pending_field_answer"),
            )
            if plan.get("status") == "ready":
                result = self.business_actions.execute_action(session_id, plan)
                update["action_status"] = result
            else:
                update["action_status"] = plan

            context = self.context.load(session_id)
            update.update(self._context_update(context))
        except (
            BusinessActionWorkflowError,
            VisibleRecommendationError,
            ValueError,
            SQLAlchemyError,
        ):
            self.session.rollback()
            update["errors"] = self._errors(state, "business_action_failed")
            update["action_status"] = None
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
            response = render_business_action(
                state.get("action_status"),
                user_message=state.get("normalized_message"),
            )
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
