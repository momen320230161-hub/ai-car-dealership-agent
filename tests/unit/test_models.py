"""Unit tests for SQLAlchemy domain models and DB-level constraints."""

import uuid
from datetime import date, time
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.car import Car
from app.models.conversation import ConversationSession
from app.models.knowledge import KnowledgeDocument
from app.models.lead import SalesLead
from app.models.message import ChatMessage
from app.models.recommendation import RecommendationSnapshot, RecommendationSnapshotItem
from app.models.test_drive import TestDriveRequest


def _car(**overrides) -> Car:
    data = {
        "brand": "Toyota",
        "model": "Corolla",
        "year": 2024,
        "condition": "new",
        "price_egp": Decimal("1250000.00"),
        "source": "unit-test",
        "source_id": str(uuid.uuid4()),
    }
    data.update(overrides)
    return Car(**data)


def test_car_persistence_and_constraints(db_session):
    car = _car(
        body_type="Sedan",
        transmission="Automatic",
        fuel_type="Gasoline",
        mileage_km=0,
        engine_capacity_cc=1600,
        horsepower=Decimal("120.00"),
    )
    db_session.add(car)
    db_session.commit()

    assert car.id is not None
    assert car.created_at is not None
    assert car.updated_at is not None
    assert car.engine_capacity_cc == 1600

    invalid_cases = (
        {"price_egp": Decimal("-1.00")},
        {"condition": "salvage"},
        {"mileage_km": -1},
        {"brand": "   "},
    )
    for overrides in invalid_cases:
        with pytest.raises(IntegrityError):
            db_session.add(_car(**overrides))
            db_session.commit()
        db_session.rollback()


def test_conversation_session_and_messages(db_session):
    session = ConversationSession(
        preferences={"budget_max": 1000000, "transmission": "automatic"},
        status="active",
    )
    db_session.add(session)
    db_session.commit()

    assert isinstance(session.id, uuid.UUID)
    assert session.preferences["budget_max"] == 1000000

    db_session.add_all(
        [
            ChatMessage(session_id=session.id, role="user", content="Hello"),
            ChatMessage(session_id=session.id, role="assistant", content="Hi"),
        ]
    )
    db_session.commit()
    assert [message.role for message in session.messages] == ["user", "assistant"]

    with pytest.raises(IntegrityError):
        db_session.add(ChatMessage(session_id=session.id, role="admin", content="Invalid"))
        db_session.commit()
    db_session.rollback()


def test_recommendation_snapshot_visible_positions_and_uniqueness(db_session):
    cars = [
        _car(brand="Kia", model="Sportage", source_id="rec-1"),
        _car(brand="Hyundai", model="Tucson", source_id="rec-2"),
        _car(brand="Nissan", model="Qashqai", source_id="rec-3"),
    ]
    session = ConversationSession()
    db_session.add_all([*cars, session])
    db_session.commit()

    snapshot = RecommendationSnapshot(
        session_id=session.id,
        sequence_no=1,
        criteria={"body_type": "SUV"},
    )
    db_session.add(snapshot)
    db_session.commit()

    db_session.add_all(
        [
            RecommendationSnapshotItem(snapshot_id=snapshot.id, position=1, car_id=cars[0].id),
            RecommendationSnapshotItem(snapshot_id=snapshot.id, position=2, car_id=cars[1].id),
        ]
    )
    db_session.commit()

    assert [(item.position, item.car_id) for item in snapshot.items] == [
        (1, cars[0].id),
        (2, cars[1].id),
    ]

    session.active_recommendation_snapshot_id = snapshot.id
    session.selected_car_id = cars[0].id
    db_session.commit()
    assert session.active_recommendation_snapshot.id == snapshot.id
    assert session.selected_car.id == cars[0].id

    with pytest.raises(IntegrityError):
        db_session.add(
            RecommendationSnapshotItem(
                snapshot_id=snapshot.id,
                position=1,
                car_id=cars[2].id,
            )
        )
        db_session.commit()
    db_session.rollback()

    with pytest.raises(IntegrityError):
        db_session.add(
            RecommendationSnapshotItem(
                snapshot_id=snapshot.id,
                position=3,
                car_id=cars[0].id,
            )
        )
        db_session.commit()
    db_session.rollback()


