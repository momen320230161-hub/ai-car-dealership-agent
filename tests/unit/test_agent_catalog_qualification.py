"""Regression coverage for catalog sales qualification and Arabic aliases."""

from __future__ import annotations

import uuid
from collections import deque
from decimal import Decimal

from sqlalchemy import func, select

from app.agent.graph import SalesOrchestrator
from app.agent.llm import DeterministicAgentLLM
from app.agent.schemas import RequestUnderstanding, sanitize_understanding
from app.models.car import Car
from app.models.conversation import ConversationSession
from app.models.recommendation import RecommendationSnapshot
from app.rag.embeddings import DeterministicEmbeddingProvider


class QueueLLM(DeterministicAgentLLM):
    def __init__(self, *understandings: RequestUnderstanding):
        self.understandings = deque(understandings)

    def understand(self, message, *, recent_messages, preferences):
        del message, recent_messages, preferences
        return self.understandings.popleft()


class EmptyRAG:
    def retrieve(self, query, **kwargs):
        del query, kwargs
        return []


def _orchestrator(db_session, *understandings: RequestUnderstanding) -> SalesOrchestrator:
    return SalesOrchestrator(
        db_session,
        QueueLLM(*understandings),
        DeterministicEmbeddingProvider(),
        rag_service=EmptyRAG(),
    )


def _car(source_id: str, *, brand: str, model: str, price: int) -> Car:
    return Car(
        brand=brand,
        model=model,
        year=2026,
        condition="new",
        price_egp=Decimal(price),
        body_type="SUV",
        transmission="Automatic",
        fuel_type="Gasoline",
        mileage_km=0,
        source="qualification-test",
        source_id=source_id,
    )


def test_arabic_bmw_alias_is_preserved_as_canonical_brand():
    raw = RequestUnderstanding(
        intent="catalog_search",
        preference_updates={"brand": "BMW", "max_price": 3_000_000},
    )

    sanitized = sanitize_understanding(raw, "عايز عربية بي ام ومعايا 3 مليون")

    assert sanitized.preference_updates.brand == "BMW"
    assert sanitized.preference_updates.max_price == 3_000_000


def test_arabic_body_and_fuel_aliases_are_preserved_as_canonical_values():
    raw = RequestUnderstanding(
        intent="catalog_search",
        preference_updates={"body_type": "Sedan", "fuel_type": "Gasoline"},
    )

    sanitized = sanitize_understanding(raw, "عايز عربية سيدان بنزين")

    assert sanitized.preference_updates.body_type == "Sedan"
    assert sanitized.preference_updates.fuel_type == "Gasoline"


def test_budget_only_search_asks_preferences_before_creating_snapshot(db_session):
    orchestrator = _orchestrator(
        db_session,
        RequestUnderstanding(
            intent="catalog_search",
            preference_updates={"max_price": 2_000_000},
        ),
    )

    result = orchestrator.handle_message(None, "عايز اشتري عربية ومعايا 2 مليون")

    assert result.intent == "catalog_search"
    assert result.route == "catalog"
    assert result.recommendation_snapshot_id is None
    assert "جديدة ولا مستعملة" in result.response
    assert "SUV" not in result.response
    assert "Sedan" not in result.response
    assert db_session.scalar(select(func.count()).select_from(RecommendationSnapshot)) == 0
    session = db_session.get(ConversationSession, uuid.UUID(result.session_id))
    assert session.preferences == {"max_price": 2_000_000}


def test_brand_budget_search_asks_model_or_recommendation_then_uses_persisted_brand(db_session):
    db_session.add_all(
        [
            _car("bmw-x1", brand="BMW", model="X1", price=2_900_000),
            _car("bmw-x3", brand="BMW", model="X3", price=2_800_000),
            _car("audi-q3", brand="Audi", model="Q3", price=2_950_000),
        ]
    )
    db_session.commit()

    orchestrator = _orchestrator(
        db_session,
        RequestUnderstanding(
            intent="catalog_search",
            preference_updates={"brand": "BMW", "max_price": 3_000_000},
        ),
        RequestUnderstanding(
            intent="catalog_search",
            preference_updates={"condition": "new"},
        ),
    )

    first = orchestrator.handle_message(None, "عايز عربية بي ام ومعايا 3 مليون")

    assert first.recommendation_snapshot_id is None
    assert "BMW" in first.response
    assert "موديل معين" in first.response
    assert "أرشحلك" in first.response
    first_session = db_session.get(ConversationSession, uuid.UUID(first.session_id))
    assert first_session.preferences == {"brand": "BMW", "max_price": 3_000_000}

    second = orchestrator.handle_message(first.session_id, "رشحلي جديدة")

    assert second.recommendation_snapshot_id is not None
    assert second.visible_recommendations
    assert all(item["car"]["brand"] == "BMW" for item in second.visible_recommendations)
    session = db_session.get(ConversationSession, uuid.UUID(second.session_id))
    assert session.preferences == {
        "brand": "BMW",
        "condition": "new",
        "max_price": 3_000_000,
    }
