"""Regression tests for Phase 6 live E2E conversation bugs."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select

from app.agent.conversational_orchestrator import ConversationalSalesOrchestrator
from app.agent.llm import DeterministicAgentLLM
from app.models.car import Car
from app.models.conversation import ConversationSession
from app.models.test_drive import TestDriveRequest
from app.rag.embeddings import DeterministicEmbeddingProvider
from app.services.recommendation_service import RecommendationService


def _car(
    source_id: str, brand: str = "Chery", model: str = "Tiggo 4", price: str = "930000"
) -> Car:
    return Car(
        brand=brand,
        model=model,
        year=2026,
        condition="used",
        price_egp=Decimal(price),
        body_type="SUV",
        transmission="Automatic",
        fuel_type="Gasoline",
        mileage_km=7500,
        source="phase6-unit",
        source_id=source_id,
        active=True,
    )


def _orchestrator(db_session, **kwargs) -> ConversationalSalesOrchestrator:
    return ConversationalSalesOrchestrator(
        db_session,
        DeterministicAgentLLM(),
        DeterministicEmbeddingProvider(),
        **kwargs,
    )


def test_pending_test_drive_separate_messages_decreases_missing_fields_and_inserts_once(
    db_session,
) -> None:
    """Bug 1 regression: Start test drive with explicit car ID, supply each field separately."""
    car = _car("car-1872", brand="Chery", model="Tiggo 4", price="930000")
    session = ConversationSession()
    db_session.add_all([car, session])
    db_session.commit()

    orchestrator = _orchestrator(db_session)

    # Turn 1: Start booking with explicit car ID
    r1 = orchestrator.handle_message(session.id, f"عايز احجز تجربة قيادة للعربية ID {car.id}")
    assert r1.route == "business_gate"
    assert "اسمك" in r1.response
    assert "رقم الموبايل" in r1.response
    assert "التاريخ" in r1.response or "اليوم" in r1.response
    assert "الوقت" in r1.response
    assert db_session.scalar(select(func.count(TestDriveRequest.id))) == 0

    # Turn 2: Customer name only ("مؤمن محمد")
    r2 = orchestrator.handle_message(session.id, "مؤمن محمد")
    assert r2.route == "business_gate"
    assert "اسمك" not in r2.response
    assert "رقم الموبايل" in r2.response
    assert "التاريخ" in r2.response or "اليوم" in r2.response
    assert "الوقت" in r2.response
    assert db_session.scalar(select(func.count(TestDriveRequest.id))) == 0

    # Verify pending state preserved in database
    db_session.expire_all()
    s_loaded = db_session.get(ConversationSession, session.id)
    assert s_loaded.pending_action is not None
    assert s_loaded.pending_action["fields"]["car_id"] == car.id
    assert s_loaded.pending_action["fields"]["customer_name"] == "مؤمن محمد"

    # Turn 3: Phone only ("01012345678")
    r3 = orchestrator.handle_message(session.id, "01012345678")
    assert r3.route == "business_gate"
    assert "رقم الموبايل" not in r3.response
    assert "اسمك" not in r3.response
    assert "التاريخ" in r3.response or "اليوم" in r3.response
    assert "الوقت" in r3.response
    assert db_session.scalar(select(func.count(TestDriveRequest.id))) == 0

    # Turn 4: Date only ("بكرة")
    r4 = orchestrator.handle_message(session.id, "بكرة")
    assert r4.route == "business_gate"
    assert "الوقت" in r4.response
    assert "التاريخ" not in r4.response
    assert "اليوم" not in r4.response
    assert "رقم الموبايل" not in r4.response
    assert "اسمك" not in r4.response
    assert db_session.scalar(select(func.count(TestDriveRequest.id))) == 0

    # Turn 5: A bare 12-hour clock is ambiguous in the production workflow.
    r5 = orchestrator.handle_message(session.id, "الساعة 4")
    assert r5.route == "business_gate"
    assert "صباح" in r5.response
    assert "عصر" in r5.response or "مساء" in r5.response
    assert db_session.scalar(select(func.count(TestDriveRequest.id))) == 0

    # Turn 6: Daypart resolves the same pending attempt, then the real insert may happen.
    r6 = orchestrator.handle_message(session.id, "العصر")
    assert r6.route == "business_gate"
    assert "تم تسجيل طلب تجربة القيادة برقم" in r6.response
    assert db_session.scalar(select(func.count(TestDriveRequest.id))) == 1

    created = db_session.scalar(
        select(TestDriveRequest).where(TestDriveRequest.session_id == session.id)
    )
    assert created is not None
    assert created.car_id == car.id
    assert created.customer_name == "مؤمن محمد"
    assert created.phone == "01012345678"
    assert created.status == "NEW"

    # Verify pending_action is cleared
    db_session.expire_all()
    s_reloaded = db_session.get(ConversationSession, session.id)
    assert s_reloaded.pending_action is None

    # Turn 7: Duplicate/social confirmation does not insert another row.
    r7 = orchestrator.handle_message(session.id, "تمام شكرا")
    assert r7.route == "general"
    assert db_session.scalar(select(func.count(TestDriveRequest.id))) == 1


def test_recommendation_context_details_asks_clarification_when_ambiguous(
    db_session,
) -> None:
    """Bug 2 regression: Multiple visible cars and user asks for details."""
    car1 = _car("car-1", brand="Chery", model="Tiggo 4", price="930000")
    car2 = _car("car-2", brand="Soueast", model="S07", price="1350000")
    car3 = _car("car-3", brand="Haval", model="H6", price="1490000")
    session = ConversationSession()
    db_session.add_all([car1, car2, car3, session])
    db_session.commit()

    RecommendationService(db_session).create_visible_snapshot(
        session.id, [car1.id, car2.id, car3.id]
    )

    orchestrator = _orchestrator(db_session)

    # User asks "عايز اعرف تفاصيلها" without selecting or specifying a number
    result = orchestrator.handle_message(session.id, "عايز اعرف تفاصيلها")
    assert result.route == "catalog"
    assert "تقصد رقم كام من القائمة؟" in result.response
    assert "1 ولا 2 ولا 3" in result.response
    assert "اختار العربية الأول" not in result.response

    # User then specifies "الأولى"
    r_first = orchestrator.handle_message(session.id, "الأولى")
    assert r_first.route == "catalog"
    assert "Chery" in r_first.response
    assert "Tiggo 4" in r_first.response


def test_recommendation_context_single_visible_car_shows_details_directly(
    db_session,
) -> None:
    """Bug 2 edge case: Single visible car in snapshot shows details directly."""
    car = _car("single-car", brand="Chery", model="Tiggo 4", price="930000")
    session = ConversationSession()
    db_session.add_all([car, session])
    db_session.commit()

    RecommendationService(db_session).create_visible_snapshot(session.id, [car.id])

    orchestrator = _orchestrator(db_session)

    result = orchestrator.handle_message(session.id, "تفاصيلها")
    assert result.route == "catalog"
    assert "Chery" in result.response
    assert "Tiggo 4" in result.response
    assert "تقصد رقم كام" not in result.response


def test_visible_references_resolve_against_active_snapshot_only(
    db_session,
) -> None:
    """Bug 2 regression: Explicit visible reference 'تفاصيل العربية الأولى' and 'قارن أول اتنين'."""
    car1 = _car("car-1", brand="Chery", model="Tiggo 4", price="930000")
    car2 = _car("car-2", brand="Soueast", model="S07", price="1350000")
    car3 = _car("car-3", brand="Haval", model="H6", price="1490000")
    session = ConversationSession()
    db_session.add_all([car1, car2, car3, session])
    db_session.commit()

    RecommendationService(db_session).create_visible_snapshot(
        session.id, [car1.id, car2.id, car3.id]
    )

    orchestrator = _orchestrator(db_session)

    # 1. "تفاصيل العربية الأولى"
    r1 = orchestrator.handle_message(session.id, "تفاصيل العربية الأولى")
    assert r1.route == "catalog"
    assert "Chery" in r1.response
    assert "Tiggo 4" in r1.response

    # 2. "قارن أول اتنين"
    r2 = orchestrator.handle_message(session.id, "قارن أول اتنين")
    assert r2.route == "catalog"
    assert "المقارنة حسب البيانات المتاحة" in r2.response
    assert "Chery" in r2.response
    assert "Soueast" in r2.response


def test_selection_with_altanya_eajabatni_persists_selected_car_for_subsequent_booking(
    db_session,
) -> None:
    """Bug 2 & Bug 1: 'التانية عجبتني' sets selected_car_id, then 'احجزلي العربية دي' uses it."""
    car1 = _car("car-101", brand="Chery", model="Tiggo 4", price="930000")
    car2 = _car("car-102", brand="Soueast", model="S07", price="1350000")
    car3 = _car("car-103", brand="Haval", model="H6", price="1490000")
    session = ConversationSession()
    db_session.add_all([car1, car2, car3, session])
    db_session.commit()

    RecommendationService(db_session).create_visible_snapshot(
        session.id, [car1.id, car2.id, car3.id]
    )

    orchestrator = _orchestrator(db_session)

    # Turn 1: "التانية عجبتني"
    r1 = orchestrator.handle_message(session.id, "التانية عجبتني")
    assert r1.selected_car_id == car2.id

    db_session.expire_all()
    s_loaded = db_session.get(ConversationSession, session.id)
    assert s_loaded.selected_car_id == car2.id

    # Turn 2: "احجزلي العربية دي"
    r2 = orchestrator.handle_message(session.id, "احجزلي العربية دي")
    assert r2.route == "business_gate"
    assert "اسمك" in r2.response

    db_session.expire_all()
    s_loaded2 = db_session.get(ConversationSession, session.id)
    assert s_loaded2.pending_action is not None
    assert s_loaded2.pending_action["fields"]["car_id"] == car2.id


def test_pending_action_retains_car_when_followup_message_contains_numeric_date_and_time(
    db_session,
) -> None:
    """Bug 1: Messages containing numbers like 'السبت الساعة 5' must not lose car_id."""
    car = _car("car-201", brand="Soueast", model="S07", price="1350000")
    session = ConversationSession()
    db_session.add_all([car, session])
    db_session.commit()

    orchestrator = _orchestrator(db_session)

    # Turn 1: Start booking
    r1 = orchestrator.handle_message(session.id, f"احجزلي تست درايف للعربية ID {car.id}")
    assert r1.route == "business_gate"

    # Turn 2: Name
    r2 = orchestrator.handle_message(session.id, "أحمد علي")
    assert r2.route == "business_gate"

    # Turn 3: Phone
    r3 = orchestrator.handle_message(session.id, "01099887766")
    assert r3.route == "business_gate"

    # Turn 4: Numeric date/time text must retain car_id, but 5 is still ambiguous.
    r4 = orchestrator.handle_message(session.id, "السبت الساعة 5")
    assert r4.route == "business_gate"
    assert db_session.scalar(select(func.count(TestDriveRequest.id))) == 0

    # Turn 5: Resolve the daypart without losing the car or earlier contact fields.
    r5 = orchestrator.handle_message(session.id, "مساء")
    assert r5.route == "business_gate"
    assert "تم تسجيل طلب تجربة القيادة برقم" in r5.response

    created = db_session.scalar(
        select(TestDriveRequest).where(TestDriveRequest.session_id == session.id)
    )
    assert created is not None
    assert created.car_id == car.id
    assert created.customer_name == "أحمد علي"
    assert created.phone == "01099887766"
