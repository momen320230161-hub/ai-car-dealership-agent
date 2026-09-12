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
        """Return a deterministic, budget-aware, customer-diverse visible shortlist."""
        filters = (
            preferences
            if isinstance(preferences, CatalogFilters)
            else CatalogFilters.from_mapping(preferences)
        )
        sort_by = "price_desc" if filters.max_price is not None else "year_desc"
        candidate_limit = min(
            CatalogRepository.MAX_PAGE_SIZE,
            max(limit, limit * 10),
        )
        candidates = self.repository.search(
            filters,
            sort_by=sort_by,
            limit=candidate_limit,
            offset=0,
            active_only=True,
        )

        visible: list[Car] = []
        variants: list[Car] = []
        seen_models: set[tuple[str, str]] = set()
        for car in candidates:
            key = (car.brand.casefold(), car.model.casefold())
            if key in seen_models:
                variants.append(car)
                continue
            seen_models.add(key)
            visible.append(car)
            if len(visible) == limit:
                return visible

        for car in variants:
            visible.append(car)
            if len(visible) == limit:
                break
        return visible

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
