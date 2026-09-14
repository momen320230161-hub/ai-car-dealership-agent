"""Structured preference updates and deterministic stale-state invalidation."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.domain.catalog_filters import CatalogFilters
from app.models.car import Car
from app.models.conversation import ConversationSession
from app.models.recommendation import RecommendationSnapshot
from app.repositories.catalog_repository import CatalogRepository


@dataclass(frozen=True, slots=True)
class StateUpdateResult:
    preferences: dict[str, Any]
    snapshot_invalidated: bool
    selected_car_cleared: bool


class ConversationStateService:
    """Treat structured preferences as current truth and retain only compatible state."""

    def __init__(self, session: Session):
        self.session = session
        self.catalog_repository = CatalogRepository(session)

    def update_preferences(
        self, session_id: uuid.UUID, updates: Mapping[str, Any]
    ) -> StateUpdateResult:
        try:
            conversation = self.session.scalar(
                select(ConversationSession)
                .where(ConversationSession.id == session_id)
                .with_for_update()
            )
            if conversation is None:
                raise LookupError("Conversation session was not found")

            merged = dict(conversation.preferences or {})
            for name, value in updates.items():
                if value is None or (isinstance(value, str) and not value.strip()):
                    merged.pop(name, None)
                else:
                    merged[name] = value
            filters = CatalogFilters.from_mapping(merged)
            preferences = filters.as_dict()
            conversation.preferences = preferences

            selected_car_cleared = False
            if conversation.selected_car_id is not None:
                selected = self.catalog_repository.get(
                    conversation.selected_car_id, active_only=False
                )
                if selected is None or not self.car_matches_preferences(selected, filters):
                    conversation.selected_car_id = None
                    selected_car_cleared = True

            snapshot_invalidated = False
            if conversation.active_recommendation_snapshot_id is not None:
                snapshot = self.session.scalar(
                    select(RecommendationSnapshot)
                    .where(
                        RecommendationSnapshot.id == conversation.active_recommendation_snapshot_id,
                        RecommendationSnapshot.session_id == session_id,
                    )
                    .options(selectinload(RecommendationSnapshot.items))
                )
                if snapshot is None or snapshot.status != "active":
                    conversation.active_recommendation_snapshot_id = None
                else:
                    car_ids = [item.car_id for item in snapshot.items]
                    visible_cars = self.catalog_repository.get_many(car_ids, active_only=False)
                    incompatible = len(visible_cars) != len(car_ids) or any(
                        not self.car_matches_preferences(car, filters) for car in visible_cars
                    )
                    if incompatible:
                        snapshot.status = "invalidated"
                        conversation.active_recommendation_snapshot_id = None
                        snapshot_invalidated = True

            self.session.commit()
            return StateUpdateResult(
                preferences=preferences,
                snapshot_invalidated=snapshot_invalidated,
                selected_car_cleared=selected_car_cleared,
            )
        except Exception:
            self.session.rollback()
            raise

    @staticmethod
    def car_matches_preferences(car: Car, filters: CatalogFilters) -> bool:
        if not car.active:
            return False
        if filters.condition is not None and car.condition != filters.condition:
            return False
        for name in ("brand", "model", "body_type", "transmission", "fuel_type"):
            expected = getattr(filters, name)
            actual = getattr(car, name)
            if expected is not None and (
                actual is None or actual.casefold() != expected.casefold()
            ):
                return False
        if filters.min_year is not None and car.year < filters.min_year:
            return False
        if filters.max_year is not None and car.year > filters.max_year:
            return False
        price = Decimal(car.price_egp)
        if filters.min_price is not None and price < filters.min_price:
            return False
        if filters.max_price is not None and price > filters.max_price:
            return False
        if filters.max_mileage is not None and car.condition == "used":
            if car.mileage_km is None or car.mileage_km > filters.max_mileage:
                return False
        return True
