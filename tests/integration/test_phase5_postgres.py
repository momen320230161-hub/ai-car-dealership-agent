"""PostgreSQL integration coverage for Phase 5 real business actions in LangGraph."""

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
from app.models.test_drive import TestDriveRequest
from app.rag.embeddings import DeterministicEmbeddingProvider


def _truncate_all() -> None:
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
        model="X6",
        year=2024,
        condition="used",
        price_egp=Decimal(price),
        body_type="SUV",
        transmission="Automatic",
        fuel_type="Gasoline",
        mileage_km=25000,
        source="phase5-postgres",
        source_id=source_id,
        active=True,
    )


def test_postgres_test_drive_full_multi_turn_workflow_and_cancellation(pg_app):
    with pg_app.app_context():
        upgrade()
        _truncate_all()
        car = _car("pg-car-1", "BMW", "3000000")
        db.session.add(car)
        db.session.commit()

        orchestrator = _orchestrator()

        # Step 1: Catalog search to get visible snapshot
        s1 = orchestrator.handle_message(None, "عايز SUV مستعملة")
        assert s1.route == "catalog"
        session_id = s1.session_id

        # Step 2: Ask for test drive -> prompts for car & details
        s2 = orchestrator.handle_message(session_id, "عايز احجز تست درايف")
        assert s2.route == "business_gate"
        assert db.session.scalar(select(func.count()).select_from(TestDriveRequest)) == 0

        # Step 3: Select visible #1
        s3 = orchestrator.handle_message(session_id, "على الأولى")
        assert s3.route == "business_gate"
        assert db.session.scalar(select(func.count()).select_from(TestDriveRequest)) == 0

        # Step 4: Name
        s4 = orchestrator.handle_message(session_id, "اسمي محمد جمال")
        assert s4.route == "business_gate"
        assert db.session.scalar(select(func.count()).select_from(TestDriveRequest)) == 0

        # Step 5: Phone
        s5 = orchestrator.handle_message(session_id, "01012345678")
        assert s5.route == "business_gate"
        assert db.session.scalar(select(func.count()).select_from(TestDriveRequest)) == 0

        # Step 6: Date and time -> creates row
        s6 = orchestrator.handle_message(session_id, "بكرة الساعة 4")
        assert s6.route == "business_gate"
        assert "تم تسجيل طلب تجربة القيادة برقم" in s6.response
        assert db.session.scalar(select(func.count()).select_from(TestDriveRequest)) == 1

        request = db.session.scalar(
            select(TestDriveRequest).where(TestDriveRequest.session_id == session_id)
        )
        assert request is not None
        assert request.customer_name == "محمد جمال"
        assert request.phone == "01012345678"
        assert request.status == "NEW"

        # Step 7: Cancel the active request
        s7 = orchestrator.handle_message(session_id, "عايز الغي التست درايف")
        assert s7.route == "business_gate"
        assert f"تم إلغاء طلب تجربة القيادة رقم {request.id}" in s7.response

        db.session.refresh(request)
        assert request.status == "CANCELLED"
        assert request.cancelled_at is not None

        # Verify chat messages count: 7 turns * 2 = 14 messages
        assert db.session.scalar(select(func.count()).select_from(ChatMessage)) == 14

        _truncate_all()


def test_postgres_sales_lead_workflow(pg_app):
    with pg_app.app_context():
        upgrade()
        _truncate_all()
        orchestrator = _orchestrator()

        # Step 1: Request lead -> asks for name and phone
        s1 = orchestrator.handle_message(None, "عايز حد من المبيعات يكلمني")
        assert s1.route == "business_gate"
        assert "اسمك ورقم الموبايل" in s1.response
        assert db.session.scalar(select(func.count()).select_from(SalesLead)) == 0
        session_id = s1.session_id

        # Step 2: Supply fields -> creates real lead
        s2 = orchestrator.handle_message(session_id, "اسمي احمد علي 01098765432")
        assert s2.route == "business_gate"
        assert "تم تسجيل طلب التواصل مع فريق المبيعات برقم" in s2.response
        assert db.session.scalar(select(func.count()).select_from(SalesLead)) == 1

        lead = db.session.scalar(select(SalesLead).where(SalesLead.session_id == session_id))
        assert lead is not None
        assert lead.customer_name == "احمد علي"
        assert lead.phone == "01098765432"
        assert lead.status == "NEW"

        _truncate_all()
