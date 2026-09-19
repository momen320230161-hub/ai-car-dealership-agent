"""Pending-action collection, readiness, idempotency, and cancellation coverage."""

from __future__ import annotations

import uuid
from datetime import date, time
from decimal import Decimal

from sqlalchemy import func, select

from app.models.car import Car
from app.models.conversation import ConversationSession
from app.models.lead import SalesLead
from app.models.test_drive import TestDriveRequest
from app.services.business_action_parsing import parse_business_fields
from app.services.business_action_workflow_service import BusinessActionWorkflowService
from app.services.recommendation_service import RecommendationService
from app.services.test_drive_service import TestDriveService as DriveService


def _conversation_with_selected_car(db_session, *, source_id: str):
    car = Car(
        brand="BMW",
        model="X6",
        year=2019,
        condition="used",
        price_egp=Decimal("2700000"),
        mileage_km=140000,
        source="phase5-workflow-test",
        source_id=source_id,
        active=True,
    )
    conversation = ConversationSession(id=uuid.uuid4())
    db_session.add_all([car, conversation])
    db_session.commit()
    conversation.selected_car_id = car.id
    db_session.commit()
    return conversation, car


def _workflow(db_session) -> BusinessActionWorkflowService:
    return BusinessActionWorkflowService(
        db_session,
        today_provider=lambda: date(2026, 9, 14),
    )


def test_action_parser_extracts_explicit_fields_without_inventing_phone() -> None:
    parsed = parse_business_fields(
        "عمر أحمد 01012345678 السبت الساعة 5",
        allow_bare_name=True,
        today=date(2026, 9, 14),
    )

    assert parsed.customer_name == "عمر أحمد"
    assert parsed.phone == "01012345678"
    assert parsed.preferred_date == date(2026, 9, 19)
    assert parsed.preferred_time == time(5, 0)

    date_only = parse_business_fields(
        "2026-09-19",
        allow_bare_name=False,
        today=date(2026, 9, 14),
    )
    assert date_only.phone is None
    assert date_only.preferred_date == date(2026, 9, 19)



def test_single_token_name_requires_semantic_field_hint() -> None:
    hinted = parse_business_fields(
        "مؤمن",
        allow_bare_name=True,
        allow_single_name=True,
        today=date(2026, 9, 14),
    )
    unhinted = parse_business_fields(
        "مؤمن",
        allow_bare_name=True,
        allow_single_name=False,
        today=date(2026, 9, 14),
    )
    question = parse_business_fields(
        "بكام؟",
        allow_bare_name=True,
        allow_single_name=True,
        today=date(2026, 9, 14),
    )

    assert hinted.customer_name == "مؤمن"
    assert unhinted.customer_name is None
    assert question.customer_name is None


def test_pending_test_drive_accepts_single_name_only_with_field_hint(db_session) -> None:
    conversation, _ = _conversation_with_selected_car(
        db_session,
        source_id="single-name-hint",
    )
    workflow = _workflow(db_session)

    started = workflow.prepare_action(
        conversation.id,
        "test_drive",
        "عايز احجز تست درايف",
    )
    assert "customer_name" in started["missing_fields"]

    without_hint = workflow.prepare_action(
        conversation.id,
        "general",
        "مؤمن",
    )
    assert without_hint["fields"].get("customer_name") is None

    with_hint = workflow.prepare_action(
        conversation.id,
        "general",
        "مؤمن",
        field_hint="customer_name",
    )
    assert with_hint["fields"]["customer_name"] == "مؤمن"
    assert "customer_name" not in with_hint["missing_fields"]


def test_explicit_current_draft_cancellation_clears_pending_without_searching_requests(
    db_session,
) -> None:
    conversation, _ = _conversation_with_selected_car(
        db_session,
        source_id="cancel-current-draft",
    )
    workflow = _workflow(db_session)
    started = workflow.prepare_action(
        conversation.id,
        "test_drive",
        "عايز احجز تجربة قيادة",
    )
    assert started["status"] == "missing_fields"

    cancelled = workflow.prepare_action(
        conversation.id,
        "cancel_test_drive",
        "عايز ألغي الطلب الحالي",
    )

    assert cancelled["status"] == "draft_cancelled"
    assert cancelled["intent"] == "test_drive"
    db_session.expire_all()
    assert db_session.get(ConversationSession, conversation.id).pending_action is None


