"""Regression tests for response planning policy."""

from app.agent.composition_policy import (
    build_response_plan,
    composition_policy_allows,
)


def test_social_plan_avoids_forced_sales_followup_and_repeated_opening() -> None:
    plan = build_response_plan(
        {
            "route": "general",
            "recent_messages": [
                {"role": "assistant", "content": "تسلم يا غالي! أنا تمام الحمد لله."}
            ],
        }
    )

    assert plan["dialogue_act"] == "conversation"
    assert plan["question_strategy"] == "none_required"
    assert "تسلم يا غالي" in plan["avoid_openings"]
    assert not composition_policy_allows("تسلم يا غالي! أنا تمام الحمد لله.", plan)
    assert composition_policy_allows("أنا تمام الحمد لله، تسلم إنك سألت.", plan)
