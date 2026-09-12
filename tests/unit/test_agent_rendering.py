"""Focused regression tests for customer-facing deterministic agent rendering."""

from app.agent.rendering import render_catalog


def test_recommendations_show_condition_and_mileage() -> None:
    response = render_catalog(
        {
            "type": "recommendations",
            "cars": [
                {
                    "position": 1,
                    "car": {
                        "brand": "Chery",
                        "model": "Tiggo 4",
                        "year": 2026,
                        "condition": "used",
                        "mileage_km": 7500,
                        "price_egp": 930000,
                    },
                },
                {
                    "position": 2,
                    "car": {
                        "brand": "Toyota",
                        "model": "Corolla",
                        "year": 2025,
                        "condition": "new",
                        "mileage_km": 0,
                        "price_egp": 1200000,
                    },
                },
            ],
        }
    )

    assert "1. Chery Tiggo 4 — 2026 — مستعملة — 7,500 كم — 930,000 جنيه" in response
    assert "2. Toyota Corolla — 2025 — جديدة — 0 كم — 1,200,000 جنيه" in response


def test_recommendations_omit_unknown_optional_condition_and_mileage() -> None:
    response = render_catalog(
        {
            "type": "recommendations",
            "cars": [
                {
                    "position": 1,
                    "car": {
                        "brand": "Example",
                        "model": "Car",
                        "year": 2024,
                        "condition": None,
                        "mileage_km": None,
                        "price_egp": 500000,
                    },
                }
            ],
        }
    )

    assert response.endswith("1. Example Car — 2024 — 500,000 جنيه")
    assert "None" not in response
