"""Regression tests for Phase 6 catalog preference state & explicit model search behavior."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.agent.graph import SalesOrchestrator
from app.agent.llm import DeterministicAgentLLM
from app.models.car import Car
from app.rag.embeddings import DeterministicEmbeddingProvider
from app.services.conversation_context_service import ConversationContextService


def _seed_car(
    db_session,
    *,
    brand: str = "BMW",
    model: str = "X6",
    condition: str = "used",
    price: int = 4_500_000,
    active: bool = True,
    source_id: str = "bmw-x6-1",
) -> Car:
    car = Car(
        brand=brand,
        model=model,
        year=2024,
        condition=condition,
        price_egp=Decimal(price),
        body_type="SUV",
        transmission="Automatic",
        fuel_type="Gasoline",
        mileage_km=15_000 if condition == "used" else None,
        source="test-catalog",
        source_id=source_id,
        active=active,
    )
    db_session.add(car)
    db_session.commit()
    return car


@pytest.fixture
def orchestrator(db_session):
    return SalesOrchestrator(
        session=db_session,
        llm=DeterministicAgentLLM(),
        embedding_provider=DeterministicEmbeddingProvider(),
    )


def test_preference_state_merge_preserves_accumulated_fields(orchestrator, db_session) -> None:
    """Test 1: Input sequence 'عايز BMW ومعايا 5 مليون' -> 'عايزها جديدة' preserve state."""
    session_id = uuid.uuid4()
    context_service = ConversationContextService(db_session)

    res1 = orchestrator.handle_message(session_id, "عايز BMW ومعايا 5 مليون")
    assert res1.errors == ()
    ctx1 = context_service.load(session_id)
    assert ctx1.preferences.get("brand") == "BMW"
    assert ctx1.preferences.get("max_price") == 5000000.0

    res2 = orchestrator.handle_message(session_id, "عايزها جديدة")
    assert res2.errors == ()
    ctx2 = context_service.load(session_id)
    assert ctx2.preferences.get("brand") == "BMW"
    assert ctx2.preferences.get("condition") == "new"
    assert ctx2.preferences.get("max_price") == 5000000.0
    assert "سجلت إنك بتدور على BMW جديدة" in res2.response


def test_explicit_model_request_fallback_when_condition_has_no_results(
    orchestrator, db_session
) -> None:
    """Test 2: Request X6 with active condition=new when only used X6 exists -> fallback message."""
    _seed_car(db_session, brand="BMW", model="X6", condition="used", price=4_500_000)
    session_id = uuid.uuid4()
    context_service = ConversationContextService(db_session)

    # First set brand=BMW and condition=new
    orchestrator.handle_message(session_id, "عايز BMW جديدة")
    ctx = context_service.load(session_id)
    assert ctx.preferences.get("condition") == "new"

    # User asks for X6
    res = orchestrator.handle_message(session_id, "عايزها X6")
    assert res.errors == ()
    expected_msg = (
        "لقيت BMW X6 حسب الكتالوج المسجل، لكنها متاحة كسيارة مستعملة. هل تحب أعرض التفاصيل؟"
    )
    assert expected_msg in res.response

    # Verify condition preference was NOT mutated to 'used'
    ctx_after = context_service.load(session_id)
    assert ctx_after.preferences.get("condition") == "new"
    assert ctx_after.preferences.get("model") == "X6"


def test_direct_matching_model_and_condition_returns_results(orchestrator, db_session) -> None:
    """Test 3: 'عايز BMW X6 مستعملة' should directly return used X6 results."""
    used_car = _seed_car(db_session, brand="BMW", model="X6", condition="used", price=4_500_000)
    session_id = uuid.uuid4()

    res = orchestrator.handle_message(session_id, "عايز BMW X6 مستعملة")
    assert res.errors == ()
    assert res.route == "catalog"
    assert len(res.visible_recommendations) == 1
    assert res.visible_recommendations[0]["car"]["id"] == used_car.id
    assert "BMW X6" in res.response


def test_session_isolation_preserves_independent_preferences(orchestrator, db_session) -> None:
    """Test 4: Verify session isolation between concurrent users."""
    session_a = uuid.uuid4()
    session_b = uuid.uuid4()
    context_service = ConversationContextService(db_session)

    orchestrator.handle_message(session_a, "عايز BMW ومعايا 5 مليون")
    orchestrator.handle_message(session_b, "عايز SUV مستعملة تحت مليون")

    ctx_a = context_service.load(session_a)
    ctx_b = context_service.load(session_b)

    assert ctx_a.preferences.get("brand") == "BMW"
    assert ctx_a.preferences.get("max_price") == 5000000.0
    assert ctx_a.preferences.get("condition") is None

    assert ctx_b.preferences.get("brand") is None
    assert ctx_b.preferences.get("condition") == "used"
    assert ctx_b.preferences.get("body_type") == "SUV"
    assert ctx_b.preferences.get("max_price") == 1000000.0
