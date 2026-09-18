"""Regression coverage for conversational memory, routing, and grounded composition."""

from __future__ import annotations

import uuid
from datetime import date, time
from decimal import Decimal

from sqlalchemy import func, select

from app.agent.conversational_orchestrator import ConversationalSalesOrchestrator
from app.models.car import Car
from app.models.conversation import ConversationSession
from app.models.lead import SalesLead
from app.models.test_drive import TestDriveRequest
from app.models.user import UserProfile
from app.services.catalog_preference_state_service import CatalogPreferenceStateService
from app.services.conversational_business_action_workflow_service import (
    ConversationalBusinessActionWorkflowService,
)
from app.services.customer_memory_service import CustomerMemoryService


def _car(db_session, source_id: str) -> Car:
    car = Car(
        brand="BMW",
        model="X6",
        year=2019,
        condition="used",
        price_egp=Decimal("2700000"),
        mileage_km=140000,
        source="conversational-hardening-test",
        source_id=source_id,
        active=True,
    )
    db_session.add(car)
    db_session.commit()
    return car


def _workflow(db_session) -> ConversationalBusinessActionWorkflowService:
    return ConversationalBusinessActionWorkflowService(
        db_session,
        today_provider=lambda: date(2026, 9, 14),
    )


def test_completed_test_drive_contact_is_reused_for_sales_lead(db_session) -> None:
    car = _car(db_session, "reuse-contact")
    conversation = ConversationSession(id=uuid.uuid4(), selected_car_id=car.id)
    db_session.add(conversation)
    db_session.commit()
    workflow = _workflow(db_session)

    drive_plan = workflow.prepare_action(
        conversation.id,
        "test_drive",
        "اسمي عمر أحمد ورقمي 01012345678 وعايز السبت الساعة 5 مساء",
    )
    assert drive_plan["status"] == "ready"
    drive_result = workflow.execute_action(conversation.id, drive_plan)
    assert isinstance(drive_result["request_id"], int)

    lead_plan = workflow.prepare_action(
        conversation.id,
        "sales_lead",
        "عايز حد من المبيعات يكلمني",
    )
    assert lead_plan["status"] == "ready"
    assert lead_plan["fields"]["customer_name"] == "عمر أحمد"
    assert lead_plan["fields"]["phone"] == "01012345678"
    assert set(lead_plan["memory_fields_used"]) == {"customer_name", "phone"}

    lead_result = workflow.execute_action(conversation.id, lead_plan)
    assert isinstance(lead_result["lead_id"], int)
    assert set(lead_result["memory_fields_used"]) == {"customer_name", "phone"}
    lead = db_session.get(SalesLead, lead_result["lead_id"])
    assert lead is not None
    assert lead.phone == "01012345678"

    db_session.expire_all()
    refreshed = db_session.get(ConversationSession, conversation.id)
    assert refreshed is not None
    assert "customer_name" not in refreshed.preferences
    assert "phone" not in refreshed.preferences


def test_explicit_new_phone_overrides_remembered_phone(db_session) -> None:
    car = _car(db_session, "explicit-phone-wins")
    conversation = ConversationSession(id=uuid.uuid4(), selected_car_id=car.id)
    db_session.add(conversation)
    db_session.commit()
    workflow = _workflow(db_session)

    drive_plan = workflow.prepare_action(
        conversation.id,
        "test_drive",
        "اسمي عمر أحمد ورقمي 01012345678 والسبت الساعة 5 مساء",
    )
    workflow.execute_action(conversation.id, drive_plan)

    lead_plan = workflow.prepare_action(
        conversation.id,
        "sales_lead",
        "كلمني على 01112345678",
    )
    assert lead_plan["status"] == "ready"
    assert lead_plan["fields"]["phone"] == "01112345678"
    assert lead_plan["fields"]["customer_name"] == "عمر أحمد"
    assert lead_plan["memory_fields_used"] == ["customer_name"]


def test_authenticated_user_contact_memory_crosses_chat_sessions(db_session) -> None:
    user = UserProfile(
        id=uuid.uuid4(),
        email="memory-user@example.com",
        display_name="Profile Name",
    )
    car = _car(db_session, "cross-session-memory")
    old_session = ConversationSession(id=uuid.uuid4(), user_id=user.id)
    new_session = ConversationSession(id=uuid.uuid4(), user_id=user.id)
    db_session.add_all([user, old_session, new_session])
    db_session.commit()
    request_row = TestDriveRequest(
        session_id=old_session.id,
        car_id=car.id,
        customer_name="محمد جمال",
        phone="01099998888",
        preferred_date=date(2026, 9, 19),
        preferred_time=time(17, 0),
        status="NEW",
        idempotency_key="cross-session-memory-request",
    )
    db_session.add(request_row)
    db_session.commit()

    memory = CustomerMemoryService(db_session).load(new_session.id)

    assert memory.customer_name == "محمد جمال"
    assert memory.phone == "01099998888"
    assert memory.email == "memory-user@example.com"
    assert "authenticated_user_history" in memory.scope
    assert memory.safe_context() == {"available_for_actions": True}


