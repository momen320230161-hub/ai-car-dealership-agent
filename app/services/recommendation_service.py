"""Transaction-safe visible recommendations, ordinals, selection, and comparison."""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.domain.catalog_filters import CatalogFilters
from app.domain.ordinal_resolver import InvalidOrdinalError, parse_ordinal
from app.models.car import Car
from app.models.conversation import ConversationSession
from app.models.recommendation import RecommendationSnapshot, RecommendationSnapshotItem
from app.repositories.catalog_repository import CatalogRepository
from app.services.catalog_service import CatalogService


class VisibleRecommendationError(LookupError):
    """A visible recommendation or requested position is unavailable."""


class RecommendationService:
    """Persist and resolve exactly the list shown to one conversation session."""

    def __init__(self, session: Session):
        self.session = session
        self.catalog_repository = CatalogRepository(session)
        self.catalog_service = CatalogService(session)

    def create_visible_snapshot(
        self,
        session_id: uuid.UUID,
        cars: Sequence[Car | int],
        criteria: CatalogFilters | Mapping[str, Any] | None = None,
    ) -> RecommendationSnapshot:
        """Atomically persist exact visible ordering and activate the complete snapshot."""
        raw_car_ids = [car.id if isinstance(car, Car) else car for car in cars]
        if any(car_id is None for car_id in raw_car_ids):
            raise ValueError("Every visible car must already be persisted")
        car_ids = [int(car_id) for car_id in raw_car_ids]
        if not car_ids:
            raise ValueError("A visible recommendation snapshot cannot be empty")
        if len(set(car_ids)) != len(car_ids):
            raise ValueError("Visible recommendation car IDs must be unique")
        normalized_criteria = (
            criteria.as_dict()
            if isinstance(criteria, CatalogFilters)
            else CatalogFilters.from_mapping(criteria).as_dict()
        )

        try:
            conversation = self.session.scalar(
                select(ConversationSession)
                .where(ConversationSession.id == session_id)
                .with_for_update()
            )
            if conversation is None:
                raise VisibleRecommendationError("Conversation session was not found")

            persisted_cars = self.catalog_repository.get_many(car_ids, active_only=True)
            if len(persisted_cars) != len(car_ids):
                raise VisibleRecommendationError("Every visible car must exist and be active")

            sequence_no = (
                self.session.scalar(
                    select(func.coalesce(func.max(RecommendationSnapshot.sequence_no), 0)).where(
                        RecommendationSnapshot.session_id == session_id
                    )
                )
                + 1
            )
            previous = None
            if conversation.active_recommendation_snapshot_id is not None:
                previous = self.session.get(
                    RecommendationSnapshot, conversation.active_recommendation_snapshot_id
                )
                if previous is not None:
                    previous.status = "superseded"

            snapshot = RecommendationSnapshot(
                session_id=session_id,
                sequence_no=sequence_no,
                criteria=normalized_criteria,
                status="active",
            )
            self.session.add(snapshot)
            self.session.flush()
            self.session.add_all(
                [
                    RecommendationSnapshotItem(
                        snapshot_id=snapshot.id,
                        position=position,
                        car_id=car_id,
                    )
                    for position, car_id in enumerate(car_ids, start=1)
                ]
            )
            self.session.flush()
            conversation.active_recommendation_snapshot_id = snapshot.id
            self.session.commit()
            return snapshot
        except Exception:
            self.session.rollback()
            raise

    def recommend_and_snapshot(
        self,
        session_id: uuid.UUID,
        preferences: CatalogFilters | Mapping[str, Any] | None,
        *,
        limit: int = 3,
    ) -> RecommendationSnapshot | None:
        cars = self.catalog_service.recommend(preferences, limit=limit)
        if not cars:
            return None
        return self.create_visible_snapshot(session_id, cars, preferences)

    def get_active_snapshot(self, session_id: uuid.UUID) -> RecommendationSnapshot | None:
        statement = (
            select(RecommendationSnapshot)
            .join(
                ConversationSession,
                ConversationSession.active_recommendation_snapshot_id == RecommendationSnapshot.id,
            )
            .where(
                ConversationSession.id == session_id,
                RecommendationSnapshot.session_id == session_id,
                RecommendationSnapshot.status == "active",
            )
            .options(selectinload(RecommendationSnapshot.items))
        )
        return self.session.scalar(statement)

    def resolve_visible_item(
        self, session_id: uuid.UUID, reference: int | str
    ) -> RecommendationSnapshotItem:
        try:
            position = parse_ordinal(reference)
        except InvalidOrdinalError:
            raise
        snapshot = self.get_active_snapshot(session_id)
        if snapshot is None:
            raise VisibleRecommendationError("No active visible recommendation list")
        item = next((item for item in snapshot.items if item.position == position), None)
        if item is None:
            raise VisibleRecommendationError(f"Visible position {position} is out of range")
        return item

    def select_visible_car(self, session_id: uuid.UUID, reference: int | str) -> Car:
        position = parse_ordinal(reference)
        try:
            conversation = self.session.scalar(
                select(ConversationSession)
                .where(ConversationSession.id == session_id)
                .with_for_update()
            )
            if conversation is None:
                raise VisibleRecommendationError("Conversation session was not found")
            snapshot = self.session.scalar(
                select(RecommendationSnapshot)
                .where(
                    RecommendationSnapshot.id == conversation.active_recommendation_snapshot_id,
                    RecommendationSnapshot.session_id == session_id,
                    RecommendationSnapshot.status == "active",
                )
                .options(selectinload(RecommendationSnapshot.items))
            )
            if snapshot is None:
                raise VisibleRecommendationError("No active visible recommendation list")
            item = next((item for item in snapshot.items if item.position == position), None)
            if item is None:
                raise VisibleRecommendationError(f"Visible position {position} is out of range")
            car = self.catalog_repository.get(item.car_id, active_only=True)
            if car is None:
                raise VisibleRecommendationError("The visible car is no longer active")
            conversation.selected_car_id = item.car_id
            self.session.commit()
            return car
        except Exception:
            self.session.rollback()
            raise

    def compare_visible(
        self, session_id: uuid.UUID, references: Sequence[int | str]
    ) -> dict[str, Any]:
        if len(references) < 2:
            raise ValueError("At least two visible positions are required")
        positions = [parse_ordinal(reference) for reference in references]
        snapshot = self.get_active_snapshot(session_id)
        if snapshot is None:
            raise VisibleRecommendationError("No active visible recommendation list")
        by_position = {item.position: item.car_id for item in snapshot.items}
        try:
            car_ids = [by_position[position] for position in positions]
        except KeyError as exc:
            raise VisibleRecommendationError(
                f"Visible position {exc.args[0]} is out of range"
            ) from exc
        return self.catalog_service.compare_cars(car_ids)
