"""Unit coverage for real Phase 5 business-action services."""

from __future__ import annotations

import uuid
from datetime import date, time
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.models.car import Car
from app.models.conversation import ConversationSession
from app.models.lead import SalesLead
from app.models.test_drive import TestDriveRequest
from app.services.sales_lead_service import SalesLeadService, SalesLeadServiceError
from app.services.test_drive_service import (
    AmbiguousTestDriveError,
    TestDriveNotFoundError as DriveNotFoundError,
    TestDriveService as DriveService,
    TestDriveServiceError as DriveServiceError,
)


def _session_and_car(db_session, *, source_id: str = "phase5-car"):
    conversation = ConversationSession(id=uuid.uuid4())
    car = Car(
        brand="BMW",
        model="X6",
        year=2019,
        condition="used",
        price_egp=Decimal("2700000"),
        mileage_km=140000,
        source="phase5-test",
        source_id=source_id,
        active=True,
    )
    db_session.add_all([conversation, car])
    db_session.commit()
    return conversation, car


def test_test_drive_create_persists_real_row_once(db_session) -> None:
    conversation, car = _session_and_car(db_session)
    service = DriveService(db_session)

    first = service.create_request(
        session_id=conversation.id,
        car_id=car.id,
        customer_name="  عمر   أحمد ",
        phone="01012345678",
        preferred_date=date(2026, 9, 19),
        preferred_time=time(17, 0),
        idempotency_key="attempt-test-drive-1",
    )
    second = service.create_request(
        session_id=conversation.id,
        car_id=car.id,
        customer_name="عمر أحمد",
        phone="01012345678",
        preferred_date=date(2026, 9, 19),
        preferred_time=time(17, 0),
        idempotency_key="attempt-test-drive-1",
    )

    assert first.id == second.id
    assert first.id is not None
    assert first.status == "NEW"
    assert first.customer_name == "عمر أحمد"
    assert db_session.scalar(select(func.count(TestDriveRequest.id))) == 1


def test_test_drive_rejects_missing_required_data_without_insert(db_session) -> None:
    conversation, car = _session_and_car(db_session)
    service = DriveService(db_session)

    with pytest.raises(ValueError, match="customer_name"):
        service.create_request(
            session_id=conversation.id,
            car_id=car.id,
            customer_name=" ",
            phone="01012345678",
            preferred_date=date(2026, 9, 19),
            preferred_time=time(17, 0),
            idempotency_key="attempt-test-drive-missing",
        )

    assert db_session.scalar(select(func.count(TestDriveRequest.id))) == 0


def test_test_drive_idempotency_key_cannot_be_reused_for_different_payload(db_session) -> None:
    conversation, car = _session_and_car(db_session)
    service = DriveService(db_session)
    service.create_request(
        session_id=conversation.id,
        car_id=car.id,
        customer_name="عمر أحمد",
        phone="01012345678",
        preferred_date=date(2026, 9, 19),
        preferred_time=time(17, 0),
        idempotency_key="attempt-test-drive-conflict",
    )

    with pytest.raises(DriveServiceError, match="already used"):
        service.create_request(
            session_id=conversation.id,
            car_id=car.id,
            customer_name="عمر أحمد",
            phone="01099999999",
            preferred_date=date(2026, 9, 19),
            preferred_time=time(17, 0),
            idempotency_key="attempt-test-drive-conflict",
        )

    assert db_session.scalar(select(func.count(TestDriveRequest.id))) == 1


def test_test_drive_cancellation_is_session_owned_and_idempotent(db_session) -> None:
    owner, car = _session_and_car(db_session)
    other = ConversationSession(id=uuid.uuid4())
    db_session.add(other)
    db_session.commit()
    service = DriveService(db_session)
    request = service.create_request(
        session_id=owner.id,
        car_id=car.id,
        customer_name="عمر أحمد",
        phone="01012345678",
        preferred_date=date(2026, 9, 19),
        preferred_time=time(17, 0),
        idempotency_key="attempt-test-drive-cancel",
    )

    with pytest.raises(DriveNotFoundError):
        service.cancel_request(session_id=other.id, request_id=request.id)

    cancelled = service.cancel_request(session_id=owner.id, request_id=request.id)
    repeated = service.cancel_request(session_id=owner.id, request_id=request.id)

    assert cancelled.id == request.id
    assert repeated.id == request.id
    assert repeated.status == "CANCELLED"
    assert repeated.cancelled_at is not None


def test_test_drive_cancellation_requires_id_when_multiple_are_active(db_session) -> None:
    conversation, car = _session_and_car(db_session)
    service = DriveService(db_session)
    for index, hour in enumerate((17, 18), start=1):
        service.create_request(
            session_id=conversation.id,
            car_id=car.id,
            customer_name="عمر أحمد",
            phone="01012345678",
            preferred_date=date(2026, 9, 19),
            preferred_time=time(hour, 0),
            idempotency_key=f"attempt-test-drive-{index}",
        )

    with pytest.raises(AmbiguousTestDriveError) as exc_info:
        service.cancel_request(session_id=conversation.id)

    assert len(exc_info.value.request_ids) == 2
    assert db_session.scalar(
        select(func.count(TestDriveRequest.id)).where(TestDriveRequest.status == "NEW")
    ) == 2


def test_sales_lead_create_persists_once_with_selected_car(db_session) -> None:
    conversation, car = _session_and_car(db_session)
    service = SalesLeadService(db_session)

    first = service.create_lead(
        session_id=conversation.id,
        car_id=car.id,
        customer_name="عمر أحمد",
        phone="01012345678",
        email="omar@example.com",
        idempotency_key="attempt-lead-1",
    )
    second = service.create_lead(
        session_id=conversation.id,
        car_id=car.id,
        customer_name="عمر أحمد",
        phone="01012345678",
        email="omar@example.com",
        idempotency_key="attempt-lead-1",
    )

    assert first.id == second.id
    assert first.id is not None
    assert first.car_id == car.id
    assert first.status == "NEW"
    assert db_session.scalar(select(func.count(SalesLead.id))) == 1


def test_sales_lead_idempotency_key_rejects_different_payload(db_session) -> None:
    conversation, car = _session_and_car(db_session)
    service = SalesLeadService(db_session)
    service.create_lead(
        session_id=conversation.id,
        car_id=car.id,
        customer_name="عمر أحمد",
        phone="01012345678",
        idempotency_key="attempt-lead-conflict",
    )

    with pytest.raises(SalesLeadServiceError, match="already used"):
        service.create_lead(
            session_id=conversation.id,
            car_id=car.id,
            customer_name="عمر أحمد",
            phone="01099999999",
            idempotency_key="attempt-lead-conflict",
        )

    assert db_session.scalar(select(func.count(SalesLead.id))) == 1
