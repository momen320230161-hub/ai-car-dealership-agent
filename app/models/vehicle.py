"""Vehicle inventory model."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Index, Integer, Numeric, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.models.base import TimestampMixin


class Vehicle(TimestampMixin, db.Model):
    __tablename__ = "vehicles"
    __table_args__ = (
        CheckConstraint("price_egp >= 0", name="ck_vehicles_price_nonnegative"),
        CheckConstraint("kilometers IS NULL OR kilometers >= 0", name="ck_vehicles_kilometers_nonnegative"),
        CheckConstraint("engine_capacity_cc IS NULL OR engine_capacity_cc > 0", name="ck_vehicles_engine_positive"),
        CheckConstraint("horsepower IS NULL OR horsepower > 0", name="ck_vehicles_horsepower_positive"),
        CheckConstraint("condition IN ('new', 'used')", name="ck_vehicles_condition"),
        CheckConstraint("year >= 1900 AND year <= 2100", name="ck_vehicles_year_range"),
        Index("ix_vehicles_brand_model", "brand", "model"),
        Index("ix_vehicles_brand_model_year", "brand", "model", "year"),
        Index("ix_vehicles_condition_price", "condition", "price_egp"),
        Index("ix_vehicles_fuel_type", "fuel_type"),
        Index("ix_vehicles_transmission_type", "transmission_type"),
        Index("ix_vehicles_body_type", "body_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    brand: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    condition: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    price_egp: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    kilometers: Mapped[int | None] = mapped_column(BigInteger)
    fuel_type: Mapped[str | None] = mapped_column(String(64))
    transmission_type: Mapped[str] = mapped_column(String(32), nullable=False)
    engine_capacity_cc: Mapped[int | None] = mapped_column(Integer)
    body_type: Mapped[str | None] = mapped_column(String(64))
    trim: Mapped[str | None] = mapped_column(String(160))
    horsepower: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    color: Mapped[str | None] = mapped_column(String(64))
    # The approved dataset includes a 39-character legacy powertrain label.
    powertrain_type: Mapped[str | None] = mapped_column(String(64))
    vin: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    stock_number: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    source: Mapped[str] = mapped_column(String(255), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    source_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    data_quality_status: Mapped[str] = mapped_column(String(64), nullable=False)
    data_quality_metadata: Mapped[dict] = mapped_column(JSONB().with_variant(db.JSON, "sqlite"), nullable=False, default=dict)

    leads: Mapped[list["Lead"]] = relationship(back_populates="vehicle")
