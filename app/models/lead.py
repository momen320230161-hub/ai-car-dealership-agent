"""Relational SalesLead model."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import GUID, Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.car import Car
    from app.models.conversation import ConversationSession


class SalesLead(Base, TimestampMixin):
    """Persisted customer sales lead; creation workflow is implemented later."""

    __tablename__ = "sales_leads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        ForeignKey(
            "conversation_sessions.id",
            ondelete="RESTRICT",
            name="fk_sales_leads_session_id_conv_sessions",
        ),
        nullable=False,
    )
    car_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey(
            "cars.id",
            ondelete="SET NULL",
            name="fk_sales_leads_car_id_cars",
        ),
        nullable=True,
    )
    customer_name: Mapped[str] = mapped_column(String(150), nullable=False)
    phone: Mapped[str] = mapped_column(String(50), nullable=False)
    email: Mapped[str | None] = mapped_column(String(150), nullable=True)
    status: Mapped[str] = mapped_column(
        String(30),
        default="NEW",
        server_default="NEW",
        nullable=False,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)

    session: Mapped[ConversationSession] = relationship(
        "ConversationSession",
        back_populates="sales_leads",
    )
    car: Mapped[Car | None] = relationship("Car", back_populates="sales_leads")

    __table_args__ = (
        CheckConstraint(
            "status IN ('NEW', 'CONTACTED', 'QUALIFIED', 'CLOSED_WON', 'CLOSED_LOST')",
            name="sales_lead_status_check",
        ),
        CheckConstraint(
            "length(trim(customer_name)) > 0",
            name="sales_lead_customer_name_not_blank_check",
        ),
        CheckConstraint(
            "length(trim(phone)) > 0",
            name="sales_lead_phone_not_blank_check",
        ),
        Index("ix_sales_leads_session_id", "session_id"),
        Index("ix_sales_leads_car_id", "car_id"),
        Index("ix_sales_leads_status", "status"),
        Index("ix_sales_leads_session_status", "session_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<SalesLead id={self.id} customer={self.customer_name!r} status={self.status!r}>"