def test_legacy_customer_fields_are_removed_from_catalog_preferences(db_session) -> None:
    conversation = ConversationSession(
        id=uuid.uuid4(),
        preferences={"brand": "BMW", "customer_name": "Old Name", "phone": "01000000000"},
    )
    db_session.add(conversation)
    db_session.commit()

    result = CatalogPreferenceStateService(db_session).update_preferences(
        conversation.id,
        {"condition": "used"},
    )

    assert result.preferences == {"brand": "BMW", "condition": "used"}
    db_session.refresh(conversation)
    assert conversation.preferences == {"brand": "BMW", "condition": "used"}



def test_brand_pivot_clears_only_stale_model_and_preserves_other_constraints(db_session) -> None:
    conversation = ConversationSession(
        id=uuid.uuid4(),
        preferences={
            "brand": "Renault",
            "model": "Logan",
            "max_price": 1_000_000,
            "body_type": "Sedan",
            "condition": "used",
            "transmission": "Automatic",
        },
    )
    db_session.add(conversation)
    db_session.commit()

    result = CatalogPreferenceStateService(db_session).update_preferences(
        conversation.id,
        {"brand": "BMW"},
    )

    assert result.preferences == {
        "brand": "BMW",
        "max_price": 1_000_000,
        "body_type": "Sedan",
        "condition": "used",
        "transmission": "Automatic",
    }


def test_pending_action_allows_catalog_and_rag_side_questions() -> None:
    orchestrator = object.__new__(ConversationalSalesOrchestrator)
    pending = {
        "type": "test_drive",
        "fields": {"car_id": 5, "customer_name": "محمد"},
    }

    catalog_state = {
        "intent": "car_details",
        "normalized_message": "طب قولي تفاصيل العربية دي",
        "pending_action": pending,
        "errors": [],
        "trace": [],
    }
    assert orchestrator._route_request(catalog_state)["selected_route"] == "catalog_node"

    rag_state = {
        "intent": "knowledge_question",
        "normalized_message": "طب الضمان نظامه إيه؟",
        "pending_action": pending,
        "errors": [],
        "trace": [],
    }
    assert orchestrator._route_request(rag_state)["selected_route"] == "rag_node"

    phone_state = {
        "intent": "general",
        "normalized_message": "01012345678",
        "pending_action": pending,
        "errors": [],
        "trace": [],
    }
    assert orchestrator._route_request(phone_state)["selected_route"] == "business_gate"



def test_pending_single_name_uses_semantic_field_hint_for_routing() -> None:
    orchestrator = object.__new__(ConversationalSalesOrchestrator)
    state = {
        "intent": "general",
        "pending_field_answer": "customer_name",
        "normalized_message": "مؤمن",
        "pending_action": {
            "type": "test_drive",
            "fields": {"car_id": 5},
        },
        "errors": [],
        "trace": [],
    }

    assert orchestrator._route_request(state)["selected_route"] == "business_gate"


def test_pending_side_question_is_not_consumed_as_single_name() -> None:
    orchestrator = object.__new__(ConversationalSalesOrchestrator)
    state = {
        "intent": "car_details",
        "pending_field_answer": "none",
        "normalized_message": "بكام؟",
        "pending_action": {
            "type": "test_drive",
            "fields": {"car_id": 5},
        },
        "errors": [],
        "trace": [],
    }

    assert orchestrator._route_request(state)["selected_route"] == "catalog_node"


def test_grounded_composer_rejects_unsupported_numbers_and_falls_back() -> None:
    class UnsafeLLM:
        model_name = "unsafe-test"

        def compose_general(self, message, *, verified_context):
            del message, verified_context
            return "تمام، السعر 999999 جنيه."

    orchestrator = object.__new__(ConversationalSalesOrchestrator)
    orchestrator.llm = UnsafeLLM()
    state = {
        "route": "catalog",
        "intent": "catalog_search",
        "normalized_message": "رشحلي عربية",
        "catalog_result": {"type": "no_results"},
        "recent_messages": [],
        "preferences": {},
        "selected_car_id": None,
        "pending_action": None,
        "errors": [],
        "trace": [],
        "session_id": None,
    }

    update = orchestrator._compose_response(state)

    assert update["response"] == "ملقتش عربيات مطابقة حسب البيانات المتاحة عندي في الكتالوج المسجل."
    assert "composition_rejected" in update["errors"]


def test_cross_action_reuse_creates_only_one_lead(db_session) -> None:
    car = _car(db_session, "one-lead")
    conversation = ConversationSession(id=uuid.uuid4(), selected_car_id=car.id)
    db_session.add(conversation)
    db_session.commit()
    workflow = _workflow(db_session)

    drive = workflow.prepare_action(
        conversation.id,
        "test_drive",
        "اسمي محمد جمال ورقمي 01012345678 والسبت الساعة 5 مساء",
    )
    workflow.execute_action(conversation.id, drive)
    lead = workflow.prepare_action(conversation.id, "sales_lead", "المبيعات تكلمني")
    first = workflow.execute_action(conversation.id, lead)
    repeated = workflow.execute_action(conversation.id, lead)

    assert first["lead_id"] == repeated["lead_id"]
    assert db_session.scalar(select(func.count(SalesLead.id))) == 1
