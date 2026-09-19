"""Release-blocker regressions captured from live customer conversations."""

import uuid
from datetime import date, time
from decimal import Decimal

from sqlalchemy import func, select

from app.agent.business_rendering import render_business_action
from app.agent.conversational_orchestrator import ConversationalSalesOrchestrator
from app.agent.schemas import (
    PreferenceUpdates,
    RequestUnderstanding,
    explicit_budget_ceiling,
    sanitize_understanding,
)
from app.agent.turn_semantics import analyze_turn
from app.models.car import Car
from app.models.conversation import ConversationSession
from app.models.lead import SalesLead
from app.models.test_drive import TestDriveRequest
from app.services.business_action_parsing import explicit_time
from app.services.conversation_context_service import ConversationContextService
from app.services.conversational_business_action_workflow_service import (
    ConversationalBusinessActionWorkflowService,
)
from app.services.customer_memory_service import CustomerMemory


def test_scoped_body_waiver_does_not_erase_explicit_new_condition() -> None:
    semantics = analyze_turn(
        "عايزها جديدة مش فارق معايا سيدان أو لا",
        {"max_price": 800_000},
        {"condition": "new", "body_type": "Sedan"},
    )

    assert "body_type" in semantics.force_clear_fields
    assert "condition" not in semantics.clear_fields


def test_waiver_before_contrast_does_not_clear_later_new_requirement() -> None:
    semantics = analyze_turn(
        "مش فارق معايا سيدان ولا SUV، بس لازم جديدة",
        {"body_type": "Sedan"},
        {"condition": "new"},
    )

    assert "body_type" in semantics.force_clear_fields
    assert "condition" not in semantics.clear_fields


def test_explicit_automatic_is_recovered_when_llm_misses_it() -> None:
    sanitized = sanitize_understanding(
        RequestUnderstanding(
            intent="catalog_search",
            preference_updates=PreferenceUpdates(fuel_type="Gasoline", min_year=2024),
        ),
        "بنزين أوتوماتيك من 2024 وطالع",
    )

    assert sanitized.preference_updates.transmission == "Automatic"
    assert sanitized.preference_updates.fuel_type == "Gasoline"
    assert sanitized.preference_updates.min_year == 2024


def test_required_new_survives_unrelated_dont_care_negation() -> None:
    sanitized = sanitize_understanding(
        RequestUnderstanding(
            intent="catalog_search",
            preference_updates=PreferenceUpdates(body_type="SUV"),
            preference_clears=["body_type"],
        ),
        "مش فارق معايا سيدان ولا SUV، بس لازم جديدة",
    )

    assert sanitized.preference_updates.condition == "new"


def test_invalid_explicit_car_id_never_creates_sales_lead(db_session) -> None:
    conversation = ConversationSession(id=uuid.uuid4())
    db_session.add(conversation)
    db_session.commit()
    workflow = ConversationalBusinessActionWorkflowService(db_session)

    plan = workflow.prepare_action(
        conversation.id,
        "sales_lead",
        "العربية ID 999 عايز احجزها، اسمي عمر أحمد ورقمي 01012345678",
    )

    assert plan["status"] == "invalid_car"
    assert plan["attempted_car_id"] == 999
    assert db_session.scalar(select(func.count(SalesLead.id))) == 0
    assert db_session.scalar(select(func.count(TestDriveRequest.id))) == 0
    db_session.refresh(conversation)
    assert conversation.pending_action is None


def test_context_repairs_invalid_car_and_expired_pending_date(db_session) -> None:
    conversation = ConversationSession(
        id=uuid.uuid4(),
        pending_action={
            "type": "test_drive",
            "attempt_id": str(uuid.uuid4()),
            "fields": {
                "car_id": 999,
                "customer_name": "عمر أحمد",
                "phone": "01012345678",
                "preferred_date": "2026-09-18",
                "preferred_time": "14:00",
            },
        },
    )
    db_session.add(conversation)
    db_session.commit()

    context = ConversationContextService(
        db_session,
        today_provider=lambda: date(2026, 9, 19),
    ).load(conversation.id)

    assert context.pending_action is not None
    assert context.pending_action["fields"] == {
        "customer_name": "عمر أحمد",
        "phone": "01012345678",
    }
    db_session.refresh(conversation)
    assert conversation.pending_action == context.pending_action