def test_test_drive_pending_collects_only_missing_fields_before_insert(db_session) -> None:
    conversation, car = _conversation_with_selected_car(db_session, source_id="pending-test-drive")
    workflow = _workflow(db_session)

    first = workflow.prepare_action(
        conversation.id,
        "test_drive",
        "عايز احجز تست درايف",
    )
    assert first["status"] == "missing_fields"
    assert first["fields"]["car_id"] == car.id
    assert first["missing_fields"] == [
        "customer_name",
        "phone",
        "preferred_date",
        "preferred_time",
    ]
    assert db_session.scalar(select(func.count(TestDriveRequest.id))) == 0

    second = workflow.prepare_action(
        conversation.id,
        "general",
        "عمر أحمد 01012345678",
    )
    assert second["attempt_id"] == first["attempt_id"]
    assert second["fields"]["customer_name"] == "عمر أحمد"
    assert second["fields"]["phone"] == "01012345678"
    assert second["missing_fields"] == ["preferred_date", "preferred_time"]
    assert db_session.scalar(select(func.count(TestDriveRequest.id))) == 0

    ready = workflow.prepare_action(
        conversation.id,
        "general",
        "السبت الساعة 5",
    )
    assert ready["status"] == "ready"
    assert ready["attempt_id"] == first["attempt_id"]
    assert ready["fields"]["preferred_date"] == "2026-09-19"
    assert ready["fields"]["preferred_time"] == "05:00"
    assert db_session.scalar(select(func.count(TestDriveRequest.id))) == 0

    result = workflow.execute_action(conversation.id, ready)
    repeated = workflow.execute_action(conversation.id, ready)

    assert result["status"] == "success"
    assert result["request_id"] == repeated["request_id"]
    assert result["request_id"] is not None
    assert db_session.scalar(select(func.count(TestDriveRequest.id))) == 1
    db_session.expire_all()
    refreshed = db_session.get(ConversationSession, conversation.id)
    assert refreshed.pending_action is None


def test_customer_name_stays_in_pending_action_not_catalog_preferences(db_session) -> None:
    conversation, _ = _conversation_with_selected_car(
        db_session,
        source_id="identity-boundary-pending",
    )
    conversation.preferences = {"brand": "BMW"}
    db_session.commit()
    workflow = _workflow(db_session)

    pending = workflow.prepare_action(
        conversation.id,
        "test_drive",
        "اسمي عمر أحمد ورقمي 01012345678",
    )

    assert pending["status"] == "missing_fields"
    assert pending["fields"]["customer_name"] == "عمر أحمد"
    assert pending["fields"]["phone"] == "01012345678"

    db_session.expire_all()
    refreshed = db_session.get(ConversationSession, conversation.id)
    assert refreshed.preferences == {"brand": "BMW"}
    assert refreshed.pending_action["fields"]["customer_name"] == "عمر أحمد"

    continued = workflow.prepare_action(
        conversation.id,
        "general",
        "السبت الساعة 5",
    )
    assert continued["status"] == "ready"
    assert continued["fields"]["customer_name"] == "عمر أحمد"
    assert continued["fields"]["phone"] == "01012345678"

    db_session.expire_all()
    refreshed = db_session.get(ConversationSession, conversation.id)
    assert refreshed.preferences == {"brand": "BMW"}


def test_base_workflow_does_not_reuse_legacy_name_from_catalog_preferences(db_session) -> None:
    conversation, _ = _conversation_with_selected_car(
        db_session,
        source_id="identity-boundary-legacy",
    )
    conversation.preferences = {
        "brand": "BMW",
        "customer_name": "Legacy Name",
    }
    db_session.commit()
    workflow = _workflow(db_session)

    pending = workflow.prepare_action(
        conversation.id,
        "sales_lead",
        "رقمي 01012345678",
    )

    assert pending["status"] == "missing_fields"
    assert pending["missing_fields"] == ["customer_name"]
    assert "customer_name" not in pending["fields"]



