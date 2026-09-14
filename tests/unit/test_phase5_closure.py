"""Closure regressions for Phase 5 business-action hardening."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select

from app.agent.graph import SalesOrchestrator
from app.agent.llm import DeterministicAgentLLM
from app.models.car import Car
from app.models.conversation import ConversationSession
from app.models.test_drive import TestDriveRequest
from app.rag.embeddings import DeterministicEmbeddingProvider
from app.services.business_action_workflow_service import BusinessActionWorkflowService
from app.services.test_drive_service import TestDriveService
from app.services.test_drive_service import TestDriveServiceError as DriveServiceError


def _session_with_selected_car(db_session, *, source_id: str) -> tuple[ConversationSession, Car]:
    car = Car(
        brand="BMW",
        model="X6",
        year=2020,
        condition="used",
        price_egp=Decimal("2700000"),
        body_type="SUV",
        transmission="Automatic",
        fuel_type="Gasoline",
        mileage_km=50000,
        source="phase5-closure",
        source_id=source_id,
        active=True,
    )
    conversation = ConversationSession()
    db_session.add_all([car, conversation])
    db_session.commit()
    conversation.selected_car_id = car.id
    db_session.commit()
    return conversation, car


def _orchestrator(db_session, *, business_action_service=None) -> SalesOrchestrator:
    return SalesOrchestrator(
        db_session,
        DeterministicAgentLLM(),
        DeterministicEmbeddingProvider(),
        business_action_service=business_action_service,
    )


def test_pending_acknowledgement_does_not_become_customer_name(db_session) -> None:
    conversation, _ = _session_with_selected_car(db_session, source_id="ack-name")
    workflow = BusinessActionWorkflowService(
        db_session,
        today_provider=lambda: date(2026, 9, 14),
    )

    first = workflow.prepare_action(
        conversation.id,
        "test_drive",
        "عايز احجز تست درايف",
    )
    assert "customer_name" in first["missing_fields"]

    acknowledged = workflow.prepare_action(
        conversation.id,
        "general",
        "تمام يا باشا شكرا",
    )

    assert acknowledged["fields"].get("customer_name") is None
    assert "customer_name" in acknowledged["missing_fields"]
    assert db_session.scalar(select(func.count(TestDriveRequest.id))) == 0


class _FailingTestDriveService(TestDriveService):
    def create_request(self, **kwargs):
        del kwargs
        raise DriveServiceError("simulated test-drive write failure")


def test_service_failure_is_wrapped_and_rendered_as_controlled_graph_error(db_session) -> None:
    conversation, _ = _session_with_selected_car(db_session, source_id="write-failure")
    workflow = BusinessActionWorkflowService(
        db_session,
        today_provider=lambda: date(2026, 9, 14),
        test_drives=_FailingTestDriveService(db_session),
    )
    orchestrator = _orchestrator(db_session, business_action_service=workflow)

    started = orchestrator.handle_message(conversation.id, "عايز احجز تست درايف")
    assert started.route == "business_gate"

    failed = orchestrator.handle_message(
        conversation.id,
        "اسمي محمد جمال ورقمي 01012345678 يوم 2026-09-20 الساعة 4",
    )

    assert failed.route == "business_gate"
    assert "business_action_failed" in failed.errors
    assert failed.response == "مقدرتش أنفذ الطلب حاليًا. حاول مرة تانية."
    assert "Traceback" not in failed.response
    assert db_session.scalar(select(func.count(TestDriveRequest.id))) == 0


def test_replayed_final_booking_message_does_not_create_duplicate(db_session) -> None:
    conversation, _ = _session_with_selected_car(db_session, source_id="graph-retry")
    orchestrator = _orchestrator(db_session)

    started = orchestrator.handle_message(conversation.id, "عايز احجز تست درايف")
    assert started.route == "business_gate"

    final_message = "اسمي محمد جمال ورقمي 01012345678 يوم 2026-09-20 الساعة 4"
    created = orchestrator.handle_message(conversation.id, final_message)
    assert created.route == "business_gate"
    assert "تم تسجيل طلب تجربة القيادة برقم" in created.response
    assert db_session.scalar(select(func.count(TestDriveRequest.id))) == 1

    replayed = orchestrator.handle_message(conversation.id, final_message)
    assert replayed.route == "general"
    assert db_session.scalar(select(func.count(TestDriveRequest.id))) == 1
