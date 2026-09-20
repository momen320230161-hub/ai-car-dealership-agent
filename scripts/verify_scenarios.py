"""Targeted verification harness for the 6 critical RAG & Conversational scenarios."""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from typing import Any

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app
from app.agent.factory import build_sales_orchestrator
from app.agent.llm import AgentLLMError
from app.extensions import db
from app.models.car import Car
from app.models.conversation import ConversationSession
from app.models.recommendation import RecommendationSnapshot, RecommendationSnapshotItem


def run_scenario(
    app,
    scenario_name: str,
    message: str,
    *,
    setup_visible_cars: bool = False,
    mock_category_hint: str | None = None,
    mock_compose_fail: bool = False,
) -> dict[str, Any]:
    session_id = uuid.uuid4()

    # 1. Create fresh conversation session (dialogue_state belongs to ConversationSession)
    convo = ConversationSession(
        id=session_id,
        preferences={},
        dialogue_state={},
    )
    db.session.add(convo)
    db.session.commit()

    # 2. Optionally set up 3 active visible cars in an active recommendation snapshot
    car_ids = []
    if setup_visible_cars:
        car1 = Car(
            brand="MG",
            model="ZS",
            year=2024,
            price_egp=1000000,
            condition="new",
            source="mock",
            source_id=f"mock-{uuid.uuid4()}",
            active=True,
        )
        car2 = Car(
            brand="BYD",
            model="F3",
            year=2024,
            price_egp=500000,
            condition="new",
            source="mock",
            source_id=f"mock-{uuid.uuid4()}",
            active=True,
        )
        car3 = Car(
            brand="Kia",
            model="Sportage",
            year=2024,
            price_egp=2000000,
            condition="new",
            source="mock",
            source_id=f"mock-{uuid.uuid4()}",
            active=True,
        )
        db.session.add_all([car1, car2, car3])
        db.session.commit()
        car_ids = [car1.id, car2.id, car3.id]

        snapshot = RecommendationSnapshot(
            session_id=session_id,
            sequence_no=1,
            status="active",
            items=[
                RecommendationSnapshotItem(position=1, car_id=car1.id),
                RecommendationSnapshotItem(position=2, car_id=car2.id),
                RecommendationSnapshotItem(position=3, car_id=car3.id),
            ],
        )
        db.session.add(snapshot)
        db.session.flush()
        # active_recommendation_snapshot_id belongs to ConversationSession
        convo.active_recommendation_snapshot_id = snapshot.id
        db.session.commit()

    # 3. Build production orchestrator using app config (real Gemini LLM and embeddings)
    orchestrator = build_sales_orchestrator(db.session, app.config)

    # 4. Apply mocks if requested
    orig_compose = getattr(orchestrator.llm, "compose_general", None)
    orig_compose_knowledge = getattr(orchestrator.llm, "compose_knowledge", None)
    orig_understand = getattr(orchestrator.llm, "understand", None)
    orig_understand_ctx = getattr(orchestrator.llm, "understand_with_context", None)

    if mock_compose_fail:
        def failing_compose_knowledge(*args: Any, **kwargs: Any) -> str:
            raise AgentLLMError("Simulated LLM compose_knowledge failure")
        orchestrator.llm.compose_knowledge = failing_compose_knowledge

    if mock_category_hint:
        if callable(orig_understand_ctx):
            def mock_understand_ctx(*args: Any, **kwargs: Any) -> Any:
                u = orig_understand_ctx(*args, **kwargs)
                u.knowledge_category_hint = mock_category_hint
                return u
            orchestrator.llm.understand_with_context = mock_understand_ctx
        elif callable(orig_understand):
            def mock_understand(*args: Any, **kwargs: Any) -> Any:
                u = orig_understand(*args, **kwargs)
                u.knowledge_category_hint = mock_category_hint
                return u
            orchestrator.llm.understand = mock_understand

    try:
        # AgentResponse has .response, .intent, .route, .errors, .selected_car_id
        result = orchestrator.handle_message(session_id, message)
        return {
            "scenario": scenario_name,
            "query": message,
            "intent": result.intent,
            "route": result.route,
            "response": result.response,
            "errors": list(result.errors),
            "selected_car_id": result.selected_car_id,
            "expected_car_id": car_ids[1] if len(car_ids) > 1 else None,
        }
    finally:
        if orig_compose is not None:
            orchestrator.llm.compose_general = orig_compose
        if orig_compose_knowledge is not None:
            orchestrator.llm.compose_knowledge = orig_compose_knowledge
        if orig_understand is not None:
            orchestrator.llm.understand = orig_understand
        if orig_understand_ctx is not None:
            orchestrator.llm.understand_with_context = orig_understand_ctx


def main() -> None:
    app = create_app()
    results = []

    with app.app_context():
        # Scenario 1: Meta question
        res1 = run_scenario(
            app,
            "1. Meta question",
            "لو العميل قال اختارلي العربية التانية، التانية تتحسب على أنهي عربيات؟",
            setup_visible_cars=True,
        )
        results.append(res1)

        # Scenario 2: Actual visible action
        res2 = run_scenario(
            app,
            "2. Actual visible action",
            "اختار التانية",
            setup_visible_cars=True,
        )
        results.append(res2)

        # Scenario 3: Actual cancellation
        res3 = run_scenario(
            app,
            "3. Actual cancellation",
            "عايز ألغي تجربة القيادة",
        )
        results.append(res3)

        # Scenario 4: Financing contract
        res4 = run_scenario(
            app,
            "4. Financing contract",
            "إيه البيانات الأساسية اللي المفروض تكون في عقد التمويل؟",
        )
        results.append(res4)

        # Scenario 5: Category-hint failure
        res5 = run_scenario(
            app,
            "5. Category-hint failure",
            "إيه البيانات الأساسية اللي المفروض تكون في عقد التمويل؟",
            mock_category_hint="wrong_simulated_category",
        )
        results.append(res5)

        # Scenario 6: LLM composition failure
        res6 = run_scenario(
            app,
            "6. LLM composition failure",
            "إيه البيانات الأساسية اللي المفروض تكون في عقد التمويل؟",
            mock_compose_fail=True,
        )
        results.append(res6)

    # Write human-readable UTF-8 report
    with open("verify_results.txt", "w", encoding="utf-8") as f:
        for r in results:
            f.write(f"\n{'='*70}\n")
            f.write(f"SCENARIO: {r['scenario']}\n")
            f.write(f"QUERY: {r['query']}\n")
            f.write(f"INTENT: {r['intent']}\n")
            f.write(f"ROUTE: {r['route']}\n")
            if r.get("selected_car_id") is not None:
                car_id = r["selected_car_id"]
                exp_id = r["expected_car_id"]
                f.write(f"SELECTED_CAR_ID: {car_id} (expected: {exp_id})\n")
            f.write(f"ERRORS: {r['errors']}\n")
            f.write(f"FINAL RESPONSE:\n{r['response']}\n")
            f.write(f"{'='*70}\n")

    # Write JSON results for structured inspection
    with open("verify_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print("Verification run complete. Results written to verify_results.txt and .json")


if __name__ == "__main__":
    main()