def test_ambiguous_same_brand_visible_cars_do_not_auto_select_first(db_session) -> None:
    sunny = Car(
        brand="Nissan",
        model="Sunny",
        year=2025,
        condition="used",
        price_egp=Decimal("950000"),
        source="business-reference-test",
        source_id="nissan-sunny-ambiguous",
        active=True,
    )
    qashqai = Car(
        brand="Nissan",
        model="Qashqai",
        year=2025,
        condition="used",
        price_egp=Decimal("1800000"),
        source="business-reference-test",
        source_id="nissan-qashqai-ambiguous",
        active=True,
    )
    conversation = ConversationSession(id=uuid.uuid4())
    db_session.add_all([sunny, qashqai, conversation])
    db_session.commit()
    RecommendationService(db_session).create_visible_snapshot(
        conversation.id,
        [sunny.id, qashqai.id],
    )

    plan = _workflow(db_session).prepare_action(
        conversation.id,
        "test_drive",
        "عايز أجرب النيسان، اسمي عمر أحمد ورقمي 01012345678 السبت الساعة 5 مساء",
    )

    assert plan["status"] == "missing_fields"
    assert plan["missing_fields"] == ["car_id"]
    assert "car_id" not in plan["fields"]
    db_session.refresh(conversation)
    assert conversation.selected_car_id is None


def test_specific_model_wins_over_ambiguous_same_brand(db_session) -> None:
    sunny = Car(
        brand="Nissan",
        model="Sunny",
        year=2025,
        condition="used",
        price_egp=Decimal("950000"),
        source="business-reference-test",
        source_id="nissan-sunny-specific",
        active=True,
    )
    qashqai = Car(
        brand="Nissan",
        model="Qashqai",
        year=2025,
        condition="used",
        price_egp=Decimal("1800000"),
        source="business-reference-test",
        source_id="nissan-qashqai-specific",
        active=True,
    )
    conversation = ConversationSession(id=uuid.uuid4())
    db_session.add_all([sunny, qashqai, conversation])
    db_session.commit()
    RecommendationService(db_session).create_visible_snapshot(
        conversation.id,
        [qashqai.id, sunny.id],
    )

    plan = _workflow(db_session).prepare_action(
        conversation.id,
        "test_drive",
        "عايز أجرب Nissan Sunny، اسمي عمر أحمد ورقمي 01012345678 السبت الساعة 5 مساء",
    )

    assert plan["status"] == "ready"
    assert plan["fields"]["car_id"] == sunny.id
    db_session.refresh(conversation)
    assert conversation.selected_car_id == sunny.id


def test_unique_brand_visible_car_still_resolves(db_session) -> None:
    nissan = Car(
        brand="Nissan",
        model="Sunny",
        year=2025,
        condition="used",
        price_egp=Decimal("950000"),
        source="business-reference-test",
        source_id="nissan-unique",
        active=True,
    )
    chery = Car(
        brand="Chery",
        model="Tiggo 4",
        year=2025,
        condition="used",
        price_egp=Decimal("1000000"),
        source="business-reference-test",
        source_id="chery-unique",
        active=True,
    )
    conversation = ConversationSession(id=uuid.uuid4())
    db_session.add_all([nissan, chery, conversation])
    db_session.commit()
    RecommendationService(db_session).create_visible_snapshot(
        conversation.id,
        [nissan.id, chery.id],
    )

    plan = _workflow(db_session).prepare_action(
        conversation.id,
        "test_drive",
        "عايز أجرب النيسان، اسمي عمر أحمد ورقمي 01012345678 السبت الساعة 5 مساء",
    )

    assert plan["status"] == "ready"
    assert plan["fields"]["car_id"] == nissan.id



def test_shared_alias_resolver_handles_toyota_arabic_in_business_action(db_session) -> None:
    toyota = Car(
        brand="Toyota",
        model="Corolla",
        year=2025,
        condition="used",
        price_egp=Decimal("1250000"),
        source="business-reference-test",
        source_id="toyota-shared-alias",
        active=True,
    )
    kia = Car(
        brand="Kia",
        model="Sportage",
        year=2025,
        condition="used",
        price_egp=Decimal("1600000"),
        source="business-reference-test",
        source_id="kia-shared-alias",
        active=True,
    )
    conversation = ConversationSession(id=uuid.uuid4())
    db_session.add_all([toyota, kia, conversation])
    db_session.commit()
    RecommendationService(db_session).create_visible_snapshot(
        conversation.id,
        [kia.id, toyota.id],
    )

    plan = _workflow(db_session).prepare_action(
        conversation.id,
        "test_drive",
        "عايز أجرب التويوتا، اسمي عمر أحمد ورقمي 01012345678 السبت الساعة 5 مساء",
    )

    assert plan["status"] == "ready"
    assert plan["fields"]["car_id"] == toyota.id
    db_session.refresh(conversation)
    assert conversation.selected_car_id == toyota.id


