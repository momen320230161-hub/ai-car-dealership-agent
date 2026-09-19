"""Release-blocker regressions captured from live customer conversations."""

from datetime import time

from app.agent.business_rendering import render_business_action
from app.agent.conversational_orchestrator import ConversationalSalesOrchestrator
from app.agent.schemas import (
    PreferenceUpdates,
    RequestUnderstanding,
    explicit_budget_ceiling,
    sanitize_understanding,
)
from app.agent.turn_semantics import analyze_turn
from app.services.business_action_parsing import explicit_time
from app.services.customer_memory_service import CustomerMemory


def test_scoped_body_waiver_does_not_erase_explicit_new_condition() -> None:
    semantics = analyze_turn(
        "عايزها جديدة مش فارق معايا سيدان أو لا",
        {"max_price": 800_000},
        {"condition": "new", "body_type": "Sedan"},
    )

    assert "body_type" in semantics.force_clear_fields
    assert "condition" not in semantics.clear_fields


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
