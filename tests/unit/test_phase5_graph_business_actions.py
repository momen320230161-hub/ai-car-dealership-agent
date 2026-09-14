"""Phase 5 LangGraph business actions end-to-end unit test suite."""

from __future__ import annotations

from datetime import date, time
from decimal import Decimal

from sqlalchemy import func, select

from app.agent.graph import SalesOrchestrator
from app.agent.llm import DeterministicAgentLLM
from app.models.car import Car
from app.models.conversation import ConversationSession
from app.models.lead import SalesLead
from app.models.test_drive import TestDriveRequest
from app.rag.embeddings import DeterministicEmbeddingProvider
from app.services.business_action_workflow_service import (
    BusinessActionWorkflowError,
    BusinessActionWorkflowService,
)
from app.services.recommendation_service import RecommendationService
from app.services.test_drive_service import TestDriveService


class FailingBusinessService(BusinessActionWorkflowService):
    def prepare_action(self, *args, **kwargs):
        raise BusinessActionWorkflowError("simulated business workflow failure")


def _car(source_id: str, brand: str = "BMW", model: str = "X6", price: str = "2700000") -> Car:
    return Car(
        brand=brand,
        model=model,
        year=2020,
        condition="used",
        price_egp=Decimal(price),
        body_type="SUV",
        transmission="Automatic",
        fuel_type="Gasoline",
        mileage_km=50000,
        source="phase5-unit",
        source_id=source_id,
        active=True,
    )


def _orchestrator(db_session, **kwargs) -> SalesOrchestrator:
    return SalesOrchestrator(
        db_session,
        DeterministicAgentLLM(),
        DeterministicEmbeddingProvider(),
        **kwargs,
    )


def test_test_drive_multi_turn_with_visible_ordinal_resolution(db_session) -> None:
    car1 = _car("car-1", brand="Mercedes-Benz", model="C180", price="2500000")
    car2 = _car("car-2", brand="BMW", model="X6", price="2800000")
    session = ConversationSession()
    db_session.add_all([car1, car2, session])
    db_session.commit()

    RecommendationService(db_session).create_visible_snapshot(session.id, [car1.id, car2.id])

    orchestrator = _orchestrator(db_session)

    # Turn 1: Start booking
    r1 = orchestrator.handle_message(session.id, "عايز احجز تست درايف")
    assert r1.route == "business_gate"
    assert "العربية" in r1.response
    assert "اسمك" in r1.response
    assert db_session.scalar(select(func.count(TestDriveRequest.id))) == 0

    # Turn 2: Select visible car 2
    r2 = orchestrator.handle_message(session.id, "على التانية")
    assert r2.route == "business_gate"
    assert "العربية" not in r2.response
    assert "اسمك" in r2.response
    assert db_session.scalar(select(func.count(TestDriveRequest.id))) == 0

    # Turn 3: Name
    r3 = orchestrator.handle_message(session.id, "اسمي محمد جمال")
    assert r3.route == "business_gate"
    assert "رقم الموبايل" in r3.response
    assert "اسمك" not in r3.response
    assert db_session.scalar(select(func.count(TestDriveRequest.id))) == 0

    # Turn 4: Phone
    r4 = orchestrator.handle_message(session.id, "01012345678")
    assert r4.route == "business_gate"
    assert "المناسب" in r4.response
    assert "رقم الموبايل" not in r4.response
    assert db_session.scalar(select(func.count(TestDriveRequest.id))) == 0

    # Turn 5: Date and Time -> Complete and Create DB row
    r5 = orchestrator.handle_message(session.id, "بكرة الساعة 4")
    assert r5.route == "business_gate"
    assert "تم تسجيل طلب تجربة القيادة برقم" in r5.response
    assert db_session.scalar(select(func.count(TestDriveRequest.id))) == 1

    created = db_session.scalar(
        select(TestDriveRequest).where(TestDriveRequest.session_id == session.id)
    )
    assert created is not None
    assert created.car_id == car2.id
    assert created.customer_name == "محمد جمال"
    assert created.phone == "01012345678"
    assert created.status == "NEW"

    # Verify pending action cleared
    db_session.expire_all()
    reloaded_session = db_session.get(ConversationSession, session.id)
    assert reloaded_session.pending_action is None


def test_test_drive_with_selected_car_and_single_turn_details(db_session) -> None:
    car = _car("single-car", brand="BMW", model="X6")
    session = ConversationSession()
    db_session.add_all([car, session])
    db_session.commit()
    session.selected_car_id = car.id
    db_session.commit()

    orchestrator = _orchestrator(db_session)

    # Initial test drive intent with selected car
    r1 = orchestrator.handle_message(session.id, "عايز احجز تست درايف")
    assert r1.route == "business_gate"
    assert "العربية" not in r1.response  # Car was already selected
    assert "اسمك" in r1.response

    # Provide all remaining fields in one follow-up
    r2 = orchestrator.handle_message(
        session.id,
        "اسمي طارق حسن ورقمي 01234567890 يوم السبت الساعة 3",
    )
    assert r2.route == "business_gate"
    assert "تم تسجيل طلب تجربة القيادة برقم" in r2.response

    requests = list(
        db_session.scalars(
            select(TestDriveRequest).where(TestDriveRequest.session_id == session.id)
        )
    )
    assert len(requests) == 1
    assert requests[0].car_id == car.id
    assert requests[0].customer_name == "طارق حسن"
    assert requests[0].phone == "01234567890"


