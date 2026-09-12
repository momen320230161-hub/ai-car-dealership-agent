"""Visible-list, ordinal, comparison, and preference-state unit coverage."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.domain.ordinal_resolver import InvalidOrdinalError, parse_ordinal
from app.models.car import Car
from app.models.conversation import ConversationSession
from app.models.recommendation import RecommendationSnapshot
from app.services.conversation_state_service import ConversationStateService
from app.services.recommendation_service import (
    RecommendationService,
    VisibleRecommendationError,
)


def _car(source_id: str, **overrides) -> Car:
    values = {
        "brand": "Toyota",
        "model": "Corolla",
        "year": 2023,
        "condition": "used",
        "price_egp": Decimal("900000"),
        "body_type": "SUV",
        "transmission": "Automatic",
        "fuel_type": "Gasoline",
        "mileage_km": 30000,
        "source": "recommendation-test",
        "source_id": source_id,
    }
    values.update(overrides)
    return Car(**values)


@pytest.mark.parametrize(
    ("reference", "position"),
    [
        (1, 1),
        ("1", 1),
        ("#2", 2),
        ("first", 1),
        ("first one", 1),
        ("second", 2),
        ("third", 3),
        ("الأول", 1),
        ("الاول", 1),
        ("اول", 1),
        ("أول", 1),
        ("اول واحد", 1),
        ("الأول واحد", 1),
        ("التاني", 2),
        ("الثاني", 2),
        ("الثالث", 3),
        ("التالت", 3),
    ],
)
def test_controlled_ordinals(reference, position):
    assert parse_ordinal(reference) == position


@pytest.mark.parametrize("reference", [0, -1, True, "fourth", "car 1", "#0"])
def test_unsupported_ordinals_fail_cleanly(reference):
    with pytest.raises(InvalidOrdinalError):
        parse_ordinal(reference)


def test_snapshot_persists_exact_visible_order_and_ignores_hidden_variants(db_session):
    hidden = _car("hidden", price_egp=Decimal("100"))
    first = _car("first", brand="Kia")
    second = _car("second", brand="Hyundai")
    conversation = ConversationSession()
    other = ConversationSession()
    db_session.add_all([hidden, first, second, conversation, other])
    db_session.commit()

    service = RecommendationService(db_session)
    snapshot = service.create_visible_snapshot(
        conversation.id,
        [second.id, first.id],
        {"body_type": "SUV"},
    )

    assert snapshot.sequence_no == 1
    assert [(item.position, item.car_id) for item in snapshot.items] == [
        (1, second.id),
        (2, first.id),
    ]
    assert service.resolve_visible_item(conversation.id, "first").car_id == second.id
    assert service.resolve_visible_item(conversation.id, "التاني").car_id == first.id
    with pytest.raises(VisibleRecommendationError):
        service.resolve_visible_item(other.id, 1)
    with pytest.raises(VisibleRecommendationError, match="out of range"):
        service.resolve_visible_item(conversation.id, 3)


def test_new_snapshot_supersedes_old_and_ordinals_never_fall_back_to_history(db_session):
    cars = [_car("one"), _car("two"), _car("three")]
    conversation = ConversationSession()
    db_session.add_all([*cars, conversation])
    db_session.commit()
    service = RecommendationService(db_session)

    old = service.create_visible_snapshot(conversation.id, [cars[0].id, cars[1].id])
    new = service.create_visible_snapshot(conversation.id, [cars[2].id])

    db_session.refresh(old)
    assert old.status == "superseded"
    assert new.sequence_no == 2
    assert service.resolve_visible_item(conversation.id, 1).car_id == cars[2].id
    with pytest.raises(VisibleRecommendationError):
        service.resolve_visible_item(conversation.id, 2)


def test_visible_selection_and_comparison_use_exact_persisted_ids(db_session):
    hidden = _car("hidden", price_egp=Decimal("1"))
    first = _car("first", engine_capacity_cc=None, horsepower=None)
    second = _car("second", brand="Kia", engine_capacity_cc=1600)
    conversation = ConversationSession()
    db_session.add_all([hidden, first, second, conversation])
    db_session.commit()
    service = RecommendationService(db_session)
    service.create_visible_snapshot(conversation.id, [second.id, first.id])

    selected = service.select_visible_car(conversation.id, "#2")
    comparison = service.compare_visible(conversation.id, ["first", "second"])

    db_session.refresh(conversation)
    assert selected.id == first.id
    assert conversation.selected_car_id == first.id
    assert comparison["car_ids"] == [second.id, first.id]
    assert comparison["cars"][1]["engine_capacity_cc"] is None
    assert comparison["cars"][1]["horsepower"] is None
    assert hidden.id not in comparison["car_ids"]


def test_snapshot_creation_rejects_invalid_lists_without_partial_state(db_session):
    active = _car("active")
    inactive = _car("inactive", active=False)
    conversation = ConversationSession()
    db_session.add_all([active, inactive, conversation])
    db_session.commit()
    service = RecommendationService(db_session)

    with pytest.raises(VisibleRecommendationError):
        service.create_visible_snapshot(conversation.id, [active.id, inactive.id])

    db_session.refresh(conversation)
    assert conversation.active_recommendation_snapshot_id is None
    assert db_session.scalar(select(func.count()).select_from(RecommendationSnapshot)) == 0
    with pytest.raises(ValueError):
        service.create_visible_snapshot(conversation.id, [active.id, active.id])


def test_compatible_preferences_preserve_selection_and_visible_snapshot(db_session):
    first = _car("first", price_egp=Decimal("900000"))
    second = _car("second", price_egp=Decimal("1100000"))
    conversation = ConversationSession(preferences={"condition": "used"})
    db_session.add_all([first, second, conversation])
    db_session.commit()
    recommendation = RecommendationService(db_session)
    snapshot = recommendation.create_visible_snapshot(
        conversation.id, [first.id, second.id], conversation.preferences
    )
    recommendation.select_visible_car(conversation.id, 1)

    result = ConversationStateService(db_session).update_preferences(
        conversation.id, {"transmission": "automatic"}
    )

    db_session.refresh(conversation)
    db_session.refresh(snapshot)
    assert result.snapshot_invalidated is False
    assert result.selected_car_cleared is False
    assert conversation.selected_car_id == first.id
    assert conversation.active_recommendation_snapshot_id == snapshot.id
    assert snapshot.status == "active"


def test_budget_change_invalidates_list_but_preserves_compatible_selection(db_session):
    first = _car("first", price_egp=Decimal("900000"))
    second = _car("second", price_egp=Decimal("1100000"))
    conversation = ConversationSession(preferences={"condition": "used"})
    db_session.add_all([first, second, conversation])
    db_session.commit()
    recommendation = RecommendationService(db_session)
    snapshot = recommendation.create_visible_snapshot(conversation.id, [first.id, second.id])
    recommendation.select_visible_car(conversation.id, 1)

    result = ConversationStateService(db_session).update_preferences(
        conversation.id, {"max_price": 1_000_000}
    )

    db_session.refresh(conversation)
    db_session.refresh(snapshot)
    assert result.snapshot_invalidated is True
    assert result.selected_car_cleared is False
    assert conversation.active_recommendation_snapshot_id is None
    assert conversation.selected_car_id == first.id
    assert snapshot.status == "invalidated"


@pytest.mark.parametrize(
    "updates",
    [
        {"condition": "new"},
        {"body_type": "Sedan"},
        {"min_year": 2024},
        {"max_mileage": 10000},
    ],
)
def test_incompatible_preference_changes_clear_selection_and_invalidate(db_session, updates):
    car = _car("selected")
    conversation = ConversationSession(preferences={"condition": "used"})
    db_session.add_all([car, conversation])
    db_session.commit()
    recommendation = RecommendationService(db_session)
    snapshot = recommendation.create_visible_snapshot(conversation.id, [car.id])
    recommendation.select_visible_car(conversation.id, 1)

    result = ConversationStateService(db_session).update_preferences(conversation.id, updates)

    db_session.refresh(conversation)
    db_session.refresh(snapshot)
    assert result.snapshot_invalidated is True
    assert result.selected_car_cleared is True
    assert conversation.selected_car_id is None
    assert conversation.active_recommendation_snapshot_id is None
    assert snapshot.status == "invalidated"


def test_preference_updates_are_session_isolated(db_session):
    car_a = _car("a")
    car_b = _car("b", brand="Kia")
    session_a = ConversationSession(preferences={"condition": "used"})
    session_b = ConversationSession(preferences={"condition": "used"})
    db_session.add_all([car_a, car_b, session_a, session_b])
    db_session.commit()
    recommendations = RecommendationService(db_session)
    snapshot_a = recommendations.create_visible_snapshot(session_a.id, [car_a.id])
    snapshot_b = recommendations.create_visible_snapshot(session_b.id, [car_b.id])
    recommendations.select_visible_car(session_b.id, 1)

    ConversationStateService(db_session).update_preferences(
        session_a.id, {"brand": "Kia"}
    )

    db_session.refresh(session_b)
    db_session.refresh(snapshot_a)
    db_session.refresh(snapshot_b)
    assert snapshot_a.status == "invalidated"
    assert snapshot_b.status == "active"
    assert session_b.active_recommendation_snapshot_id == snapshot_b.id
    assert session_b.selected_car_id == car_b.id
