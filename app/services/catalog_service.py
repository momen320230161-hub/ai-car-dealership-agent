"""Deterministic structured catalog operations with no inferred vehicle facts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy.orm import Session

from app.domain.catalog_filters import CatalogFilters
from app.models.car import Car
from app.repositories.catalog_repository import CatalogRepository


class CatalogService:
    """Application-facing search, details, comparison, and recommendation behavior."""

    DETAIL_FIELDS = (
        "id",
        "brand",
        "model",
        "year",
        "condition",
        "price_egp",
        "body_type",
        "transmission",
        "fuel_type",
        "mileage_km",
        "engine_capacity_cc",
        "horsepower",
        "powertrain_type",
        "trim",
        "color",
        "location",
        "vin",
        "stock_number",
        "source",
        "source_url",
        "source_id",
        "collected_at",
        "data_quality_status",
        "data_quality_metadata",
        "active",
    )
    COMPARISON_FIELDS = (
        "brand",
        "model",
        "year",
        "condition",
        "price_egp",
        "body_type",
        "transmission",
        "fuel_type",
        "mileage_km",
        "engine_capacity_cc",
        "horsepower",
        "powertrain_type",
        "trim",
    )

    def __init__(self, session: Session):
        self.repository = CatalogRepository(session)

    def search(
        self,
        filters: CatalogFilters | Mapping[str, Any] | None = None,
        *,
        sort_by: str = "price_asc",
        limit: int = 20,
        offset: int = 0,
    ) -> list[Car]:
        return self.repository.search(
            filters, sort_by=sort_by, limit=limit, offset=offset, active_only=True
        )

    def get_car(self, car_id: int) -> Car | None:
        return self.repository.get(car_id, active_only=True)

    def get_car_details(self, car_id: int) -> dict[str, Any] | None:
        car = self.get_car(car_id)
        return None if car is None else self.serialize_details(car)

    def recommend(
        self,
        preferences: CatalogFilters | Mapping[str, Any] | None,
        *,
        limit: int = 3,
    ) -> list[Car]:
        """Rank matching records transparently: newest, then lowest price, then ID."""
        return self.repository.search(
            preferences,
            sort_by="year_desc",
            limit=limit,
            offset=0,
            active_only=True,
        )

    def compare_cars(self, car_ids: Sequence[int]) -> dict[str, Any]:
        if len(car_ids) < 2:
            raise ValueError("At least two cars are required for comparison")
        cars = self.repository.get_many(car_ids, active_only=True)
        if len(cars) != len(car_ids):
            raise LookupError("One or more active cars were not found")
        return {
            "car_ids": list(car_ids),
            "cars": [
                {field: getattr(car, field) for field in self.COMPARISON_FIELDS}
                | {"id": car.id}
                for car in cars
            ],
        }

    @classmethod
    def serialize_details(cls, car: Car) -> dict[str, Any]:
        """Expose recorded fields verbatim; unknown optional values remain ``None``."""
        return {field: getattr(car, field) for field in cls.DETAIL_FIELDS}
