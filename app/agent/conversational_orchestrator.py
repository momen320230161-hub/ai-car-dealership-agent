"""Production conversational layer over the deterministic LangGraph sales orchestrator."""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from app.agent.business_rendering import render_business_action
from app.agent.graph import SalesOrchestrator
from app.agent.llm import AgentLLMError, DeterministicAgentLLM
from app.agent.rendering import render_catalog, render_error, render_knowledge
from app.agent.state import AgentState
from app.services.business_action_parsing import parse_business_fields
from app.services.catalog_preference_state_service import CatalogPreferenceStateService
from app.services.conversational_business_action_workflow_service import (
    ConversationalBusinessActionWorkflowService,
)
from app.services.customer_memory_service import CustomerMemoryService

_BUSINESS_INTENTS = {"test_drive", "cancel_test_drive", "sales_lead"}
_CATALOG_INTENTS = {"catalog_search", "car_details", "car_compare", "car_selection"}
_RESUME_TERMS = (
    "كمل الحجز",
    "نكمل الحجز",
    "كمل الطلب",
    "نكمل الطلب",
    "كمل",
    "نكمل",
    "continue",
    "resume",
)
_REQUIRED_BY_ACTION = {
    "test_drive": {"car_id", "customer_name", "phone", "preferred_date", "preferred_time"},
    "sales_lead": {"customer_name", "phone", "email", "car_id"},
    "cancel_test_drive": {"request_id"},
}
_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


