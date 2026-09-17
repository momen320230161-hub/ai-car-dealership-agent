"""Release-blocker regressions captured from live customer conversations."""

from datetime import time

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
