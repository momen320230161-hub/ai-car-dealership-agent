"""Persistent conversation context loading and exactly-once turn persistence."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.conversation import ConversationSession
from app.models.message import ChatMessage
from app.services.catalog_service import CatalogService
from app.services.recommendation_service import RecommendationService


class ConversationContextError(RuntimeError):
    """Controlled persistent-context failure."""


@dataclass(frozen=True, slots=True)
class ConversationContext:
    session_id: uuid.UUID
    preferences: dict[str, Any]
    selected_car_id: int | None
    active_snapshot: dict[str, Any] | None
    pending_action: dict[str, Any] | None
    recent_messages: list[dict[str, Any]]


class ConversationContextService:
    """Own session creation, bounded history loading, and chat-message persistence."""

    def __init__(self, session: Session, *, recent_message_limit: int = 12):
        if not 1 <= recent_message_limit <= 100:
            raise ValueError("recent_message_limit must be between 1 and 100")
        self.session = session
        self.recent_message_limit = recent_message_limit
        self.recommendations = RecommendationService(session)
        self.catalog = CatalogService(session)

    def load_or_create(
        self,
        session_id: uuid.UUID | str | None,
        user_id: uuid.UUID | str | None = None,
    ) -> ConversationContext:
        resolved_session = self._parse_session_id(session_id)
        resolved_user = self._parse_session_id(user_id)
        try:
            conversation = (
                self.session.get(ConversationSession, resolved_session)
                if resolved_session
                else None
            )
            if conversation is not None:
                if resolved_user is not None and conversation.user_id != resolved_user:
                    # User B attempting to access User A's conversation session.
                    # Create a new session for User B instead of leaking User A's data.
                    conversation = ConversationSession(
                        id=uuid.uuid4(),
                        user_id=resolved_user,
                    )
                    self.session.add(conversation)
                    self.session.commit()
            else:
                conversation = ConversationSession(
                    id=resolved_session or uuid.uuid4(),
                    user_id=resolved_user,
                )
                self.session.add(conversation)
                self.session.commit()
            return self.load(conversation.id, user_id=resolved_user)
        except ConversationContextError:
            self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise ConversationContextError("Conversation session could not be loaded") from exc

    def load(
        self,
        session_id: uuid.UUID,
        user_id: uuid.UUID | str | None = None,
    ) -> ConversationContext:
        resolved_user = self._parse_session_id(user_id)
        try:
            conversation = self.session.get(ConversationSession, session_id)
            if conversation is None:
                raise ConversationContextError("Conversation session was not found")
            if resolved_user is not None and conversation.user_id != resolved_user:
                raise ConversationContextError("Access to this conversation session is forbidden")
            snapshot = self.recommendations.get_active_snapshot(session_id)
            snapshot_data = None
            if snapshot is not None:
                items: list[dict[str, Any]] = []
                for item in sorted(snapshot.items, key=lambda value: value.position):
                    car = self.catalog.get_car_details(item.car_id)
                    if car is not None:
                        items.append(
                            {
                                "position": item.position,
                                "car_id": item.car_id,
                                "car": self._json_safe(car),
                            }
                        )
                snapshot_data = {
                    "id": snapshot.id,
                    "sequence_no": snapshot.sequence_no,
                    "criteria": dict(snapshot.criteria or {}),
                    "items": items,
                }
            messages = list(
                self.session.scalars(
                    select(ChatMessage)
                    .where(ChatMessage.session_id == session_id)
                    .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
                    .limit(self.recent_message_limit)
                )
            )
            messages.reverse()
            return ConversationContext(
                session_id=conversation.id,
                preferences=dict(conversation.preferences or {}),
                selected_car_id=conversation.selected_car_id,
                active_snapshot=snapshot_data,
                pending_action=(
                    dict(conversation.pending_action) if conversation.pending_action else None
                ),
                recent_messages=[
                    {
                        "role": message.role,
                        "content": message.content,
                        "created_at": message.created_at.isoformat(),
                    }
                    for message in messages
                ],
            )
        except ConversationContextError:
            raise
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise ConversationContextError("Conversation context could not be loaded") from exc

    def persist_turn(self, session_id: uuid.UUID | str, user_message: Any, response: str) -> None:
        resolved = self._parse_session_id(session_id)
        if resolved is None:
            raise ConversationContextError("Conversation session ID is required")
        if not isinstance(response, str) or not response.strip():
            raise ValueError("Assistant response must not be blank")
        try:
            if self.session.get(ConversationSession, resolved) is None:
                raise ConversationContextError("Conversation session was not found")
            messages = []
            if isinstance(user_message, str) and user_message.strip():
                messages.append(
                    ChatMessage(session_id=resolved, role="user", content=user_message.strip())
                )
            messages.append(
                ChatMessage(session_id=resolved, role="assistant", content=response.strip())
            )
            self.session.add_all(messages)
            self.session.commit()
        except (ConversationContextError, ValueError):
            self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise ConversationContextError("Conversation messages could not be persisted") from exc

    def get_user_conversations(
        self,
        user_id: uuid.UUID | str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        resolved_user = self._parse_session_id(user_id)
        if resolved_user is None:
            return []
        sessions = list(
            self.session.scalars(
                select(ConversationSession)
                .where(ConversationSession.user_id == resolved_user)
                .order_by(ConversationSession.updated_at.desc())
                .limit(limit)
            )
        )
        results = []
        for s in sessions:
            first_msg = self.session.scalar(
                select(ChatMessage.content)
                .where(ChatMessage.session_id == s.id, ChatMessage.role == "user")
                .order_by(ChatMessage.created_at.asc())
                .limit(1)
            )
            title = (
                (first_msg[:40] + "...")
                if first_msg and len(first_msg) > 40
                else (first_msg or "محادثة جديدة")
            )
            results.append(
                {
                    "id": str(s.id),
                    "title": title,
                    "created_at": s.created_at.isoformat(),
                    "updated_at": s.updated_at.isoformat(),
                }
            )
        return results

    @staticmethod
    def _parse_session_id(value: uuid.UUID | str | None) -> uuid.UUID | None:
        if value is None or isinstance(value, uuid.UUID):
            return value
        try:
            return uuid.UUID(str(value))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("session_id must be a valid UUID") from exc

    @classmethod
    def _json_safe(cls, value: Any) -> Any:
        if isinstance(value, Decimal):
            return float(value)
        if hasattr(value, "isoformat"):
            return value.isoformat()
        if isinstance(value, dict):
            return {key: cls._json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [cls._json_safe(item) for item in value]
        return value
