"""Deterministic structured catalog operations with no inferred vehicle facts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy.orm import Session

from app.domain.catalog_filters import CatalogFilters
from app.models.car import Car
from app.repositories.catalog_repository import CatalogRepository
from app.services.car_image_service import image_url_for_car


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
            filters,
            sort_by=sort_by,
            limit=limit,
            offset=offset,
            active_only=True,
        )

    def count(self, filters: CatalogFilters | Mapping[str, Any] | None = None) -> int:
        return self.repository.count(filters, active_only=True)

    def facet_values(self, field_name: str, *, limit: int = 100) -> list[str]:
        """Return only values that actually exist in the active catalog."""
        return self.repository.facet_values(field_name, active_only=True, limit=limit)

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
        exclude_car_ids: Sequence[int] | None = None,
    ) -> list[Car]:
        """Return a deterministic, intent-aware, customer-diverse visible shortlist."""
        filters = (
            preferences
            if isinstance(preferences, CatalogFilters)
            else CatalogFilters.from_mapping(preferences)
        )
        if filters.model:
            sort_by = "year_desc_mileage_asc" if filters.condition == "used" else "year_desc"
        else:
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

        if exclude_car_ids:
            excluded_set = set(exclude_car_ids)
            candidates = [car for car in candidates if car.id not in excluded_set]

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

    def recommend_with_relaxation(
        self,
        preferences: CatalogFilters | Mapping[str, Any] | None,
        *,
        limit: int = 3,
    ) -> dict[str, Any]:
        """Attempt exact recommendation, then near-budget or condition relaxation.

        If exact search yields 0 results, attempts price relaxation or condition fallback.
        """
        filters = (
            preferences
            if isinstance(preferences, CatalogFilters)
            else CatalogFilters.from_mapping(preferences)
        )
        exact_cars = self.recommend(filters, limit=limit)
        if exact_cars:
            return {"type": "exact", "cars": exact_cars}

        if filters.max_price is not None:
            relaxed_dict = filters.as_dict()
            original_price = float(relaxed_dict["max_price"])
            relaxed_dict["max_price"] = original_price * 1.20
            budget_cars = self.recommend(relaxed_dict, limit=limit)
            if budget_cars:
                return {
                    "type": "price_relaxation",
                    "cars": budget_cars,
                    "original_max_price": original_price,
                    # recommendation order is intentionally price-desc near the budget
                    # ceiling, so the first item is not necessarily the cheapest.
                    "cheapest_price": min(float(car.price_egp) for car in budget_cars),
                }

        if filters.condition is not None:
            relaxed_dict = filters.as_dict()
            current_cond = relaxed_dict.pop("condition")
            cond_cars = self.recommend(relaxed_dict, limit=limit)
            if cond_cars:
                return {
                    "type": "condition_relaxation",
                    "cars": cond_cars,
                    "requested_condition": current_cond,
                    "available_condition": cond_cars[0].condition,
                }

        return {"type": "no_results", "cars": []}

    def compare_cars(self, car_ids: Sequence[int]) -> dict[str, Any]:
        if len(car_ids) < 2:
            raise ValueError("At least two cars are required for comparison")
        cars = self.repository.get_many(car_ids, active_only=True)
        if len(cars) != len(car_ids):
            raise LookupError("One or more active cars were not found")
        return {
            "car_ids": list(car_ids),
            "cars": [
                {field: getattr(car, field) for field in self.COMPARISON_FIELDS} | {"id": car.id}
                for car in cars
            ],
        }

    @classmethod
    def serialize_details(cls, car: Car) -> dict[str, Any]:
        """Expose recorded fields verbatim plus deterministic presentation metadata."""
        payload = {field: getattr(car, field) for field in cls.DETAIL_FIELDS}
        payload["image_url"] = image_url_for_car(car)
        return payload
