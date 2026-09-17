"""Verified reusable customer contact memory derived from persisted application data."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.conversation import ConversationSession
from app.models.lead import SalesLead
from app.models.test_drive import TestDriveRequest
from app.models.user import UserProfile


@dataclass(frozen=True, slots=True)
class CustomerMemory:
    """Small contact-memory view; catalog preferences intentionally do not live here."""

    customer_name: str | None = None
    phone: str | None = None
    email: str | None = None
    scope: str = "none"

    def as_fields(self) -> dict[str, str]:
        fields: dict[str, str] = {}
        if self.customer_name:
            fields["customer_name"] = self.customer_name
        if self.phone:
            fields["phone"] = self.phone
        if self.email:
            fields["email"] = self.email
        return fields

    def safe_context(self) -> dict[str, Any]:
        """Expose no customer PII to the free-form response composer.

        Verified contact memory exists to complete deterministic business actions without
        asking the customer for the same data again. The customer-facing LLM does not need
        the stored name, phone suffix, email, or memory provenance in ordinary conversation.
        """
        return {"available_for_actions": bool(self.as_fields())}


class CustomerMemoryService:
    """Resolve reusable contact data without mixing it into vehicle preferences.

    Current-session action rows outrank older authenticated-user history. The authenticated
    profile is only a final fallback for display name/email; phone is reused only after it has
    been verified in a real TestDriveRequest or SalesLead row.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    def load(self, session_id: uuid.UUID) -> CustomerMemory:
        conversation = self.session.get(ConversationSession, session_id)
        if conversation is None:
            raise LookupError("Conversation session was not found")

        values: dict[str, str | None] = {
            "customer_name": None,
            "phone": None,
            "email": None,
        }
        scope = "none"

        current_rows = self._contact_rows([conversation.id])
        if current_rows:
            self._fill_missing(values, current_rows)
            scope = "current_session"

        if conversation.user_id is not None and any(value is None for value in values.values()):
            user_session_ids = list(
                self.session.scalars(
                    select(ConversationSession.id)
                    .where(
                        ConversationSession.user_id == conversation.user_id,
                        ConversationSession.id != conversation.id,
                    )
                    .order_by(ConversationSession.updated_at.desc())
                    .limit(25)
                )
            )
            historical_rows = self._contact_rows(user_session_ids)
            if historical_rows:
                before = dict(values)
                self._fill_missing(values, historical_rows)
                if values != before and scope == "none":
                    scope = "authenticated_user_history"
                elif values != before:
                    scope = "current_session+authenticated_user_history"

        if conversation.user_id is not None:
            profile = self.session.get(UserProfile, conversation.user_id)
            if profile is not None:
                if not values["customer_name"] and profile.display_name:
                    values["customer_name"] = profile.display_name.strip() or None
                    if values["customer_name"] and scope == "none":
                        scope = "profile"
                if not values["email"] and profile.email:
                    values["email"] = profile.email.strip() or None
                    if values["email"] and scope == "none":
                        scope = "profile"

        return CustomerMemory(
            customer_name=values["customer_name"],
            phone=values["phone"],
            email=values["email"],
            scope=scope,
        )

    def _contact_rows(self, session_ids: list[uuid.UUID]) -> list[SalesLead | TestDriveRequest]:
        if not session_ids:
            return []
        leads = list(
            self.session.scalars(
                select(SalesLead)
                .where(SalesLead.session_id.in_(session_ids))
                .order_by(SalesLead.created_at.desc(), SalesLead.id.desc())
                .limit(12)
            )
        )
        drives = list(
            self.session.scalars(
                select(TestDriveRequest)
                .where(TestDriveRequest.session_id.in_(session_ids))
                .order_by(TestDriveRequest.created_at.desc(), TestDriveRequest.id.desc())
                .limit(12)
            )
        )
        rows: list[SalesLead | TestDriveRequest] = [*leads, *drives]
        rows.sort(key=self._created_sort_key, reverse=True)
        return rows

    @staticmethod
    def _created_sort_key(row: SalesLead | TestDriveRequest) -> float:
        created_at = getattr(row, "created_at", None)
        return created_at.timestamp() if created_at is not None else 0.0

    @staticmethod
    def _fill_missing(
        values: dict[str, str | None],
        rows: list[SalesLead | TestDriveRequest],
    ) -> None:
        for row in rows:
            if not values["customer_name"] and row.customer_name:
                values["customer_name"] = row.customer_name.strip() or None
            if not values["phone"] and row.phone:
                values["phone"] = row.phone.strip() or None
            if isinstance(row, SalesLead) and not values["email"] and row.email:
                values["email"] = row.email.strip() or None
            if all(values.values()):
                return
