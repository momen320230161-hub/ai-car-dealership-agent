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
_DAYPART_MARKERS = (
    "صباح",
    "الصباح",
    "الصبح",
    "مساء",
    "المساء",
    "عصر",
    "العصر",
    "ظهر",
    "الظهر",
    " am",
    " pm",
    "a.m",
    "p.m",
)
_DAYPART_ONLY_RE = re.compile(
    r"^\s*(?:الصباح|الصبح|صباح(?:ا|اً)?|المساء|مساء(?:ا|ً)?|"
    r"العصر|عصر(?:ا|اً)?|الظهر|ظهر(?:ا|اً)?|am|pm)\s*$",
    re.IGNORECASE,
)
_BARE_CLOCK_RE = re.compile(
    r"^\s*(?:(?:الساعة|الساعه|ساعة|ساعه)\s*)?([1-9]|1[0-2])\s*$",
    re.IGNORECASE,
)


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
        field_hint: str | None = None,
    ) -> dict[str, Any]:
        # Clean rows polluted by older builds before strict CatalogFilters sees them again.
        self.preference_state.strip_legacy_contact_preferences(session_id)

        conversation_before = self.session.get(ConversationSession, session_id)
        if conversation_before is None:
            raise LookupError("Conversation session was not found")
        pending_before = dict(conversation_before.pending_action or {})
        effective_message = self._resolve_daypart_only_followup(pending_before, message)
        bare_ambiguous_hour = self._pending_bare_clock_hour(pending_before, message)

        result = super().prepare_action(
            session_id,
            requested_intent,
            effective_message,
            car_reference=car_reference,
            field_hint=field_hint,
        )
        intent = str(result.get("intent") or requested_intent)
        ambiguous_hour = bare_ambiguous_hour
        if ambiguous_hour is None and self._has_ambiguous_clock_time(effective_message):
            ambiguous_hour = self._ambiguous_clock_hour(effective_message)
        if intent == "test_drive" and ambiguous_hour is not None:
            result = self._remove_ambiguous_time(
                session_id,
                result,
                candidate_hour=ambiguous_hour,
            )

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
            field_hint=None,
        )
        if result.get("ambiguous_time"):
            refreshed = self._remove_ambiguous_time(
                session_id,
                refreshed,
                candidate_hour=result.get("ambiguous_time_hour"),
            )
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
        *,
        candidate_hour: Any = None,
    ) -> dict[str, Any]:
        """Keep ambiguous 12-hour input pending until a daypart is explicit."""
        fields = dict(result.get("fields") or {})
        fields.pop("preferred_time", None)

        hour: int | None = None
        try:
            parsed_hour = int(candidate_hour) if candidate_hour is not None else None
            if parsed_hour is not None and 1 <= parsed_hour <= 12:
                hour = parsed_hour
        except (TypeError, ValueError):
            hour = None

        conversation = self.session.get(ConversationSession, session_id)
        if conversation is None:
            raise LookupError("Conversation session was not found")
        pending = dict(conversation.pending_action or {})
        pending_fields = dict(pending.get("fields") or {})
        pending_fields.pop("preferred_time", None)
        pending["fields"] = pending_fields
        if hour is not None:
            pending["ambiguous_time_hour"] = hour
        else:
            pending.pop("ambiguous_time_hour", None)
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
                **({"ambiguous_time_hour": hour} if hour is not None else {}),
            }
        )
        return updated

    @classmethod
    def _has_ambiguous_clock_time(cls, message: str) -> bool:
        text = str(message or "").translate(_ARABIC_DIGITS).casefold()
        if any(marker in text for marker in _DAYPART_MARKERS):
            return False
        # 24-hour clock values are already unambiguous.
        if re.search(
            r"(?:الساعة|الساعه|ساعة|ساعه|at)\s*(?:1[3-9]|2[0-3])(?::[0-5]\d)?",
            text,
        ):
            return False
        return cls._ambiguous_clock_hour(text) is not None

    @staticmethod
    def _ambiguous_clock_hour(message: str) -> int | None:
        text = str(message or "").translate(_ARABIC_DIGITS).casefold()
        match = re.search(
            r"(?:الساعة|الساعه|ساعة|ساعه|at)\s*([1-9]|1[0-2])(?::[0-5]\d)?(?!\d)",
            text,
        )
        return int(match.group(1)) if match else None

    @staticmethod
    def _pending_bare_clock_hour(pending: Mapping[str, Any], message: str) -> int | None:
        if pending.get("type") != "test_drive":
            return None
        fields = dict(pending.get("fields") or {})
        if fields.get("preferred_time") not in (None, ""):
            return None
        text = str(message or "").translate(_ARABIC_DIGITS).casefold()
        if any(marker in text for marker in _DAYPART_MARKERS):
            return None
        match = _BARE_CLOCK_RE.fullmatch(text)
        return int(match.group(1)) if match else None

    @staticmethod
    def _resolve_daypart_only_followup(pending: Mapping[str, Any], message: str) -> str:
        if pending.get("type") != "test_drive":
            return message
        fields = dict(pending.get("fields") or {})
        if fields.get("preferred_time") not in (None, ""):
            return message
        candidate = pending.get("ambiguous_time_hour")
        try:
            hour = int(candidate)
        except (TypeError, ValueError):
            return message
        if not 1 <= hour <= 12:
            return message
        text = str(message or "").translate(_ARABIC_DIGITS).casefold().strip()
        if not _DAYPART_ONLY_RE.fullmatch(text):
            return message
        return f"الساعة {hour} {message.strip()}"
