"""Relational Car model for the structured dealership catalog."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, PortableJSON, TimestampMixin

if TYPE_CHECKING:
    from app.models.lead import SalesLead
    from app.models.test_drive import TestDriveRequest


class Car(Base, TimestampMixin):
    """Represents one structured catalog vehicle record."""

    __tablename__ = "cars"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    brand: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    condition: Mapped[str] = mapped_column(String(20), nullable=False)
    price_egp: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    body_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    transmission: Mapped[str | None] = mapped_column(String(50), nullable=True)
    fuel_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    mileage_km: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    engine_capacity_cc: Mapped[int | None] = mapped_column(Integer, nullable=True)
    horsepower: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    powertrain_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    trim: Mapped[str | None] = mapped_column(String(100), nullable=True)
    color: Mapped[str | None] = mapped_column(String(50), nullable=True)
    location: Mapped[str | None] = mapped_column(String(100), nullable=True)
    vin: Mapped[str | None] = mapped_column(String(100), nullable=True)
    stock_number: Mapped[str | None] = mapped_column(String(100), nullable=True)

    source: Mapped[str] = mapped_column(String(100), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_id: Mapped[str] = mapped_column(String(255), nullable=False)
    collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    data_quality_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    data_quality_metadata: Mapped[dict[str, Any]] = mapped_column(
        PortableJSON,
        default=dict,
        server_default=text("'{}'"),
        nullable=False,
    )

    active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default=text("true"),
        nullable=False,
    )

    test_drive_requests: Mapped[list[TestDriveRequest]] = relationship(
        "TestDriveRequest",
        back_populates="car",
        passive_deletes="all",
    )
    sales_leads: Mapped[list[SalesLead]] = relationship(
        "SalesLead",
        back_populates="car",
        passive_deletes="all",
    )

    __table_args__ = (
        CheckConstraint("length(trim(brand)) > 0", name="car_brand_not_blank_check"),
        CheckConstraint("length(trim(model)) > 0", name="car_model_not_blank_check"),
        CheckConstraint("condition IN ('new', 'used')", name="car_condition_check"),
        CheckConstraint("price_egp >= 0", name="car_price_non_negative_check"),
        CheckConstraint(
            "mileage_km IS NULL OR mileage_km >= 0",
            name="car_mileage_non_negative_check",
        ),
        CheckConstraint("year >= 1900", name="car_year_minimum_check"),
        CheckConstraint(
            "engine_capacity_cc IS NULL OR engine_capacity_cc > 0",
            name="car_engine_capacity_positive_check",
        ),
        CheckConstraint(
            "horsepower IS NULL OR horsepower >= 0",
            name="car_horsepower_non_negative_check",
        ),
        CheckConstraint("length(trim(source)) > 0", name="car_source_not_blank_check"),
        CheckConstraint("length(trim(source_id)) > 0", name="car_source_id_not_blank_check"),
        UniqueConstraint("source", "source_id", name="uq_cars_source_source_id"),
        Index("ix_cars_active", "active"),
        Index("ix_cars_condition", "condition"),
        Index("ix_cars_price_egp", "price_egp"),
        Index("ix_cars_brand", "brand"),
        Index("ix_cars_model", "model"),
        Index("ix_cars_brand_model", "brand", "model"),
        Index("ix_cars_year", "year"),
        Index("ix_cars_body_type", "body_type"),
        Index("ix_cars_transmission", "transmission"),
        Index("ix_cars_fuel_type", "fuel_type"),
        Index("ix_cars_active_condition_price", "active", "condition", "price_egp"),
    )

    def __repr__(self) -> str:
        return f"<Car id={self.id} brand={self.brand!r} model={self.model!r} year={self.year}>"