def test_test_drive_request_constraints_and_idempotency(db_session):
    car = _car(source_id="td-car")
    session = ConversationSession()
    db_session.add_all([car, session])
    db_session.commit()

    request = TestDriveRequest(
        session_id=session.id,
        car_id=car.id,
        customer_name="Ahmed Hassan",
        phone="+201012345678",
        preferred_date=date(2026, 9, 20),
        preferred_time=time(14, 30),
        status="NEW",
        idempotency_key="td-unit-001",
    )
    db_session.add(request)
    db_session.commit()
    assert request.id is not None

    with pytest.raises(IntegrityError):
        db_session.add(
            TestDriveRequest(
                session_id=session.id,
                car_id=car.id,
                customer_name="Ahmed Hassan",
                phone="+201012345678",
                preferred_date=date(2026, 9, 20),
                preferred_time=time(14, 30),
                status="NEW",
                idempotency_key="td-unit-001",
            )
        )
        db_session.commit()
    db_session.rollback()

    with pytest.raises(IntegrityError):
        db_session.add(
            TestDriveRequest(
                session_id=session.id,
                car_id=car.id,
                customer_name="Ahmed Hassan",
                phone="+201012345678",
                preferred_date=date(2026, 9, 20),
                preferred_time=time(14, 30),
                status="INVALID",
                idempotency_key="td-unit-invalid",
            )
        )
        db_session.commit()
    db_session.rollback()


def test_sales_lead_nullable_car_and_idempotency(db_session):
    session = ConversationSession()
    db_session.add(session)
    db_session.commit()

    lead = SalesLead(
        session_id=session.id,
        car_id=None,
        customer_name="Sara Mohamed",
        phone="+201098765432",
        email="sara@example.com",
        status="NEW",
        idempotency_key="lead-unit-001",
    )
    db_session.add(lead)
    db_session.commit()

    assert lead.id is not None
    assert lead.car_id is None

    with pytest.raises(IntegrityError):
        db_session.add(
            SalesLead(
                session_id=session.id,
                customer_name="Sara Mohamed",
                phone="+201098765432",
                status="NEW",
                idempotency_key="lead-unit-001",
            )
        )
        db_session.commit()
    db_session.rollback()


def test_knowledge_document_persistence_and_category_active_query(db_session):
    active = KnowledgeDocument(
        title="Warranty Policy",
        category="warranty",
        content="Approved warranty policy text.",
        active=True,
    )
    inactive = KnowledgeDocument(
        title="Old Warranty Policy",
        category="warranty",
        content="Retired policy text.",
        active=False,
    )
    db_session.add_all([active, inactive])
    db_session.commit()

    matches = (
        db_session.query(KnowledgeDocument)
        .filter_by(category="warranty", active=True)
        .all()
    )
    assert [document.id for document in matches] == [active.id]


def test_business_records_restrict_session_deletion(db_session):
    car = _car(source_id="retention-car")
    session = ConversationSession()
    db_session.add_all([car, session])
    db_session.commit()

    db_session.add_all(
        [
            TestDriveRequest(
                session_id=session.id,
                car_id=car.id,
                customer_name="Customer",
                phone="+201000000000",
                preferred_date=date(2026, 9, 20),
                preferred_time=time(12, 0),
                idempotency_key="retention-td",
            ),
            SalesLead(
                session_id=session.id,
                car_id=car.id,
                customer_name="Customer",
                phone="+201000000000",
                idempotency_key="retention-lead",
            ),
        ]
    )
    db_session.commit()

    with pytest.raises(IntegrityError):
        db_session.delete(session)
        db_session.commit()
    db_session.rollback()

    assert db_session.get(ConversationSession, session.id) is not None