def test_past_date_in_current_turn_cannot_create_ready_booking(db_session) -> None:
    car = Car(
        brand="BMW",
        model="X6",
        year=2025,
        condition="used",
        price_egp=Decimal("2700000"),
        mileage_km=10_000,
        source="release-blocker-test",
        source_id="past-date-current-turn",
        active=True,
    )
    conversation = ConversationSession(id=uuid.uuid4())
    db_session.add_all([car, conversation])
    db_session.commit()
    workflow = ConversationalBusinessActionWorkflowService(
        db_session,
        today_provider=lambda: date(2026, 9, 19),
    )

    plan = workflow.prepare_action(
        conversation.id,
        "test_drive",
        f"العربية ID {car.id} اسمي عمر أحمد ورقمي 01012345678 "
        "يوم 2026-09-18 الساعة 2 العصر",
    )

    assert plan["status"] == "missing_fields"
    assert plan["invalid_preferred_date"] is True
    assert "preferred_date" in plan["missing_fields"]
    assert "preferred_time" in plan["missing_fields"]


def test_arabic_afternoon_is_an_unambiguous_pm_time() -> None:
    assert explicit_time("بعد بكرة الساعة 3 العصر") == time(15, 0)
    assert explicit_time("3 العصر") == time(15, 0)


def test_arabic_noon_daypart_is_parsed_as_pm() -> None:
    assert explicit_time("الساعة 1 الظهر") == time(13, 0)
    assert explicit_time("الساعة 12 الظهر") == time(12, 0)


def test_numeric_million_and_half_is_parsed_generically() -> None:
    assert explicit_budget_ceiling("معايا 2 ونص مليون جنيه") == 2_500_000
    assert explicit_budget_ceiling("ميزانيتي ٣ ونص مليون") == 3_500_000


def test_response_memory_context_contains_no_contact_pii() -> None:
    memory = CustomerMemory(
        customer_name="مؤمن محمد",
        phone="01229847585",
        email="customer@example.com",
        scope="authenticated_user_history",
    )

    context = memory.safe_context()
    serialized = repr(context)

    assert context == {"available_for_actions": True}
    assert "مؤمن" not in serialized
    assert "7585" not in serialized
    assert "customer@example.com" not in serialized
    assert "authenticated_user_history" not in serialized


def test_ambiguous_pending_time_renderer_asks_a_specific_question() -> None:
    response = render_business_action(
        {
            "status": "missing_fields",
            "intent": "test_drive",
            "missing_fields": ["preferred_time"],
            "ambiguous_time": True,
            "ambiguous_time_hour": 4,
        }
    )

    assert "4 صباح" in response
    assert "4 العصر" in response
    assert "وقت غلط" in response


def test_reused_account_contact_is_disclosed_without_exposing_values() -> None:
    response = render_business_action(
        {
            "status": "missing_fields",
            "intent": "test_drive",
            "missing_fields": ["preferred_date", "preferred_time"],
            "memory_fields_used": ["customer_name", "phone"],
            "customer_memory_scope": "authenticated_user_history",
        }
    )

    assert "الاسم ورقم الموبايل" in response
    assert "طلب سابق على حسابك" in response
    assert "لو حابب تغيّرهم" in response
    assert "اليوم أو التاريخ المناسب والوقت المناسب" in response
    assert "012" not in response


def test_successful_request_discloses_reused_contact_source() -> None:
    response = render_business_action(
        {
            "status": "success",
            "intent": "test_drive",
            "request_id": 11,
            "preferred_date": "2026-09-20",
            "preferred_time": "14:00",
            "memory_fields_used": ["customer_name", "phone"],
            "customer_memory_scope": "authenticated_user_history",
        }
    )

    assert "تم تسجيل طلب تجربة القيادة برقم 11" in response
    assert "الاسم ورقم الموبايل" in response
    assert "طلب سابق على حسابك" in response


def test_cancelled_pending_draft_renderer_does_not_claim_missing_active_request() -> None:
    response = render_business_action(
        {"status": "draft_cancelled", "intent": "test_drive"}
    )

    assert "تم إلغاء استكمال" in response
    assert "مفيش حجز اتسجل" in response
    assert "مفيش طلب تجربة قيادة نشط" not in response


