"""Regression tests for LLM-first conversational semantics with deterministic safety."""

from __future__ import annotations

from app.agent.conversational_orchestrator import ConversationalSalesOrchestrator
from app.agent.graph import SalesOrchestrator
from app.agent.schemas import PreferenceUpdates, RequestUnderstanding


class _SemanticLLM:
    model_name = "semantic-test"

    def __init__(self, understanding: RequestUnderstanding):
        self.understanding = understanding

    def understand(self, message, *, recent_messages, preferences):
        del message, recent_messages, preferences
        return self.understanding


def _state(message: str, *, preferences: dict | None = None) -> dict:
    return {
        "normalized_message": message,
        "preferences": preferences or {},
        "dialogue_state": {},
        "active_snapshot": None,
        "selected_car_id": None,
        "recent_messages": [],
        "errors": [],
        "trace": [],
    }


def test_semantic_scope_keeps_new_while_clearing_body_type() -> None:
    orchestrator = object.__new__(ConversationalSalesOrchestrator)
    orchestrator.llm = _SemanticLLM(
        RequestUnderstanding(
            intent="catalog_search",
            preference_updates=PreferenceUpdates(condition="new"),
            dialogue_action="recommend",
            preference_clears=["body_type"],
        )
    )

    update = orchestrator._understand_request(
        _state(
            "مش فارق معايا سيدان ولا SUV، بس تكون جديدة",
            preferences={
                "max_price": 800_000,
                "condition": "used",
                "body_type": "Sedan",
            },
        )
    )

    assert update["extracted_preferences"]["condition"] == "new"
    assert update["extracted_preferences"]["body_type"] is None
    assert update["turn_semantics"]["source"] == "llm"
    assert update["turn_semantics"]["force_catalog_search"] is True


def test_semantic_dont_care_does_not_clear_the_only_required_transmission() -> None:
    orchestrator = object.__new__(ConversationalSalesOrchestrator)
    orchestrator.llm = _SemanticLLM(
        RequestUnderstanding(
            intent="catalog_search",
            preference_updates=PreferenceUpdates(transmission="Automatic"),
            dialogue_action="recommend",
            preference_clears=["condition", "body_type"],
        )
    )

    update = orchestrator._understand_request(
        _state(
            "أي حاجة أوتوماتيك بس",
            preferences={"condition": "used", "body_type": "Sedan"},
        )
    )

    assert update["extracted_preferences"]["transmission"] == "Automatic"
    assert update["extracted_preferences"]["condition"] is None
    assert update["extracted_preferences"]["body_type"] is None


def test_semantic_brand_waiver_clears_old_identity_without_phrase_rule() -> None:
    orchestrator = object.__new__(ConversationalSalesOrchestrator)
    orchestrator.llm = _SemanticLLM(
        RequestUnderstanding(
            intent="catalog_search",
            preference_updates=PreferenceUpdates(body_type="SUV"),
            dialogue_action="broaden",
            preference_clears=["brand", "model"],
        )
    )

    update = orchestrator._understand_request(
        _state(
            "مش مهم الماركة، المهم SUV",
            preferences={"brand": "BMW", "model": "X6", "max_price": 3_000_000},
        )
    )

    assert update["extracted_preferences"]["brand"] is None
    assert update["extracted_preferences"]["model"] is None
    assert update["extracted_preferences"]["body_type"] == "SUV"
    assert update["turn_semantics"]["mode"] == "broaden"


def test_semantic_continue_resumes_pending_action_without_resume_keyword() -> None:
    orchestrator = object.__new__(ConversationalSalesOrchestrator)
    state = {
        "intent": "general",
        "llm_dialogue_action": "continue",
        "normalized_message": "خلينا نرجع للي كنا بنعمله",
        "pending_action": {
            "type": "test_drive",
            "fields": {"car_id": 7, "customer_name": "محمد"},
        },
        "errors": [],
        "trace": [],
    }

    update = orchestrator._route_request(state)

    assert update["selected_route"] == "business_gate"


def test_budget_decrease_semantics_asks_for_new_limit() -> None:
    orchestrator = object.__new__(ConversationalSalesOrchestrator)
    state = {
        "route": "general",
        "intent": "general",
        "normalized_message": "عايز أقلل الميزانية شوية",
        "preferences": {"max_price": 1_500_000},
        "turn_semantics": {
            "budget_change_unspecified": True,
            "budget_change": "decrease_unspecified",
        },
        "recent_messages": [],
        "pending_action": None,
        "errors": [],
        "trace": [],
    }

    update = orchestrator._compose_response(state)

    assert "نقلل الميزانية" in update["response"]
    assert "1,500,000" in update["response"]


def test_safe_understanding_context_never_exposes_pending_contact_values() -> None:
    state = {
        "dialogue_state": {"catalog_goal": "recommend"},
        "selected_car_id": 22,
        "active_snapshot": {
            "items": [
                {
                    "position": 2,
                    "car_id": 22,
                    "car": {
                        "brand": "Nissan",
                        "model": "Sunny",
                        "year": 2025,
                        "condition": "used",
                        "body_type": "Sedan",
                    },
                }
            ]
        },
        "pending_action": {
            "type": "test_drive",
            "fields": {
                "car_id": 22,
                "customer_name": "محمد جمال",
                "phone": "01012345678",
            },
        },
    }

    context = SalesOrchestrator._safe_understanding_context(state)
    serialized = repr(context)

    assert context["dialogue_goal"] == "recommend"
    assert context["visible_recommendations"][0]["position"] == 2
    assert context["selected_car"]["model"] == "Sunny"
    assert set(context["pending_action"]["collected_fields"]) == {
        "car_id",
        "customer_name",
        "phone",
    }
    assert set(context["pending_action"]["missing_fields"]) == {
        "preferred_date",
        "preferred_time",
    }
    assert "محمد جمال" not in serialized
    assert "01012345678" not in serialized


def test_context_aware_llm_receives_structured_state_when_supported() -> None:
    captured = {}

    class ContextAwareLLM:
        model_name = "context-aware-test"

        def understand_with_context(
            self,
            message,
            *,
            recent_messages,
            preferences,
            conversation_context,
        ):
            del message, recent_messages, preferences
            captured.update(conversation_context)
            return RequestUnderstanding(intent="general")

    orchestrator = object.__new__(SalesOrchestrator)
    orchestrator.llm = ContextAwareLLM()
    state = {
        "normalized_message": "دي عاجباني",
        "preferences": {},
        "dialogue_state": {"catalog_goal": "recommend"},
        "selected_car_id": None,
        "active_snapshot": {
            "items": [
                {
                    "position": 1,
                    "car_id": 9,
                    "car": {"brand": "Kia", "model": "Sportage", "year": 2025},
                }
            ]
        },
        "pending_action": None,
        "recent_messages": [],
        "errors": [],
        "trace": [],
    }

    update = SalesOrchestrator._understand_request(orchestrator, state)

    assert update["intent"] == "general"
    assert captured["dialogue_goal"] == "recommend"
    assert captured["visible_recommendations"][0]["model"] == "Sportage"
