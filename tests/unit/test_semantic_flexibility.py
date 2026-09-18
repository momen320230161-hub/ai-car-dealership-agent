"""Regression tests for LLM-first conversational semantics with deterministic safety."""

from __future__ import annotations

import uuid
from decimal import Decimal

from app.agent.conversational_orchestrator import ConversationalSalesOrchestrator
from app.agent.graph import SalesOrchestrator
from app.agent.schemas import PreferenceUpdates, RequestUnderstanding
from app.models.car import Car
from app.models.conversation import ConversationSession
from app.rag.embeddings import DeterministicEmbeddingProvider


class _SemanticLLM:
    model_name = "semantic-test"

    def __init__(self, understanding: RequestUnderstanding):
        self.understanding = understanding

    def understand(self, message, *, recent_messages, preferences):
        del message, recent_messages, preferences
        return self.understanding

    def compose_general(self, message, *, verified_context):
        del message
        return str(verified_context.get("authoritative_fallback") or "تمام.")


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



def test_social_semantics_cannot_clear_persistent_catalog_preferences() -> None:
    orchestrator = object.__new__(ConversationalSalesOrchestrator)
    orchestrator.llm = _SemanticLLM(
        RequestUnderstanding(
            intent="general",
            dialogue_action="social",
            preference_clears=["brand"],
        )
    )

    update = orchestrator._understand_request(
        _state("تسلم يا باشا", preferences={"brand": "BMW"})
    )

    assert "brand" not in update["extracted_preferences"]
    assert update["turn_semantics"]["clear_fields"] == []




def test_social_semantics_cannot_apply_accidental_preference_updates() -> None:
    orchestrator = object.__new__(ConversationalSalesOrchestrator)
    orchestrator.llm = _SemanticLLM(
        RequestUnderstanding(
            intent="general",
            preference_updates=PreferenceUpdates(brand="BMW"),
            dialogue_action="social",
        )
    )

    update = orchestrator._understand_request(
        _state("تسلم يا باشا", preferences={"body_type": "SUV"})
    )

    assert update["extracted_preferences"] == {}
    assert update["turn_semantics"]["source"] == "llm"


def test_empty_recommendation_does_not_force_random_catalog_search() -> None:
    orchestrator = object.__new__(ConversationalSalesOrchestrator)
    orchestrator.llm = _SemanticLLM(
        RequestUnderstanding(
            intent="catalog_search",
            dialogue_action="recommend",
        )
    )

    update = orchestrator._understand_request(_state("عايز عربية"))

    assert update["intent"] == "catalog_search"
    assert update["turn_semantics"]["force_catalog_search"] is False


def test_single_useful_preference_is_enough_for_semantic_recommendation() -> None:
    orchestrator = object.__new__(ConversationalSalesOrchestrator)
    orchestrator.llm = _SemanticLLM(
        RequestUnderstanding(
            intent="catalog_search",
            preference_updates=PreferenceUpdates(transmission="Automatic"),
            dialogue_action="recommend",
        )
    )

    update = orchestrator._understand_request(_state("عايز أي عربية أوتوماتيك"))

    assert update["extracted_preferences"]["transmission"] == "Automatic"
    assert update["turn_semantics"]["force_catalog_search"] is True


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
    assert context["visible_recommendations"][0]["transmission"] is None
    assert context["selected_car"]["model"] == "Sunny"
    assert "price_egp" in context["selected_car"]
    assert "mileage_km" in context["selected_car"]
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



def test_selected_car_marker_survives_without_active_snapshot() -> None:
    context = SalesOrchestrator._safe_understanding_context(
        {
            "dialogue_state": {},
            "selected_car_id": 77,
            "active_snapshot": None,
            "pending_action": None,
        }
    )

    assert context["visible_recommendations"] == []
    assert context["selected_car"] == {"selected": True}


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


def test_production_orchestrator_applies_semantic_relaxation_end_to_end(db_session) -> None:
    cars = [
        Car(
            brand="Nissan",
            model="Sunny",
            year=2025,
            condition="used",
            price_egp=Decimal("900000"),
            body_type="Sedan",
            transmission="Automatic",
            fuel_type="Gasoline",
            mileage_km=20_000,
            source="semantic-e2e",
            source_id="semantic-e2e-1",
            active=True,
        ),
        Car(
            brand="Chery",
            model="Tiggo 4",
            year=2025,
            condition="new",
            price_egp=Decimal("1200000"),
            body_type="SUV",
            transmission="Automatic",
            fuel_type="Gasoline",
            mileage_km=0,
            source="semantic-e2e",
            source_id="semantic-e2e-2",
            active=True,
        ),
    ]
    conversation = ConversationSession(
        id=uuid.uuid4(),
        preferences={"condition": "used", "body_type": "Sedan"},
    )
    db_session.add_all([*cars, conversation])
    db_session.commit()

    llm = _SemanticLLM(
        RequestUnderstanding(
            intent="catalog_search",
            preference_updates=PreferenceUpdates(transmission="Automatic"),
            dialogue_action="recommend",
            preference_clears=["condition", "body_type"],
        )
    )
    orchestrator = ConversationalSalesOrchestrator(
        db_session,
        llm,
        DeterministicEmbeddingProvider(),
    )

    result = orchestrator.handle_message(conversation.id, "أي حاجة أوتوماتيك بس")

    db_session.refresh(conversation)
    assert result.errors == ()
    assert result.route == "catalog"
    assert conversation.preferences == {"transmission": "Automatic"}
    assert len(result.visible_recommendations) == 2
