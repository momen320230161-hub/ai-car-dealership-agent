"""Conversation session model for persistent structured dialogue state."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import GUID, Base, PortableJSON, TimestampMixin

if TYPE_CHECKING:
    from app.models.car import Car
    from app.models.lead import SalesLead
    from app.models.message import ChatMessage
    from app.models.recommendation import RecommendationSnapshot
    from app.models.test_drive import TestDriveRequest
    from app.models.user import UserProfile


class ConversationSession(Base, TimestampMixin):
    """Represents one isolated anonymous or customer conversation session."""

    __tablename__ = "conversation_sessions"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID,
        ForeignKey(
            "user_profiles.id",
            ondelete="CASCADE",
            name="fk_conversation_sessions_user_id_user_profiles",
        ),
        nullable=True,
    )
    preferences: Mapped[dict[str, Any]] = mapped_column(
        PortableJSON,
        default=dict,
        server_default=text("'{}'"),
        nullable=False,
    )
    dialogue_state: Mapped[dict[str, Any]] = mapped_column(
        PortableJSON,
        default=dict,
        server_default=text("'{}'"),
        nullable=False,
    )
    selected_car_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey(
            "cars.id",
            ondelete="SET NULL",
            name="fk_conversation_sessions_selected_car_id_cars",
        ),
        nullable=True,
    )
    active_recommendation_snapshot_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey(
            "recommendation_snapshots.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_conversation_sessions_active_rec_snapshot",
        ),
        nullable=True,
    )
    pending_action: Mapped[dict[str, Any] | None] = mapped_column(PortableJSON, nullable=True)
    status: Mapped[str] = mapped_column(
        String(50),
        default="active",
        server_default="active",
        nullable=False,
    )

    user: Mapped[UserProfile | None] = relationship("UserProfile", back_populates="conversations")
    selected_car: Mapped[Car | None] = relationship("Car", foreign_keys=[selected_car_id])
    active_recommendation_snapshot: Mapped[RecommendationSnapshot | None] = relationship(
        "RecommendationSnapshot",
        foreign_keys=[active_recommendation_snapshot_id],
        post_update=True,
    )
    messages: Mapped[list[ChatMessage]] = relationship(
        "ChatMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatMessage.created_at",
    )
    recommendation_snapshots: Mapped[list[RecommendationSnapshot]] = relationship(
        "RecommendationSnapshot",
        back_populates="session",
        foreign_keys="[RecommendationSnapshot.session_id]",
        cascade="all, delete-orphan",
        order_by="RecommendationSnapshot.sequence_no",
    )
    test_drive_requests: Mapped[list[TestDriveRequest]] = relationship(
        "TestDriveRequest",
        back_populates="session",
        passive_deletes="all",
    )
    sales_leads: Mapped[list[SalesLead]] = relationship(
        "SalesLead",
        back_populates="session",
        passive_deletes="all",
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'closed')",
            name="conversation_session_status_check",
        ),
        Index("ix_conversation_sessions_status", "status"),
        Index("ix_conversation_sessions_user_id", "user_id"),
        Index("ix_conversation_sessions_selected_car_id", "selected_car_id"),
        Index(
            "ix_conversation_sessions_active_recommendation_snapshot_id",
            "active_recommendation_snapshot_id",
        ),
    )

    def __repr__(self) -> str:
        return f"<ConversationSession id={self.id} status={self.status!r}>"
