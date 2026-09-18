"""Regression tests for behavior ported from the Langflow prototype."""

from app.agent.llm import _with_history_reference
from app.agent.schemas import RequestUnderstanding, sanitize_understanding


def test_single_visible_car_reaction_resolves_from_recent_history() -> None:
    raw = RequestUnderstanding(intent="car_selection")
    history = [
        {
            "role": "assistant",
            "content": (
                "حسب البيانات المتاحة عندي في الكتالوج المسجل: "
                "1. Chery Tiggo 4 — 2026 — جديدة — 930,000 جنيه"
            ),
        }
    ]

    understood = _with_history_reference(raw, history, "اوف حلوة ديه")
    sanitized = sanitize_understanding(understood, "اوف حلوة ديه")

    assert understood.car_reference == 1
    assert sanitized.car_reference == 1


def test_multiple_visible_cars_do_not_get_guessed_from_deictic_reaction() -> None:
    raw = RequestUnderstanding(intent="car_selection")
    history = [
        {
            "role": "assistant",
            "content": "1. Kia XCeed — 1,490,000 جنيه 2. Chery Tiggo 8 — 1,420,000 جنيه",
        }
    ]

    understood = _with_history_reference(raw, history)

    assert understood.car_reference is None


def test_large_invented_reference_is_still_rejected() -> None:
    raw = RequestUnderstanding(intent="car_selection", car_reference=999999)

    sanitized = sanitize_understanding(raw, "اوف حلوة ديه")

    assert sanitized.car_reference is None


def test_ambiguous_history_clears_llm_guess_without_explicit_ordinal() -> None:
    raw = RequestUnderstanding(intent="car_selection", car_reference=1)
    history = [
        {
            "role": "assistant",
            "content": "1. Kia XCeed — 1,490,000 جنيه 2. Chery Tiggo 8 — 1,420,000 جنيه",
        }
    ]

    understood = _with_history_reference(raw, history, "حلوة ديه")

    assert understood.car_reference is None
