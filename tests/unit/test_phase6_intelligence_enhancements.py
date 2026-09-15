"""Tests for Arabic model resolution, soft relaxation, and filter reset."""

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
    brand: str,
    model: str,
    condition: str = "new",
    price: int = 4_900_000,
    body_type: str = "SUV",
    source_id: str = "intelligence-test-1",
) -> Car:
    car = Car(
        brand=brand,
        model=model,
        year=2025,
        condition=condition,
        price_egp=Decimal(price),
        body_type=body_type,
        transmission="Automatic",
        fuel_type="Gasoline",
        mileage_km=0 if condition == "new" else 10_000,
        source="test-intelligence",
        source_id=source_id,
        active=True,
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


def test_arabic_model_resolution_preserves_model_preference(orchestrator, db_session) -> None:
    """Arabic transliterated model names (e.g., تيجو 4) should map to canonical model Tiggo 4."""
    _seed_car(db_session, brand="Chery", model="Tiggo 4", condition="used", price=930_000)
    session_id = uuid.uuid4()

    res = orchestrator.handle_message(session_id, "عايز تيجو 4 مستعملة")
    assert res.errors == ()
    assert res.route == "catalog"
    context = ConversationContextService(db_session).load(session_id)
    assert context.preferences.get("model") == "Tiggo 4"
    assert "Chery Tiggo 4" in res.response


def test_soft_price_relaxation_suggests_near_budget_cars(orchestrator, db_session) -> None:
    """When budget has 0 exact matches, near-budget cars are suggested instead of no_results."""
    _seed_car(db_session, brand="BMW", model="420i", condition="new", price=4_900_000)
    session_id = uuid.uuid4()

    # User asks for BMW new under 4.5 million (cheapest is 4.9 million)
    res1 = orchestrator.handle_message(session_id, "عايز BMW جديدة")
    assert res1.errors == ()

    res2 = orchestrator.handle_message(session_id, "معايا 4.5 مليون ورشحلي")
    assert res2.errors == ()
    assert "ملقتش عربيات مطابقة تماماً تحت 4,500,000" in res2.response
    assert "BMW 420i" in res2.response
    assert "4,900,000" in res2.response


def test_filter_reset_clears_stored_budget_ceiling(orchestrator, db_session) -> None:
    """Phrases like 'شيل السعر' or 'من غير حد أقصى' clear max_price filter."""
    session_id = uuid.uuid4()
    context_service = ConversationContextService(db_session)

    orchestrator.handle_message(session_id, "عايز BMW ومعايا 4 مليون")
    ctx1 = context_service.load(session_id)
    assert ctx1.preferences.get("max_price") == 4000000.0

    orchestrator.handle_message(session_id, "شيل حد السعر وخليها من غير حد أقصى")
    ctx2 = context_service.load(session_id)
    assert ctx2.preferences.get("max_price") is None
    assert ctx2.preferences.get("brand") == "BMW"


def test_global_reset_clears_all_preferences(orchestrator, db_session) -> None:
    """Phrases like 'من الأول' or 'تصفير التفضيلات' clear all stored filters."""
    session_id = uuid.uuid4()
    context_service = ConversationContextService(db_session)

    orchestrator.handle_message(session_id, "عايز BMW جديدة تحت 5 مليون")
    ctx1 = context_service.load(session_id)
    assert ctx1.preferences.get("brand") == "BMW"
    assert ctx1.preferences.get("condition") == "new"

    orchestrator.handle_message(session_id, "تصفير التفضيلات وابدأ من الأول")
    ctx2 = context_service.load(session_id)
    assert ctx2.preferences == {}


def test_dialect_condition_extraction_and_pagination(orchestrator, db_session) -> None:
    """Test dialect terms 'استعمال خفيف', 'اعرضلي', and pagination 'في حاجات تاني'."""
    _seed_car(
        db_session,
        brand="BYD",
        model="F3",
        condition="used",
        price=500_000,
        body_type="Sedan",
        source_id="p1",
    )
    _seed_car(
        db_session,
        brand="Nissan",
        model="Sunny",
        condition="used",
        price=500_000,
        body_type="Sedan",
        source_id="p2",
    )
    _seed_car(
        db_session,
        brand="Changan",
        model="V7",
        condition="used",
        price=500_000,
        body_type="Sedan",
        source_id="p3",
    )
    _seed_car(
        db_session,
        brand="Chery",
        model="Arrizo 5",
        condition="used",
        price=500_000,
        body_type="Sedan",
        source_id="p4",
    )
    _seed_car(
        db_session,
        brand="MG",
        model="MG 5",
        condition="used",
        price=500_000,
        body_type="Sedan",
        source_id="p5",
    )

    session_id = uuid.uuid4()
    context_service = ConversationContextService(db_session)

    # 1. User says "عايز عربية استعمال خفيف سيدان" -> condition=used, body_type=Sedan
    res1 = orchestrator.handle_message(session_id, "عايز عربية استعمال خفيف سيدان")
    assert res1.errors == ()
    assert res1.route == "catalog"
    ctx1 = context_service.load(session_id)
    assert ctx1.preferences.get("condition") == "used"
    assert ctx1.preferences.get("body_type") == "Sedan"
    page1_ids = [c["car"]["id"] for c in res1.visible_recommendations]
    assert len(page1_ids) == 3

    # 2. User says "في حاجات تاني غير ال انت عارضهم دول" -> return page 2 (cars 4, 5)
    res2 = orchestrator.handle_message(session_id, "في حاجات تاني غير ال انت عارضهم دول")
    assert res2.errors == ()
    assert res2.route == "catalog"
    page2_ids = [c["car"]["id"] for c in res2.visible_recommendations]
    assert len(page2_ids) >= 1
    assert set(page1_ids).isdisjoint(set(page2_ids))
