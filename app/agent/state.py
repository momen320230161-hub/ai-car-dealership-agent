"""Typed transient state passed between Phase 4 LangGraph nodes."""

from __future__ import annotations

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    session_id: str | None
    user_message: Any
    normalized_message: str
    recent_messages: list[dict[str, Any]]
    preferences: dict[str, Any]
    dialogue_state: dict[str, Any]
    selected_car_id: int | None
    active_snapshot: dict[str, Any] | None
    pending_action: dict[str, Any] | None
    intent: str
    extracted_preferences: dict[str, Any]
    llm_dialogue_action: str | None
    llm_preference_clears: list[str]
    llm_budget_change: str
    pending_field_answer: str
    llm_condition_preference_order: list[str]
    visible_reference_selector: dict[str, Any]
    turn_semantics: dict[str, Any]
    car_reference: str | int | None
    comparison_references: list[str | int]
    explicit_car_id: int | None
    knowledge_category_hint: str | None
    catalog_result: dict[str, Any] | None
    retrieved_knowledge: list[dict[str, Any]]
    grounded_knowledge: dict[str, Any] | None
    knowledge_supported: bool
    action_status: dict[str, Any] | None
    general_context: dict[str, Any] | None
    route: str
    selected_route: str
    response: str
    errors: list[str]
    guard_error: str | None
    persisted: bool
    trace: list[str]
