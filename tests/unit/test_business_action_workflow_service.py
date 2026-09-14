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


def test_test_drive_pending_collects_only_missing_fields_before_insert(db_session) -> None:
    conversation, car = _conversation_with_selected_car(
        db_session, source_id="pending-test-drive"
    )
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
    conversation, car = _conversation_with_selected_car(
        db_session, source_id="single-cancel"
    )
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
