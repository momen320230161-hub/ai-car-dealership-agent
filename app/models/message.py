"""Relational ChatMessage model for session dialogue history."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import GUID, Base, utc_now

if TYPE_CHECKING:
    from app.models.conversation import ConversationSession


class ChatMessage(Base):
    """One persisted message within a conversation session."""

    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        ForeignKey(
            "conversation_sessions.id",
            ondelete="CASCADE",
            name="fk_chat_messages_session_id_conversation_sessions",
        ),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=utc_now,
        nullable=False,
    )

    session: Mapped[ConversationSession] = relationship(
        "ConversationSession",
        back_populates="messages",
    )

    __table_args__ = (
        CheckConstraint(
            "role IN ('user', 'assistant', 'system', 'tool')",
            name="chat_message_role_check",
        ),
        CheckConstraint(
            "length(trim(content)) > 0",
            name="chat_message_content_not_blank_check",
        ),
        Index("ix_chat_messages_session_id", "session_id"),
        Index("ix_chat_messages_session_created", "session_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<ChatMessage id={self.id} session_id={self.session_id} role={self.role!r}>"
