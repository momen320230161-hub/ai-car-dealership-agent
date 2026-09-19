"""Regression tests for response planning and conversational composition policy."""

from app.agent.composition_policy import (
    build_response_plan,
    composition_policy_allows,
)


def test_customer_response_rejects_plural_address_for_single_user() -> None:
    assert not composition_policy_allows(
        "حبايبي، تحبوا تعرفوا تفاصيل أكتر؟",
        {"max_questions": 1, "allow_evaluative_superlatives": False},
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


def test_recommendation_policy_rejects_unsupported_best_language() -> None:
    plan = build_response_plan(
        {
            "route": "catalog",
            "catalog_result": {"type": "recommendations", "cars": []},
            "recent_messages": [],
        }
    )

    assert plan["preferred_response_shape"] == "shortlist_then_optional_next_step"
    assert plan["allow_evaluative_superlatives"] is False
    assert not composition_policy_allows("دي أفضل الخيارات المتاحة ليك.", plan)
    assert composition_policy_allows("دي 3 خيارات مطابقة للشروط اللي قلتها.", plan)


def test_clarification_policy_rejects_multi_questionnaire() -> None:
    plan = build_response_plan(
        {
            "route": "catalog",
            "catalog_result": {"type": "clarification"},
            "recent_messages": [],
        }
    )

    assert plan["preferred_response_shape"] == "single_high_value_question"
    assert not composition_policy_allows(
        "تحبها جديدة ولا مستعملة؟ وعايز SUV ولا Sedan؟",
        plan,
    )
    assert composition_policy_allows("تحبها جديدة ولا مستعملة؟", plan)


def test_advice_style_budget_turn_forces_catalog_search() -> None:
    from app.agent.turn_semantics import analyze_turn

    semantics = analyze_turn(
        "لو انت مكاني ومعاك مليون ونص هتشتري ايه",
        {},
        {"max_price": 1_500_000},
    )

    assert semantics.force_catalog_search is True


def test_greeting_is_rejected_after_first_assistant_turn() -> None:
    plan = build_response_plan(
        {
            "route": "catalog",
            "catalog_result": {"type": "recommendations", "cars": []},
            "recent_messages": [
                {
                    "role": "assistant",
                    "content": "حسب البيانات المتاحة عندي، عندي اختيار مناسب.",
                }
            ],
        }
    )

    assert plan["allow_greeting"] is False
    assert not composition_policy_allows(
        "يا هلا بيك! حسب البيانات المتاحة عندي عندي اختيار مناسب.",
        plan,
    )
