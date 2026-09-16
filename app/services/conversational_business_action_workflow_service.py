"""Business-action workflow with verified reusable customer contact memory."""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy.orm import Session

from app.models.conversation import ConversationSession
from app.services.business_action_workflow_service import BusinessActionWorkflowService
from app.services.catalog_preference_state_service import CatalogPreferenceStateService
from app.services.customer_memory_service import CustomerMemoryService
from app.services.recommendation_service import RecommendationService

_CONTACT_FIELDS = ("customer_name", "phone", "email")
_MEMORY_ACTIONS = {"test_drive", "sales_lead"}
_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


class ConversationalBusinessActionWorkflowService(BusinessActionWorkflowService):
    """Reuse verified contacts while keeping execution/readiness fully deterministic."""

    def __init__(
        self,
        session: Session,
        *,
        customer_memory: CustomerMemoryService | None = None,
        recommendations: RecommendationService | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(session, recommendations=recommendations, **kwargs)
        self.customer_memory = customer_memory or CustomerMemoryService(session)
        self.preference_state = CatalogPreferenceStateService(session)

    def prepare_action(
        self,
        session_id: uuid.UUID,
        requested_intent: str,
        message: str,
        *,
        car_reference: str | int | None = None,
    ) -> dict[str, Any]:
        # Clean rows polluted by older builds before strict CatalogFilters sees them again.
        self.preference_state.strip_legacy_contact_preferences(session_id)

        result = super().prepare_action(
            session_id,
            requested_intent,
            message,
            car_reference=car_reference,
        )
        # The legacy base workflow temporarily mirrors customer_name into preferences.
        # Remove it immediately so customer identity never becomes a car filter.
        self.preference_state.strip_legacy_contact_preferences(session_id)

        intent = str(result.get("intent") or requested_intent)
        if intent == "test_drive" and self._has_ambiguous_clock_time(message):
            result = self._remove_ambiguous_time(session_id, result)

        if result.get("status") != "missing_fields" or intent not in _MEMORY_ACTIONS:
            return result

        missing = {str(name) for name in result.get("missing_fields", [])}
        contact_missing = [name for name in _CONTACT_FIELDS if name in missing]
        if not contact_missing:
            return result

        memory = self.customer_memory.load(session_id)
        memory_fields = memory.as_fields()
        reusable = {
            name: memory_fields[name]
            for name in contact_missing
            if memory_fields.get(name)
        }
        if not reusable:
            return result

        conversation = self.session.get(ConversationSession, session_id)
        if conversation is None:
            raise LookupError("Conversation session was not found")
        pending = dict(conversation.pending_action or {})
        if pending.get("type") != intent:
            return result
        fields = dict(pending.get("fields") or {})
        used: list[str] = []
        for name, value in reusable.items():
            if fields.get(name) in (None, ""):
                fields[name] = value
                used.append(name)
        if not used:
            return result

        pending["fields"] = fields
        conversation.pending_action = pending
        self.session.commit()

        # Re-run readiness against the same persisted attempt. Empty message means remembered
        # fields can only fill missing slots; they never override explicit current-turn input.
        refreshed = super().prepare_action(
            session_id,
            intent,
            "",
            car_reference=car_reference,
        )
        self.preference_state.strip_legacy_contact_preferences(session_id)
        refreshed["memory_fields_used"] = used
        refreshed["customer_memory_scope"] = memory.scope
        return refreshed

    def execute_action(
        self,
        session_id: uuid.UUID,
        plan: Mapping[str, Any],
    ) -> dict[str, Any]:
        result = super().execute_action(session_id, plan)
        memory_fields_used = [str(name) for name in plan.get("memory_fields_used", [])]
        if memory_fields_used:
            result["memory_fields_used"] = memory_fields_used
            result["customer_memory_scope"] = plan.get("customer_memory_scope")
        return result

    def _remove_ambiguous_time(
        self,
        session_id: uuid.UUID,
        result: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Never turn an ambiguous "الساعة 5" into 05:00 and insert it."""
        fields = dict(result.get("fields") or {})
        if "preferred_time" not in fields:
            return dict(result)
        fields.pop("preferred_time", None)

        conversation = self.session.get(ConversationSession, session_id)
        if conversation is None:
            raise LookupError("Conversation session was not found")
        pending = dict(conversation.pending_action or {})
        pending_fields = dict(pending.get("fields") or {})
        pending_fields.pop("preferred_time", None)
        pending["fields"] = pending_fields
        conversation.pending_action = pending
        self.session.commit()

        missing = [str(name) for name in result.get("missing_fields", [])]
        if "preferred_time" not in missing:
            missing.append("preferred_time")
        updated = dict(result)
        updated.update(
            {
                "status": "missing_fields",
                "fields": fields,
                "missing_fields": missing,
                "ambiguous_time": True,
            }
        )
        return updated

    @staticmethod
    def _has_ambiguous_clock_time(message: str) -> bool:
        text = str(message or "").translate(_ARABIC_DIGITS).casefold()
        if any(
            marker in text
            for marker in ("صباح", "مساء", " am", " pm", "a.m", "p.m")
        ):
            return False
        # 24-hour clock values are already unambiguous.
        if re.search(r"(?:الساعة|الساعه|ساعة|ساعه|at)\s*(?:1[3-9]|2[0-3])(?::[0-5]\d)?", text):
            return False
        return bool(
            re.search(
                r"(?:الساعة|الساعه|ساعة|ساعه|at)\s*(?:[1-9]|1[0-2])(?::[0-5]\d)?(?!\d)",
                text,
            )
        )