class ConversationalSalesOrchestrator(SalesOrchestrator):
    """Keep deterministic execution, but make routing/memory/language conversational."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        provided_state_service = kwargs.get("state_service")
        provided_business_service = kwargs.get("business_action_service")
        super().__init__(*args, **kwargs)

        self.customer_memory = CustomerMemoryService(self.session)
        if provided_state_service is None:
            self.state_updates = CatalogPreferenceStateService(self.session)
        if provided_business_service is None:
            self.business_actions = ConversationalBusinessActionWorkflowService(
                self.session,
                customer_memory=self.customer_memory,
                recommendations=self.recommendations,
            )

    def _route_request(self, state: AgentState) -> AgentState:
        """Allow side questions while a pending action stays safely persisted."""
        update = self._trace(state, "route_request")
        intent = state.get("intent", "general")
        pending = state.get("pending_action")
        pending_type = str((pending or {}).get("type") or "")
        has_pending_business = pending_type in _BUSINESS_INTENTS

        if "understanding_failed" in state.get("errors", []) or "state_update_failed" in state.get(
            "errors", []
        ):
            route = "general_node"
        elif intent in _BUSINESS_INTENTS:
            route = "business_gate"
        elif has_pending_business and self._continues_pending_action(state, pending_type):
            route = "business_gate"
        elif intent in _CATALOG_INTENTS:
            route = "catalog_node"
        elif intent == "knowledge_question":
            route = "rag_node"
        else:
            route = "general_node"

        update["route"] = route.removesuffix("_node")
        update["selected_route"] = route
        return update

    def _continues_pending_action(self, state: AgentState, pending_type: str) -> bool:
        message = state.get("normalized_message", "")
        intent = state.get("intent", "general")
        pending = state.get("pending_action") or {}
        fields = dict(pending.get("fields") or {})
        required = _REQUIRED_BY_ACTION.get(pending_type, set())
        missing = {name for name in required if fields.get(name) in (None, "")}

        allow_bare_name = intent == "general" and "customer_name" in missing
        parsed = parse_business_fields(message, allow_bare_name=allow_bare_name)
        explicit = set(parsed.as_json_fields())
        if explicit & required:
            return True

        text = message.casefold()
        return intent == "general" and any(term in text for term in _RESUME_TERMS)

    def _compose_response(self, state: AgentState) -> AgentState:
        update = self._trace(state, "compose_response")
        guard_error = state.get("guard_error")
        errors = state.get("errors", [])
        if guard_error:
            update["response"] = render_error(guard_error)
            return update
        if errors:
            update["response"] = render_error(errors[0])
            return update

        fallback = self._deterministic_fallback(state)
        if isinstance(self.llm, DeterministicAgentLLM):
            update["response"] = fallback
            return update

        # If RAG has no verified support, do not invite a language model to improvise policy.
        if state.get("route") == "rag" and not state.get("knowledge_supported", False):
            update["response"] = fallback
            return update

        verified_context = self._verified_response_context(state, fallback)
        try:
            response = self.llm.compose_general(
                state.get("normalized_message", ""),
                verified_context=verified_context,
            ).strip()
        except AgentLLMError:
            update["response"] = fallback
            update["errors"] = self._errors(state, "composition_failed")
            return update

        if not self._composition_is_grounded(response, state, verified_context):
            update["response"] = fallback
            update["errors"] = self._errors(state, "composition_rejected")
            return update

        update["response"] = response
        return update

    def _deterministic_fallback(self, state: AgentState) -> str:
        route = state.get("route")
        if route == "catalog":
            return render_catalog(state.get("catalog_result"))
        if route == "rag":
            return render_knowledge(
                state.get("knowledge_supported", False),
                state.get("grounded_knowledge"),
            )
        if route == "business_gate":
            return render_business_action(
                state.get("action_status"),
                user_message=state.get("normalized_message"),
            )
        return DeterministicAgentLLM().compose_general(
            state.get("normalized_message", ""),
            verified_context={},
        )

    def _verified_response_context(
        self,
        state: AgentState,
        fallback: str,
    ) -> dict[str, Any]:
        memory_context: dict[str, Any] = {}
        session_id = state.get("session_id")
        if session_id:
            try:
                memory_context = self.customer_memory.load(uuid.UUID(session_id)).safe_context()
            except (LookupError, TypeError, ValueError):
                memory_context = {}

        pending = state.get("pending_action") or {}
        pending_fields = dict(pending.get("fields") or {})
        action = dict(state.get("action_status") or {})
        safe_action_keys = {
            "status",
            "intent",
            "request_id",
            "lead_id",
            "car_id",
            "preferred_date",
            "preferred_time",
            "missing_fields",
            "candidate_request_ids",
            "memory_fields_used",
            "customer_memory_scope",
        }

        return {
            "authoritative_fallback": fallback,
            "route": state.get("route"),
            "intent": state.get("intent"),
            "recent_messages": state.get("recent_messages", [])[-8:],
            "vehicle_preferences": state.get("preferences", {}),
            "selected_car_id": state.get("selected_car_id"),
            "pending_action": {
                "type": pending.get("type"),
                "collected_fields": sorted(pending_fields),
            },
            "customer_memory": memory_context,
            "catalog_result": state.get("catalog_result"),
            "grounded_knowledge": state.get("grounded_knowledge"),
            "action_result": {key: action.get(key) for key in safe_action_keys if key in action},
        }

    def _composition_is_grounded(
        self,
        response: str,
        state: AgentState,
        verified_context: dict[str, Any],
    ) -> bool:
        if not response or len(response) > 2400:
            return False

        source = " ".join(
            (
                state.get("normalized_message", ""),
                json.dumps(verified_context, ensure_ascii=False, default=str),
            )
        )
        allowed_numbers = self._numbers(source)
        if any(number not in allowed_numbers for number in self._numbers(response)):
            return False

        if state.get("route") != "business_gate":
            return True

        action = state.get("action_status") or {}
        status = action.get("status")
        if status != "success":
            success_claims = ("تم تسجيل", "اتسجل بنجاح", "تم إلغاء", "اتلغى بنجاح")
            return not any(claim in response for claim in success_claims)

        intent = action.get("intent")
        required_id = action.get("lead_id") if intent == "sales_lead" else action.get("request_id")
        if not isinstance(required_id, int):
            return False
        if required_id not in self._numbers(response):
            return False

        if intent == "test_drive":
            unsafe_confirmation = (
                "تم تأكيد الموعد",
                "الموعد مؤكد",
                "الحجز مؤكد",
                "اتأكد الموعد نهائيا",
                "اتأكد الموعد نهائيًا",
            )
            if any(claim in response for claim in unsafe_confirmation):
                return False
        return True

    @staticmethod
    def _numbers(text: str) -> set[int]:
        normalized = str(text).translate(_ARABIC_DIGITS)
        return {int(value) for value in re.findall(r"\d+", normalized)}