def test_sales_lead_pending_requires_only_name_and_phone(db_session) -> None:
    conversation, car = _conversation_with_selected_car(db_session, source_id="pending-lead")
    workflow = _workflow(db_session)

    first = workflow.prepare_action(
        conversation.id,
        "sales_lead",
        "عايز حد من المبيعات يكلمني",
    )
    assert first["status"] == "missing_fields"
    assert first["missing_fields"] == ["customer_name", "phone"]
    assert first["fields"]["car_id"] == car.id
    assert db_session.scalar(select(func.count(SalesLead.id))) == 0

    ready = workflow.prepare_action(
        conversation.id,
        "general",
        "عمر أحمد 01012345678",
    )
    assert ready["status"] == "ready"
    result = workflow.execute_action(conversation.id, ready)

    assert result["status"] == "success"
    assert result["lead_id"] is not None
    assert db_session.scalar(select(func.count(SalesLead.id))) == 1


def test_cancellation_with_multiple_session_requests_waits_for_explicit_id(db_session) -> None:
    conversation, car = _conversation_with_selected_car(db_session, source_id="pending-cancel")
    drives = DriveService(db_session)
    requests = [
        drives.create_request(
            session_id=conversation.id,
            car_id=car.id,
            customer_name="عمر أحمد",
            phone="01012345678",
            preferred_date=date(2026, 9, 19),
            preferred_time=time(hour, 0),
            idempotency_key=f"cancel-workflow-{hour}",
        )
        for hour in (17, 18)
    ]
    workflow = _workflow(db_session)

    pending = workflow.prepare_action(
        conversation.id,
        "cancel_test_drive",
        "عايز ألغي حجز تجربة القيادة",
    )
    assert pending["status"] == "missing_fields"
    assert pending["missing_fields"] == ["request_id"]
    assert set(pending["candidate_request_ids"]) == {request.id for request in requests}
    assert all(request.status == "NEW" for request in requests)

    chosen = requests[0]
    ready = workflow.prepare_action(
        conversation.id,
        "general",
        f"الطلب رقم {chosen.id}",
    )
    assert ready["status"] == "ready"
    assert ready["fields"]["request_id"] == chosen.id

    result = workflow.execute_action(conversation.id, ready)
    db_session.refresh(chosen)

    assert result["request_id"] == chosen.id
    assert chosen.status == "CANCELLED"
    assert chosen.cancelled_at is not None
    other = next(request for request in requests if request.id != chosen.id)
    db_session.refresh(other)
    assert other.status == "NEW"


def test_cancellation_auto_resolves_exactly_one_active_session_request(db_session) -> None:
    conversation, car = _conversation_with_selected_car(db_session, source_id="single-cancel")
    request = DriveService(db_session).create_request(
        session_id=conversation.id,
        car_id=car.id,
        customer_name="عمر أحمد",
        phone="01012345678",
        preferred_date=date(2026, 9, 19),
        preferred_time=time(17, 0),
        idempotency_key="single-cancel-key",
    )
    workflow = _workflow(db_session)

    ready = workflow.prepare_action(
        conversation.id,
        "cancel_test_drive",
        "عايز ألغي حجز تجربة القيادة",
    )

    assert ready["status"] == "ready"
    assert ready["fields"]["request_id"] == request.id
    result = workflow.execute_action(conversation.id, ready)
    assert result["request_id"] == request.id


def test_cancellation_reports_no_active_request_without_creating_pending_state(db_session) -> None:
    conversation, _ = _conversation_with_selected_car(db_session, source_id="no-cancel")
    workflow = _workflow(db_session)

    result = workflow.prepare_action(
        conversation.id,
        "cancel_test_drive",
        "عايز ألغي حجز تجربة القيادة",
    )

    assert result["status"] == "no_active_request"
    db_session.expire_all()
    assert db_session.get(ConversationSession, conversation.id).pending_action is None
