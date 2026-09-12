"""PostgreSQL integration evidence for the compiled Phase 4 StateGraph."""

from __future__ import annotations

from decimal import Decimal

from flask_migrate import upgrade
from sqlalchemy import func, select, text

from app.agent.graph import SalesOrchestrator
from app.agent.llm import DeterministicAgentLLM
from app.extensions import db
from app.models.car import Car
from app.models.lead import SalesLead
from app.models.message import ChatMessage
from app.models.recommendation import RecommendationSnapshot
from app.models.test_drive import TestDriveRequest
from app.rag.embeddings import DeterministicEmbeddingProvider
from app.services.knowledge_service import KnowledgeService


def _truncate_phase4() -> None:
    db.session.execute(
        text(
            """
            TRUNCATE TABLE
                recommendation_snapshot_items,
                sales_leads,
                test_drive_requests,
                chat_messages,
                recommendation_snapshots,
                conversation_sessions,
                knowledge_chunks,
                knowledge_documents,
                cars
            RESTART IDENTITY CASCADE
            """
        )
    )
    db.session.commit()


def _orchestrator() -> SalesOrchestrator:
    provider = DeterministicEmbeddingProvider()
    return SalesOrchestrator(db.session, DeterministicAgentLLM(), provider)


def _car(source_id: str, brand: str, price: str) -> Car:
    return Car(
        brand=brand,
        model="Phase4",
        year=2025,
        condition="used",
        price_egp=Decimal(price),
        body_type="SUV",
        transmission="Automatic",
        fuel_type="Gasoline",
        mileage_km=10000,
        source="phase4-postgres",
        source_id=source_id,
    )


def test_stategraph_persists_snapshot_and_resolves_followup_visible_ordinal(pg_app):
    with pg_app.app_context():
        upgrade()
        _truncate_phase4()
        db.session.add_all(
            [
                _car("one", "Kia", "800000"),
                _car("two", "Hyundai", "900000"),
                _car("three", "Toyota", "1000000"),
            ]
        )
        db.session.commit()
        orchestrator = _orchestrator()

        listed = orchestrator.handle_message(None, "عايز SUV مستعملة")
        second_id = listed.visible_recommendations[1]["car_id"]
        snapshots_before = db.session.scalar(
            select(func.count()).select_from(RecommendationSnapshot)
        )
        details = orchestrator.handle_message(listed.session_id, "هات تفاصيل التانية")
        snapshots_after = db.session.scalar(
            select(func.count()).select_from(RecommendationSnapshot)
        )

        assert listed.route == details.route == "catalog"
        assert [item["position"] for item in listed.visible_recommendations] == [1, 2, 3]
        assert second_id == 2
        assert "Hyundai" in details.response
        assert snapshots_after == snapshots_before == 1
        assert db.session.scalar(select(func.count()).select_from(ChatMessage)) == 4
        _truncate_phase4()


def test_stategraph_uses_postgres_pgvector_and_rejects_unsupported_insurance(pg_app):
    with pg_app.app_context():
        upgrade()
        _truncate_phase4()
        provider = DeterministicEmbeddingProvider()
        knowledge = KnowledgeService(db.session, provider)
        knowledge.create_document(
            title="معلومات الضمان",
            category="warranty",
            content="لا تتوفر مدة ضمان موحدة لكل السيارات.",
        )
        knowledge.create_document(
            title="معلومات التمويل",
            category="financing",
            content="لا توجد نسبة تمويل معتمدة حاليًا.",
        )
        orchestrator = SalesOrchestrator(db.session, DeterministicAgentLLM(), provider)

        known = orchestrator.handle_message(None, "الضمان مدته كام؟")
        unknown = orchestrator.handle_message(
            known.session_id, "هل عندكم تأمين سيارات ضد الحوادث؟"
        )

        assert known.route == unknown.route == "rag"
        assert known.response == "لا تتوفر مدة ضمان موحدة لكل السيارات."
        assert "مش متوفرة" in unknown.response
        assert "ضمان" not in unknown.response
        _truncate_phase4()


def test_stategraph_business_intents_persist_messages_but_create_no_actions(pg_app):
    with pg_app.app_context():
        upgrade()
        _truncate_phase4()
        orchestrator = _orchestrator()

        booking = orchestrator.handle_message(None, "عايز احجز تست درايف")
        lead = orchestrator.handle_message(
            booking.session_id, "عايز حد من المبيعات يكلمني"
        )

        assert booking.intent == "test_drive"
        assert lead.intent == "sales_lead"
        assert db.session.scalar(select(func.count()).select_from(TestDriveRequest)) == 0
        assert db.session.scalar(select(func.count()).select_from(SalesLead)) == 0
        assert db.session.scalar(select(func.count()).select_from(ChatMessage)) == 4
        _truncate_phase4()
