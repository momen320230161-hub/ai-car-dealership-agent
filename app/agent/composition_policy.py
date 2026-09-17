"""Behavioral policy for grounded response composition."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def build_response_plan(state: Mapping[str, Any]) -> dict[str, Any]:
    route = str(state.get("route") or "general")
    result = state.get("catalog_result")
    kind = str(result.get("type") or "") if isinstance(result, Mapping) else ""
    act = "conversation"
    shape = "direct_natural_reply"
    questions = "none_required"
    if route == "catalog" and kind == "comparison":
        act = "compare"
        shape = "differences_then_supporting_facts"
        questions = "single_optional_priority"
    elif route == "catalog" and kind in {"recommendations", "relaxed_suggestion"}:
        act = "recommend"
        shape = "shortlist_then_optional_next_step"
        questions = "single_optional_next_step"
    elif route == "catalog" and kind == "clarification":
        act = "clarify"
        shape = "single_high_value_question"
        questions = "single_high_value"
    elif route == "rag":
        act = "knowledge"
        shape = "grounded_answer"
    elif route == "business_gate":
        act = "business_action"
        shape = "status_or_missing_fields"
        questions = "missing_fields_only"
    return {
        "dialogue_act": act,
        "preferred_response_shape": shape,
        "question_strategy": questions,
        "max_questions": 1,
        "allow_evaluative_superlatives": bool(
            isinstance(result, Mapping) and result.get("ranking_evidence")
        ),
        "avoid_openings": _recent_openings(state.get("recent_messages")),
    }
