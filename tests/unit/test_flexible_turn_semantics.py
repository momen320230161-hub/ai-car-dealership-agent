"""Regression tests for flexible conversational search semantics."""

from __future__ import annotations

from decimal import Decimal

from app.agent.catalog_qualification import explicit_brand_from_message
from app.agent.conversational_orchestrator import ConversationalSalesOrchestrator
from app.agent.schemas import PreferenceUpdates, RequestUnderstanding
from app.agent.turn_semantics import analyze_turn
from app.models.car import Car
from app.services.catalog_service import CatalogService


def _seed_car(
    db_session,
    *,
    source_id: str,
    brand: str,
    model: str,
    price: int,
    condition: str = "used",
    body_type: str = "Sedan",
) -> Car:
    car = Car(
        brand=brand,
        model=model,
        year=2025,
        condition=condition,
        price_egp=Decimal(price),
        body_type=body_type,
        transmission="Automatic",
        fuel_type="Gasoline",
        mileage_km=0 if condition == "new" else 20_000,
        source="flexible-turn-test",
        source_id=source_id,
        active=True,
    )
    db_session.add(car)
    db_session.commit()
    return car


def test_dont_care_turn_clears_form_like_constraints_and_searches() -> None:
    semantics = analyze_turn(
        "مش مهم والله اعرضلي اللي عندك بالسعر ده",
        {"max_price": 800_000, "condition": "used", "body_type": "Sedan"},
        {},
    )

    assert semantics.force_catalog_search is True
    assert "condition" in semantics.force_clear_fields
    assert "body_type" in semantics.force_clear_fields
    assert "max_price" not in semantics.clear_fields


def test_new_then_used_is_soft_fallback_not_hard_used_filter() -> None:
    semantics = analyze_turn(
        "هاتها زيرو لو مفيش عايزها استعمال",
        {"max_price": 800_000, "body_type": "Sedan"},
        {"condition": "used"},
    )

    assert semantics.soft_condition_order == ("new", "used")
    assert "condition" in semantics.force_clear_fields
    assert semantics.force_catalog_search is True


def test_budget_increase_without_amount_does_not_change_budget() -> None:
    semantics = analyze_turn(
        "ممكن ازود ال budget",
        {"max_price": 800_000, "brand": "BMW"},
        {},
    )

    assert semantics.budget_change_unspecified is True
    assert semantics.force_catalog_search is False


def test_budget_plus_explicit_purchase_request_forces_flexible_search() -> None:
    semantics = analyze_turn(
        "عايز اشتري عربية ومعايا 2 مليون",
        {},
        {"max_price": 2_000_000},
    )

    assert semantics.force_catalog_search is True


def test_arabic_definite_article_resolves_brand_alias() -> None:
    assert explicit_brand_from_message("عايز اشتري الرينو") == "Renault"


def test_reference_turn_does_not_convert_visible_brand_into_filter() -> None:
    class ReferenceLLM:
        model_name = "reference-test"

        def understand(self, message, *, recent_messages, preferences):
            del message, recent_messages, preferences
            return RequestUnderstanding(
                intent="car_selection",
                preference_updates=PreferenceUpdates(brand="Renault"),
            )

    orchestrator = object.__new__(ConversationalSalesOrchestrator)
    orchestrator.llm = ReferenceLLM()
    state = {
        "normalized_message": "عايز اشتري الرينو",
        "preferences": {"max_price": 800_000, "condition": "used"},
        "active_snapshot": {
            "id": 10,
            "items": [
                {
                    "position": 1,
                    "car_id": 101,
                    "car": {"brand": "Renault", "model": "Logan"},
                },
                {
                    "position": 2,
                    "car_id": 102,
                    "car": {"brand": "Nissan", "model": "Sunny"},
                },
            ],
        },
        "selected_car_id": None,
        "recent_messages": [],
        "errors": [],
        "trace": [],
    }

    update = orchestrator._understand_request(state)

    assert update["car_reference"] == 1
    assert update["turn_semantics"]["mode"] == "reference"
    assert "brand" not in update["extracted_preferences"]


def test_catalog_model_resolution_maps_320_to_unique_320i(db_session) -> None:
    _seed_car(
        db_session,
        source_id="bmw-320i",
        brand="BMW",
        model="320i",
        price=3_475_000,
        condition="new",
    )
    _seed_car(
        db_session,
        source_id="bmw-218i",
        brand="BMW",
        model="218i",
        price=2_650_000,
        condition="new",
    )
    orchestrator = object.__new__(ConversationalSalesOrchestrator)
    orchestrator.catalog = CatalogService(db_session)

    assert orchestrator._resolve_catalog_model("BMW", "320") == "320i"


def test_no_result_diagnosis_distinguishes_existing_model_above_budget(db_session) -> None:
    _seed_car(
        db_session,
        source_id="bmw-over-budget",
        brand="BMW",
        model="320i",
        price=3_475_000,
        condition="new",
    )
    orchestrator = object.__new__(ConversationalSalesOrchestrator)
    orchestrator.catalog = CatalogService(db_session)

    result = orchestrator._diagnose_no_results(
        {"brand": "BMW", "model": "320i", "max_price": 800_000}
    )

    assert result["type"] == "clarification"
    assert "3,475,000" in result["message"]
    assert "800,000" in result["message"]
    assert "موجودة" in result["message"]


def test_price_relaxation_reports_true_cheapest_even_when_ranked_desc(db_session) -> None:
    _seed_car(
        db_session,
        source_id="relax-720",
        brand="Renault",
        model="Taliant",
        price=720_000,
    )
    _seed_car(
        db_session,
        source_id="relax-690",
        brand="Chevrolet",
        model="Optra",
        price=690_000,
    )

    result = CatalogService(db_session).recommend_with_relaxation(
        {"max_price": 600_000, "condition": "used", "body_type": "Sedan"},
        limit=3,
    )

    assert result["type"] == "price_relaxation"
    assert result["cheapest_price"] == 690_000


def test_more_results_question_is_not_misread_as_direct_command() -> None:
    semantics = analyze_turn(
        "مفيش غير دول؟",
        {"max_price": 800_000, "condition": "used"},
        {},
    )

    assert semantics.more_results_question is True
    assert semantics.pagination_requested is False


def test_broadening_clears_model_but_keeps_brand_and_budget() -> None:
    semantics = analyze_turn(
        "طب اعرضلي العربيات اللي عندك",
        {"brand": "BMW", "model": "320i", "max_price": 800_000},
        {},
    )

    assert semantics.mode == "broaden"
    assert "model" in semantics.force_clear_fields
    assert "brand" not in semantics.clear_fields
    assert "max_price" not in semantics.clear_fields
