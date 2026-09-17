"""Persistent non-filter dialogue control state for one conversation."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.conversation import ConversationSession


class ConversationDialogueStateError(RuntimeError):
    """Controlled dialogue-state persistence failure."""


class ConversationDialogueStateService:
    """Keep conversational goals separate from structured catalog filters."""

    CATALOG_GOALS = {"recommend"}

    def __init__(self, session: Session) -> None:
        self.session = session

    def set_catalog_goal(self, session_id: uuid.UUID, goal: str | None) -> dict[str, Any]:
        if goal is not None and goal not in self.CATALOG_GOALS:
            raise ValueError(f"Unsupported catalog goal: {goal}")
        try:
            conversation = self.session.scalar(
                select(ConversationSession)
                .where(ConversationSession.id == session_id)
                .with_for_update()
            )
            if conversation is None:
                raise ConversationDialogueStateError("Conversation session was not found")
            state = dict(conversation.dialogue_state or {})
            if goal is None:
                state.pop("catalog_goal", None)
            else:
                state["catalog_goal"] = goal
            conversation.dialogue_state = state
            self.session.commit()
            return state
        except (ConversationDialogueStateError, ValueError):
            self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise ConversationDialogueStateError("Dialogue state could not be updated") from exc
