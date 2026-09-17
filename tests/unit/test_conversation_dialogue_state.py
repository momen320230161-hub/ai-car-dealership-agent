"""Regressions for persistent non-filter conversational goal state."""

import uuid

from app.agent.conversational_orchestrator import ConversationalSalesOrchestrator
from app.agent.schemas import PreferenceUpdates, RequestUnderstanding
from app.models.conversation import ConversationSession
from app.services.conversation_context_service import ConversationContextService
from app.services.conversation_dialogue_state_service import ConversationDialogueStateService


def test_catalog_goal_persists_separately_from_vehicle_preferences(db_session) -> None:
    conversation = ConversationSession(
        id=uuid.uuid4(),
        preferences={"brand": "BMW", "max_price": 700_000},
    )
    db_session.add(conversation)
    db_session.commit()

    state = ConversationDialogueStateService(db_session).set_catalog_goal(
        conversation.id,
        "recommend",
    )
    db_session.refresh(conversation)

    assert state == {"catalog_goal": "recommend"}
    assert conversation.dialogue_state == {"catalog_goal": "recommend"}
    assert conversation.preferences == {"brand": "BMW", "max_price": 700_000}

    context = ConversationContextService(db_session).load(conversation.id)
    assert context.dialogue_state == {"catalog_goal": "recommend"}


def test_budget_refinement_resumes_persisted_recommendation_goal() -> None:
    class BudgetLLM:
        model_name = "budget-refinement-test"

        def understand(self, message, *, recent_messages, preferences):
            del message, recent_messages, preferences
            return RequestUnderstanding(
                intent="catalog_search",
                preference_updates=PreferenceUpdates(max_price=5_000_000),
            )

    orchestrator = object.__new__(ConversationalSalesOrchestrator)
    orchestrator.llm = BudgetLLM()
    state = {
        "normalized_message": "معايا 5 مليون ايه النظام",
        "preferences": {"brand": "BMW", "max_price": 700_000},
        "dialogue_state": {"catalog_goal": "recommend"},
        "active_snapshot": None,
        "selected_car_id": None,
        "recent_messages": [],
        "errors": [],
        "trace": [],
    }

    update = orchestrator._understand_request(state)

    assert update["intent"] == "catalog_search"
    assert update["extracted_preferences"]["max_price"] == 5_000_000
    assert update["turn_semantics"]["resume_catalog_goal"] is True
    assert update["turn_semantics"]["force_catalog_search"] is True


def test_explicit_recommendation_request_sets_persistent_goal_operation() -> None:
    class RecommendationLLM:
        model_name = "recommendation-goal-test"

        def understand(self, message, *, recent_messages, preferences):
            del message, recent_messages, preferences
            return RequestUnderstanding(intent="general")

    orchestrator = object.__new__(ConversationalSalesOrchestrator)
    orchestrator.llm = RecommendationLLM()
    state = {
        "normalized_message": "رشحلي كل اللي عندك",
        "preferences": {"brand": "BMW", "max_price": 700_000},
        "dialogue_state": {},
        "active_snapshot": None,
        "selected_car_id": None,
        "recent_messages": [],
        "errors": [],
        "trace": [],
    }

    update = orchestrator._understand_request(state)

    assert update["intent"] == "catalog_search"
    assert update["turn_semantics"]["catalog_goal_operation"] == "recommend"
    assert update["turn_semantics"]["force_catalog_search"] is True