def test_direct_try_driving_phrase_overrides_rag_misclassification() -> None:
    understanding = RequestUnderstanding(intent="knowledge_question")

    sanitized = sanitize_understanding(
        understanding,
        "هو انا ينفع اجي اجرب اسوقها",
    )

    assert sanitized.intent == "test_drive"


def test_test_drive_policy_question_stays_knowledge_question() -> None:
    understanding = RequestUnderstanding(intent="knowledge_question")

    sanitized = sanitize_understanding(
        understanding,
        "إيه نظام التست درايف والمطلوب إيه؟",
    )

    assert sanitized.intent == "knowledge_question"


def test_negated_used_condition_cannot_override_explicit_new_meaning() -> None:
    understanding = RequestUnderstanding(
        intent="catalog_search",
        preference_updates=PreferenceUpdates(condition="new"),
    )

    sanitized = sanitize_understanding(
        understanding,
        "لا مش عايز المستعملة، أنا هشتري الجديدة",
    )

    assert sanitized.preference_updates.condition == "new"


def _reference_state(message: str) -> dict:
    return {
        "normalized_message": message,
        "preferences": {"max_price": 2_000_000, "condition": "new"},
        "active_snapshot": {
            "id": 44,
            "items": [
                {
                    "position": 1,
                    "car_id": 101,
                    "car": {"brand": "Chevrolet", "model": "Malibu"},
                },
                {
                    "position": 2,
                    "car_id": 102,
                    "car": {"brand": "Kia", "model": "XCeed"},
                },
            ],
        },
        "selected_car_id": None,
        "recent_messages": [],
        "errors": [],
        "trace": [],
    }


def test_visible_model_from_llm_resolves_before_filter_mutation() -> None:
    class ReferenceLLM:
        model_name = "reference-test"

        def understand(self, message, *, recent_messages, preferences):
            del message, recent_messages, preferences
            return RequestUnderstanding(
                intent="car_selection",
                preference_updates=PreferenceUpdates(model="Malibu"),
            )

    orchestrator = object.__new__(ConversationalSalesOrchestrator)
    orchestrator.llm = ReferenceLLM()

    update = orchestrator._understand_request(_reference_state("جميلة أوي الماليبو"))

    assert update["car_reference"] == 1
    assert update["turn_semantics"]["mode"] == "reference"
    assert "model" not in update["extracted_preferences"]


def test_visible_model_survives_catalog_search_misclassification() -> None:
    class MisclassifiedLLM:
        model_name = "misclassified-reference-test"

        def understand(self, message, *, recent_messages, preferences):
            del message, recent_messages, preferences
            return RequestUnderstanding(
                intent="catalog_search",
                preference_updates=PreferenceUpdates(model="Malibu"),
            )

    orchestrator = object.__new__(ConversationalSalesOrchestrator)
    orchestrator.llm = MisclassifiedLLM()

    update = orchestrator._understand_request(_reference_state("جميلة أوي الماليبو"))

    assert update["intent"] == "car_selection"
    assert update["car_reference"] == 1
    assert "model" not in update["extracted_preferences"]


def test_llm_ordinal_is_validated_against_visible_snapshot_before_mutation() -> None:
    class OrdinalLLM:
        model_name = "ordinal-test"

        def understand(self, message, *, recent_messages, preferences):
            del message, recent_messages, preferences
            return RequestUnderstanding(
                intent="car_details",
                preference_updates=PreferenceUpdates(model="Malibu"),
                car_reference=1,
            )

    orchestrator = object.__new__(ConversationalSalesOrchestrator)
    orchestrator.llm = OrdinalLLM()

    update = orchestrator._understand_request(_reference_state("قصدي أول عربية"))

    assert update["car_reference"] == 1
    assert update["turn_semantics"]["mode"] == "reference"
    assert "model" not in update["extracted_preferences"]


def test_deterministic_ordinal_recovers_when_llm_misses_reference() -> None:
    class MissedOrdinalLLM:
        model_name = "missed-ordinal-test"

        def understand(self, message, *, recent_messages, preferences):
            del message, recent_messages, preferences
            return RequestUnderstanding(intent="general")

    orchestrator = object.__new__(ConversationalSalesOrchestrator)
    orchestrator.llm = MissedOrdinalLLM()

    update = orchestrator._understand_request(_reference_state("لا يا باشا قصدي على أول عربية"))

    assert update["intent"] == "car_selection"
    assert update["car_reference"] == 1
    assert update["turn_semantics"]["mode"] == "reference"