def test_test_drive_cancellation_single_active_request(db_session) -> None:
    car = _car("cancel-car")
    session = ConversationSession()
    db_session.add_all([car, session])
    db_session.commit()

    drives = TestDriveService(db_session)
    req = drives.create_request(
        session_id=session.id,
        car_id=car.id,
        customer_name="خالد علي",
        phone="01111111111",
        preferred_date=date(2026, 9, 20),
        preferred_time=time(16, 0),
        idempotency_key="req-cancel-1",
    )

    orchestrator = _orchestrator(db_session)
    result = orchestrator.handle_message(session.id, "عايز الغي التست درايف")

    assert result.route == "business_gate"
    assert f"تم إلغاء طلب تجربة القيادة رقم {req.id}" in result.response

    db_session.refresh(req)
    assert req.status == "CANCELLED"
    assert req.cancelled_at is not None


def test_test_drive_cancellation_no_active_request(db_session) -> None:
    session = ConversationSession()
    db_session.add(session)
    db_session.commit()

    orchestrator = _orchestrator(db_session)
    result = orchestrator.handle_message(session.id, "عايز الغي التست درايف")

    assert result.route == "business_gate"
    assert "مفيش طلب تجربة قيادة نشط" in result.response


def test_test_drive_cancellation_multiple_active_requests_asks_for_id(db_session) -> None:
    car = _car("multi-cancel-car")
    session = ConversationSession()
    db_session.add_all([car, session])
    db_session.commit()

    drives = TestDriveService(db_session)
    r1 = drives.create_request(
        session_id=session.id,
        car_id=car.id,
        customer_name="عمرو خالد",
        phone="01111111111",
        preferred_date=date(2026, 9, 20),
        preferred_time=time(14, 0),
        idempotency_key="multi-cancel-1",
    )
    r2 = drives.create_request(
        session_id=session.id,
        car_id=car.id,
        customer_name="عمرو خالد",
        phone="01111111111",
        preferred_date=date(2026, 9, 21),
        preferred_time=time(16, 0),
        idempotency_key="multi-cancel-2",
    )

    orchestrator = _orchestrator(db_session)

    # First turn: ambiguous -> asks for ID
    res1 = orchestrator.handle_message(session.id, "عايز الغي التست درايف")
    assert res1.route == "business_gate"
    assert "أكتر من طلب" in res1.response
    assert str(r1.id) in res1.response
    assert str(r2.id) in res1.response

    # Second turn: provide specific ID
    res2 = orchestrator.handle_message(session.id, f"الطلب رقم {r2.id}")
    assert res2.route == "business_gate"
    assert f"تم إلغاء طلب تجربة القيادة رقم {r2.id}" in res2.response

    db_session.refresh(r1)
    db_session.refresh(r2)
    assert r1.status == "NEW"
    assert r2.status == "CANCELLED"


def test_sales_lead_creation_and_duplicate_prevention(db_session) -> None:
    car = _car("lead-car")
    session = ConversationSession()
    db_session.add_all([car, session])
    db_session.commit()
    session.selected_car_id = car.id
    db_session.commit()

    orchestrator = _orchestrator(db_session)

    # Step 1: Lead request
    r1 = orchestrator.handle_message(session.id, "عايز حد من المبيعات يكلمني")
    assert r1.route == "business_gate"
    assert "اسمك ورقم الموبايل" in r1.response
    assert db_session.scalar(select(func.count(SalesLead.id))) == 0

    # Step 2: Provide info
    r2 = orchestrator.handle_message(session.id, "اسمي هاني شاكر 01223344556")
    assert r2.route == "business_gate"
    assert "تم تسجيل طلب التواصل مع فريق المبيعات برقم" in r2.response
    assert db_session.scalar(select(func.count(SalesLead.id))) == 1

    lead = db_session.scalar(select(SalesLead).where(SalesLead.session_id == session.id))
    assert lead is not None
    assert lead.customer_name == "هاني شاكر"
    assert lead.phone == "01223344556"
    assert lead.car_id == car.id


def test_business_workflow_failure_returns_controlled_response(db_session) -> None:
    session = ConversationSession()
    db_session.add(session)
    db_session.commit()

    failing_service = FailingBusinessService(db_session)
    orchestrator = _orchestrator(db_session, business_action_service=failing_service)

    result = orchestrator.handle_message(session.id, "عايز احجز تست درايف")
    assert "business_action_failed" in result.errors
    assert "مقدرتش أنفذ الطلب حاليًا" in result.response
    assert "Traceback" not in result.response
