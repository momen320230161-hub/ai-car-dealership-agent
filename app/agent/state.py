"""Typed state shared by every LangGraph node."""

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    conversation_id: str
    customer_message_id: str
    user_message: str
    history: list[dict[str, str]]
    analysis: dict[str, Any]
    intent: str
    language: str
    vehicle_results: list[dict[str, Any]]
    knowledge_results: list[dict[str, Any]]
    sources: list[str]
    final_response: str
    response_persisted: bool
