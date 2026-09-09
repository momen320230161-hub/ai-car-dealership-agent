"""Sales-lead model."""

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.models.base import TimestampMixin


class Lead(TimestampMixin, db.Model):
    __tablename__ = "leads"
    __table_args__ = (CheckConstraint("status IN ('new', 'contacted', 'qualified', 'negotiating', 'won', 'lost')", name="ck_leads_status"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True)
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vehicles.id", ondelete="SET NULL"), index=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="new", index=True)
    notes: Mapped[str | None] = mapped_column(Text)

    customer: Mapped["Customer"] = relationship(back_populates="leads")
    vehicle: Mapped["Vehicle | None"] = relationship(back_populates="leads")
    conversations: Mapped[list["Conversation"]] = relationship(back_populates="lead")
