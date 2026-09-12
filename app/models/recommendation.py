"""Relational models for customer-visible recommendation history."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import GUID, Base, PortableJSON, utc_now

if TYPE_CHECKING:
    from app.models.car import Car
    from app.models.conversation import ConversationSession


class RecommendationSnapshot(Base):
    """Ordered recommendation list exactly as it was shown to the customer."""

    __tablename__ = "recommendation_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        ForeignKey(
            "conversation_sessions.id",
            ondelete="CASCADE",
            name="fk_recommendation_snapshots_session_id_conv_sessions",
        ),
        nullable=False,
    )
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    criteria: Mapped[dict[str, Any]] = mapped_column(
        PortableJSON,
        default=dict,
        server_default=text("'{}'"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(50),
        default="active",
        server_default="active",
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=utc_now,
        nullable=False,
    )

    session: Mapped[ConversationSession] = relationship(
        "ConversationSession",
        back_populates="recommendation_snapshots",
        foreign_keys=[session_id],
    )
    items: Mapped[list[RecommendationSnapshotItem]] = relationship(
        "RecommendationSnapshotItem",
        back_populates="snapshot",
        cascade="all, delete-orphan",
        order_by="RecommendationSnapshotItem.position",
    )

    __table_args__ = (
        CheckConstraint("sequence_no > 0", name="rec_snapshot_sequence_no_check"),
        CheckConstraint(
            "status IN ('active', 'superseded', 'invalidated')",
            name="rec_snapshot_status_check",
        ),
        UniqueConstraint(
            "session_id",
            "sequence_no",
            name="uq_rec_snapshots_session_sequence",
        ),
        Index("ix_rec_snapshots_session_id", "session_id"),
        Index("ix_rec_snapshots_session_sequence", "session_id", "sequence_no"),
        Index("ix_rec_snapshots_session_status", "session_id", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<RecommendationSnapshot id={self.id} "
            f"session_id={self.session_id} seq={self.sequence_no}>"
        )


class RecommendationSnapshotItem(Base):
    """One visible position within a recommendation snapshot."""

    __tablename__ = "recommendation_snapshot_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(
            "recommendation_snapshots.id",
            ondelete="CASCADE",
            name="fk_rec_snapshot_items_snapshot_id_rec_snapshots",
        ),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    car_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(
            "cars.id",
            ondelete="RESTRICT",
            name="fk_rec_snapshot_items_car_id_cars",
        ),
        nullable=False,
    )

    snapshot: Mapped[RecommendationSnapshot] = relationship(
        "RecommendationSnapshot",
        back_populates="items",
    )
    car: Mapped[Car] = relationship("Car")

    __table_args__ = (
        CheckConstraint("position > 0", name="rec_snapshot_item_position_check"),
        UniqueConstraint(
            "snapshot_id",
            "position",
            name="uq_rec_snapshot_items_snapshot_position",
        ),
        UniqueConstraint(
            "snapshot_id",
            "car_id",
            name="uq_rec_snapshot_items_snapshot_car",
        ),
        Index("ix_rec_snapshot_items_snapshot_id", "snapshot_id"),
        Index("ix_rec_snapshot_items_car_id", "car_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<RecommendationSnapshotItem snapshot_id={self.snapshot_id} "
            f"pos={self.position} car_id={self.car_id}>"
        )
