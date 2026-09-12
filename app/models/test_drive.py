"""Relational TestDriveRequest model."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Time,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import GUID, Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.car import Car
    from app.models.conversation import ConversationSession


class TestDriveRequest(Base, TimestampMixin):
    """Persisted test-drive request; workflow logic is implemented later."""

    __tablename__ = "test_drive_requests"
    __test__ = False

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        ForeignKey(
            "conversation_sessions.id",
            ondelete="RESTRICT",
            name="fk_test_drive_requests_session_id_conv_sessions",
        ),
        nullable=False,
    )
    car_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(
            "cars.id",
            ondelete="RESTRICT",
            name="fk_test_drive_requests_car_id_cars",
        ),
        nullable=False,
    )
    customer_name: Mapped[str] = mapped_column(String(150), nullable=False)
    phone: Mapped[str] = mapped_column(String(50), nullable=False)
    preferred_date: Mapped[date] = mapped_column(Date, nullable=False)
    preferred_time: Mapped[time] = mapped_column(Time, nullable=False)
    status: Mapped[str] = mapped_column(
        String(30),
        default="NEW",
        server_default="NEW",
        nullable=False,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    session: Mapped[ConversationSession] = relationship(
        "ConversationSession",
        back_populates="test_drive_requests",
    )
    car: Mapped[Car] = relationship("Car", back_populates="test_drive_requests")

    __table_args__ = (
        CheckConstraint(
            "status IN ('NEW', 'CONFIRMED', 'COMPLETED', 'CANCELLED')",
            name="test_drive_status_check",
        ),
        CheckConstraint(
            "length(trim(customer_name)) > 0",
            name="test_drive_customer_name_not_blank_check",
        ),
        CheckConstraint(
            "length(trim(phone)) > 0",
            name="test_drive_phone_not_blank_check",
        ),
        Index("ix_test_drive_requests_session_id", "session_id"),
        Index("ix_test_drive_requests_car_id", "car_id"),
        Index("ix_test_drive_requests_status", "status"),
        Index("ix_test_drive_requests_session_status", "session_id", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<TestDriveRequest id={self.id} customer={self.customer_name!r} "
            f"car_id={self.car_id} status={self.status!r}>"
        )
