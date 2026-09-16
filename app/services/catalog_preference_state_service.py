"""Vehicle-preference state that safely drops legacy non-catalog customer fields."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import fields
from typing import Any

from sqlalchemy.orm import Session

from app.domain.catalog_filters import CatalogFilters
from app.models.conversation import ConversationSession
from app.services.conversation_state_service import ConversationStateService, StateUpdateResult

_CATALOG_PREFERENCE_KEYS = {field.name for field in fields(CatalogFilters)}


def catalog_only_preferences(values: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return only keys that belong to the strict structured catalog filter schema."""
    if not values:
        return {}
    return {name: value for name, value in values.items() if name in _CATALOG_PREFERENCE_KEYS}


class CatalogPreferenceStateService(ConversationStateService):
    """Keep customer identity/contact fields out of vehicle preference state."""

    def __init__(self, session: Session) -> None:
        super().__init__(session)

    def update_preferences(
        self,
        session_id: uuid.UUID,
        updates: Mapping[str, Any],
    ) -> StateUpdateResult:
        conversation = self.session.get(ConversationSession, session_id)
        if conversation is None:
            raise LookupError("Conversation session was not found")

        clean_existing = catalog_only_preferences(conversation.preferences)
        if clean_existing != dict(conversation.preferences or {}):
            conversation.preferences = clean_existing
            self.session.flush()

        clean_updates = catalog_only_preferences(updates)
        return super().update_preferences(session_id, clean_updates)

    def strip_legacy_contact_preferences(self, session_id: uuid.UUID) -> bool:
        """Persistently remove old customer_name/phone/email keys left by earlier builds."""
        conversation = self.session.get(ConversationSession, session_id)
        if conversation is None:
            raise LookupError("Conversation session was not found")
        before = dict(conversation.preferences or {})
        after = catalog_only_preferences(before)
        if after == before:
            return False
        conversation.preferences = after
        self.session.commit()
        return True
