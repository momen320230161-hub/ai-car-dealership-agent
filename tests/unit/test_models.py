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


def test_car_persistence_and_constraints(db_session):
    """Test valid Car model persists and DB check constraints are enforced."""
    car = Car(
        brand="Toyota",
        model="Corolla",
        year=2024,
        condition="new",
        price_egp=Decimal("1250000.00"),
        body_type="Sedan",
        transmission="Automatic",
        fuel_type="Gasoline",
        mileage_km=0,
        active=True,
    )
    db_session.add(car)
    db_session.commit()

    assert car.id is not None
    assert car.brand == "Toyota"
    assert car.created_at is not None
    assert car.updated_at is not None

    # Test negative price rejection
    with pytest.raises(IntegrityError):
        invalid_car = Car(
            brand="Honda",
            model="Civic",
            year=2023,
            condition="used",
            price_egp=Decimal("-100.00"),
        )
        db_session.add(invalid_car)
        db_session.commit()
    db_session.rollback()

    # Test invalid condition rejection
    with pytest.raises(IntegrityError):
        invalid_cond_car = Car(
            brand="Honda",
            model="Civic",
            year=2023,
            condition="salvage",
            price_egp=Decimal("800000.00"),
        )
        db_session.add(invalid_cond_car)
        db_session.commit()
    db_session.rollback()


def test_conversation_session_and_messages(db_session):
    """Test ConversationSession and ChatMessage relationships and constraints."""
    session = ConversationSession(
        preferences={"budget_max": 1000000, "transmission": "automatic"},
        status="active",
    )
    db_session.add(session)
    db_session.commit()

    assert session.id is not None
    assert session.preferences["budget_max"] == 1000000

    msg1 = ChatMessage(session_id=session.id, role="user", content="Hello, looking for an SUV")
    msg2 = ChatMessage(session_id=session.id, role="assistant", content="I can help you with that!")
    db_session.add_all([msg1, msg2])
    db_session.commit()

    assert len(session.messages) == 2
    assert session.messages[0].role == "user"

    # Test invalid message role constraint
    with pytest.raises(IntegrityError):
        invalid_msg = ChatMessage(session_id=session.id, role="admin", content="Invalid")
        db_session.add(invalid_msg)
        db_session.commit()
    db_session.rollback()


def test_recommendation_snapshot_and_items(db_session):
    """Test RecommendationSnapshot and items ordering and unique constraints."""
    car1 = Car(
        brand="Kia", model="Sportage", year=2023, condition="used", price_egp=Decimal("1500000.00")
    )
    car2 = Car(
        brand="Hyundai", model="Tucson", year=2024, condition="new", price_egp=Decimal("1700000.00")
    )
    session = ConversationSession()
    db_session.add_all([car1, car2, session])
    db_session.commit()

    snapshot = RecommendationSnapshot(
        session_id=session.id,
        sequence_no=1,
        criteria={"body_type": "SUV"},
    )
    db_session.add(snapshot)
    db_session.commit()

    item1 = RecommendationSnapshotItem(snapshot_id=snapshot.id, position=1, car_id=car1.id)
    item2 = RecommendationSnapshotItem(snapshot_id=snapshot.id, position=2, car_id=car2.id)
    db_session.add_all([item1, item2])
    db_session.commit()

    assert len(snapshot.items) == 2
    assert snapshot.items[0].position == 1
    assert snapshot.items[0].car_id == car1.id
    assert snapshot.items[1].position == 2
    assert snapshot.items[1].car_id == car2.id

    # Active recommendation snapshot reference on session
    session.active_recommendation_snapshot_id = snapshot.id
    session.selected_car_id = car1.id
    db_session.commit()

    assert session.active_recommendation_snapshot.id == snapshot.id
    assert session.selected_car.model == "Sportage"

    # Duplicate position constraint rejection
    with pytest.raises(IntegrityError):
        duplicate_pos_item = RecommendationSnapshotItem(
            snapshot_id=snapshot.id, position=1, car_id=car2.id
        )
        db_session.add(duplicate_pos_item)
        db_session.commit()
    db_session.rollback()


def test_test_drive_request_and_idempotency(db_session):
    """Test TestDriveRequest model constraints and idempotency key uniqueness."""
    car = Car(
        brand="Nissan", model="Sunny", year=2022, condition="used", price_egp=Decimal("600000.00")
    )
    session = ConversationSession()
    db_session.add_all([car, session])
    db_session.commit()

    td1 = TestDriveRequest(
        session_id=session.id,
        car_id=car.id,
        customer_name="Ahmed Hassan",
        phone="+201012345678",
        preferred_date=date(2026, 9, 20),
        preferred_time=time(14, 30),
        status="NEW",
        idempotency_key="idemp-td-001",
    )
    db_session.add(td1)
    db_session.commit()

    assert td1.id is not None
    assert td1.status == "NEW"

    # Duplicate idempotency key rejection
    with pytest.raises(IntegrityError):
        td2 = TestDriveRequest(
            session_id=session.id,
            car_id=car.id,
            customer_name="Ahmed Hassan",
            phone="+201012345678",
            preferred_date=date(2026, 9, 20),
            preferred_time=time(14, 30),
            status="NEW",
            idempotency_key="idemp-td-001",
        )
        db_session.add(td2)
        db_session.commit()
    db_session.rollback()

    # Invalid status rejection
    with pytest.raises(IntegrityError):
        td_invalid = TestDriveRequest(
            session_id=session.id,
            car_id=car.id,
            customer_name="Ahmed Hassan",
            phone="+201012345678",
            preferred_date=date(2026, 9, 20),
            preferred_time=time(14, 30),
            status="UNKNOWN_STATUS",
        )
        db_session.add(td_invalid)
        db_session.commit()
    db_session.rollback()


def test_sales_lead_model(db_session):
    """Test SalesLead model with nullable car and idempotency protection."""
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
        notes="Customer requested financing details",
        idempotency_key="idemp-lead-001",
    )
    db_session.add(lead)
    db_session.commit()

    assert lead.id is not None
    assert lead.car_id is None
    assert lead.email == "sara@example.com"


def test_knowledge_document_model(db_session):
    """Test KnowledgeDocument persistence and active status."""
    doc = KnowledgeDocument(
        title="Dealership Warranty Policy",
        category="warranty",
        content="All approved vehicles include a comprehensive 1-year dealership warranty.",
        active=True,
    )
    db_session.add(doc)
    db_session.commit()

    assert isinstance(doc.id, uuid.UUID)
    assert doc.category == "warranty"
    assert doc.active is True
