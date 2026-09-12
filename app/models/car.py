"""Relational Car model for vehicle inventory."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.lead import SalesLead
    from app.models.test_drive import TestDriveRequest


class Car(Base, TimestampMixin):
    """Represents a vehicle in the dealership inventory."""

    __tablename__ = "cars"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    brand: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    condition: Mapped[str] = mapped_column(String(20), nullable=False)
    price_egp: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    body_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    transmission: Mapped[str | None] = mapped_column(String(50), nullable=True)
    fuel_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    mileage_km: Mapped[int | None] = mapped_column(Integer, nullable=True)
    engine_capacity: Mapped[str | None] = mapped_column(String(50), nullable=True)
    engine_power: Mapped[str | None] = mapped_column(String(50), nullable=True)
    trim: Mapped[str | None] = mapped_column(String(100), nullable=True)
    color: Mapped[str | None] = mapped_column(String(50), nullable=True)
    location: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), nullable=False
    )

    # Relationships
    test_drive_requests: Mapped[list[TestDriveRequest]] = relationship(
        "TestDriveRequest", back_populates="car", passive_deletes="all"
    )
    sales_leads: Mapped[list[SalesLead]] = relationship(
        "SalesLead", back_populates="car", passive_deletes="all"
    )

    __table_args__ = (
        CheckConstraint("condition IN ('new', 'used')", name="car_condition_check"),
        CheckConstraint("price_egp >= 0", name="car_price_positive_check"),
        CheckConstraint(
            "mileage_km IS NULL OR mileage_km >= 0", name="car_mileage_non_negative_check"
        ),
        CheckConstraint("year >= 1900 AND year <= 2100", name="car_year_range_check"),
        UniqueConstraint("source", "source_id", name="uq_cars_source_source_id"),
        Index("ix_cars_condition", "condition"),
        Index("ix_cars_price_egp", "price_egp"),
        Index("ix_cars_brand", "brand"),
        Index("ix_cars_model", "model"),
        Index("ix_cars_brand_model", "brand", "model"),
        Index("ix_cars_year", "year"),
        Index("ix_cars_body_type", "body_type"),
        Index("ix_cars_transmission", "transmission"),
        Index("ix_cars_active", "active"),
    )

    def __repr__(self) -> str:
        return f"<Car id={self.id} brand={self.brand!r} model={self.model!r} year={self.year}>"
