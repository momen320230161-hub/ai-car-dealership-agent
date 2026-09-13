"""Regression coverage for explicit Egyptian-Arabic catalog budgets."""

from __future__ import annotations

import pytest

from app.agent.schemas import RequestUnderstanding, explicit_budget_ceiling, sanitize_understanding


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("عايز اشتري عربية ومعايا اتنين ونص مليون", 2_500_000),
        ("عايز عربية بميزانية اتنين مليون ونص", 2_500_000),
        ("ميزانيتي 2.5 مليون", 2_500_000),
        ("خلي الميزانية مليون ونص", 1_500_000),
        ("عايز عربية تحت 1000000", 1_000_000),
    ],
)
def test_explicit_budget_ceiling_handles_common_customer_phrasing(message, expected):
    assert explicit_budget_ceiling(message) == expected


def test_sanitizer_keeps_llm_budget_when_words_explicitly_support_it():
    raw = RequestUnderstanding(
        intent="catalog_search",
        preference_updates={"max_price": 2_500_000},
    )

    sanitized = sanitize_understanding(raw, "عايز اشتري عربية ومعايا اتنين ونص مليون")

    assert sanitized.preference_updates.max_price == 2_500_000


def test_sanitizer_recovers_explicit_budget_when_llm_omits_it():
    raw = RequestUnderstanding(intent="catalog_search")

    sanitized = sanitize_understanding(raw, "عايز اشتري عربية ومعايا اتنين ونص مليون")

    assert sanitized.preference_updates.max_price == 2_500_000


def test_sanitizer_still_rejects_invented_budget_without_message_evidence():
    raw = RequestUnderstanding(
        intent="catalog_search",
        preference_updates={"max_price": 2_500_000},
    )

    sanitized = sanitize_understanding(raw, "عايز اشتري عربية")

    assert sanitized.preference_updates.max_price is None
