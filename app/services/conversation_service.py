"""Bounded anonymous conversation persistence for the agent."""

from uuid import UUID

from sqlalchemy import select

from app.extensions import db
from app.models.base import utcnow
from app.models.conversation import Conversation
from app.models.message import Message


class ConversationService:
    def __init__(self, session=None, history_limit=12):
        self.session = session or db.session
        self.history_limit = history_limit

    def get_or_create(self, conversation_id=None) -> Conversation:
        if conversation_id:
            try:
                identifier = UUID(str(conversation_id))
            except ValueError as exc:
                raise ValueError("invalid conversation ID") from exc
            conversation = self.session.get(Conversation, identifier)
            if conversation is None:
                raise LookupError("conversation not found")
            return conversation
        conversation = Conversation(channel="agent", status="open")
        self.session.add(conversation)
        self.session.commit()
        return conversation

    def add_message(self, conversation_id, sender_type: str, content: str) -> Message:
        if sender_type not in {"customer", "agent"}:
            raise ValueError("unsupported sender_type")
        message = Message(
            conversation_id=conversation_id, sender_type=sender_type, content=content,
            created_at=utcnow(),
        )
        self.session.add(message)
        self.session.commit()
        return message

    def recent_history(self, conversation_id, *, exclude_message_id=None) -> list[dict[str, str]]:
        statement = select(Message).where(Message.conversation_id == conversation_id)
        if exclude_message_id:
            statement = statement.where(Message.id != exclude_message_id)
        messages = self.session.scalars(
            statement.order_by(Message.created_at.desc(), Message.id.desc()).limit(self.history_limit)
        ).all()
        return [{"role": item.sender_type, "content": item.content} for item in reversed(messages)]
