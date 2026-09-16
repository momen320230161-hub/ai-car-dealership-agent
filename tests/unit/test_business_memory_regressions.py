"""Business-memory and scheduling regressions found during live chat testing."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from app.models.car import Car
from app.models.conversation import ConversationSession
from app.models.lead import SalesLead
from app.services.conversational_business_action_workflow_service import (
    ConversationalBusinessActionWorkflowService,
)


def _car(db_session, source_id: str) -> Car:
    car = Car(
        brand="Chevrolet",
        model="Optra",
        year=2025,
        condition="used",
        price_egp=Decimal("690000"),
        body_type="Sedan",
        transmission="Automatic",
        fuel_type="Gasoline",
        mileage_km=20_000,
        source="business-memory-regression",
        source_id=source_id,
        active=True,
    )
    db_session.add(car)
    db_session.commit()
    return car


def _workflow(db_session) -> ConversationalBusinessActionWorkflowService:
    return ConversationalBusinessActionWorkflowService(
        db_session,
        today_provider=lambda: date(2026, 9, 16),
    )


def test_sales_lead_contact_is_reused_for_later_test_drive(db_session) -> None:
    car = _car(db_session, "lead-to-drive")
    conversation = ConversationSession(id=uuid.uuid4(), selected_car_id=car.id)
    db_session.add(conversation)
    db_session.commit()

    lead = SalesLead(
        session_id=conversation.id,
        car_id=car.id,
        customer_name="مؤمن محمد",
        phone="01229847585",
        status="NEW",
        idempotency_key="lead-to-drive-memory",
    )
    db_session.add(lead)
    db_session.commit()

    plan = _workflow(db_session).prepare_action(
        conversation.id,
        "test_drive",
        "بكره الساعة 5 مساء",
    )

    assert plan["status"] == "ready"
    assert plan["fields"]["customer_name"] == "مؤمن محمد"
    assert plan["fields"]["phone"] == "01229847585"
    assert plan["fields"]["preferred_date"] == "2026-09-17"
    assert plan["fields"]["preferred_time"] == "17:00"
    assert set(plan["memory_fields_used"]) == {"customer_name", "phone"}


def test_ambiguous_five_oclock_stays_pending_instead_of_becoming_0500(db_session) -> None:
    car = _car(db_session, "ambiguous-time")
    conversation = ConversationSession(id=uuid.uuid4(), selected_car_id=car.id)
    db_session.add(conversation)
    db_session.commit()

    plan = _workflow(db_session).prepare_action(
        conversation.id,
        "test_drive",
        "اسمي مؤمن محمد ورقمي 01229847585 بكره على الساعة 5",
    )

    assert plan["status"] == "missing_fields"
    assert plan["missing_fields"] == ["preferred_time"]
    assert plan["ambiguous_time"] is True
    assert plan["fields"]["preferred_date"] == "2026-09-17"
    assert "preferred_time" not in plan["fields"]
