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


def test_narrow_detail_question_renders_only_requested_verified_fact() -> None:
    response = render_catalog(
        {
            "type": "car_details",
            "requested_fields": ["mileage_km"],
            "car": {
                "brand": "Hyundai",
                "model": "Tucson",
                "year": 2025,
                "condition": "used",
                "price_egp": 1_850_000,
                "transmission": "Automatic",
                "fuel_type": "Gasoline",
                "mileage_km": 15_000,
            },
        }
    )

    assert response == "حسب الكتالوج المسجل، Hyundai Tucson: الممشى 15,000 كم."
    assert "السعر" not in response
    assert "ناقل الحركة" not in response


def test_missing_requested_detail_is_reported_without_invention() -> None:
    response = render_catalog(
        {
            "type": "car_details",
            "requested_fields": ["color"],
            "car": {"brand": "Hyundai", "model": "Tucson", "color": None},
        }
    )

    assert response == "اللون غير مسجل حاليًا لـ Hyundai Tucson في الكتالوج."


def test_comparison_shows_recorded_specs_and_deterministic_differences() -> None:
    response = render_catalog(
        {
            "type": "comparison",
            "positions": [1, 2],
            "cars": [
                {
                    "brand": "BMW",
                    "model": "X6",
                    "year": 2019,
                    "condition": "used",
                    "price_egp": 2_700_000,
                    "body_type": "SUV",
                    "transmission": "Automatic",
                    "fuel_type": "Gasoline",
                    "mileage_km": 140_000,
                    "engine_capacity_cc": 4600,
                    "horsepower": None,
                    "powertrain_type": "ICE",
                    "trim": None,
                },
                {
                    "brand": "BMW",
                    "model": "X6",
                    "year": 2018,
                    "condition": "used",
                    "price_egp": 2_550_000,
                    "body_type": "SUV",
                    "transmission": "Automatic",
                    "fuel_type": "Gasoline",
                    "mileage_km": 190_000,
                    "engine_capacity_cc": 4000,
                    "horsepower": None,
                    "powertrain_type": "ICE",
                    "trim": None,
                },
            ],
        }
    )

    assert "1. BMW X6 — موديل 2019" in response
    assert "2. BMW X6 — موديل 2018" in response
    assert "الحالة: مستعملة" in response
    assert "السعر: 2,700,000 جنيه" in response
    assert "السعر: 2,550,000 جنيه" in response
    assert "الممشى: 140,000 كم" in response
    assert "الممشى: 190,000 كم" in response
    assert "سعة المحرك: 4,600 سي سي" in response
    assert "سعة المحرك: 4,000 سي سي" in response
    assert "أبرز الفروق:" in response
    assert "#1 BMW X6 2019 أحدث بسنة واحدة." in response
    assert "#1 BMW X6 2019 ممشاها أقل بـ 50,000 كم." in response
    assert "#2 BMW X6 2018 أرخص بـ 150,000 جنيه." in response
    assert "سعة المحرك المسجلة في #1 BMW X6 2019 أكبر بـ 600 سي سي." in response
    assert "None" not in response


def test_comparison_does_not_invent_missing_specs() -> None:
    response = render_catalog(
        {
            "type": "comparison",
            "positions": [1, 2],
            "cars": [
                {
                    "brand": "Example",
                    "model": "A",
                    "year": 2024,
                    "condition": "used",
                    "price_egp": 1_000_000,
                    "body_type": "SUV",
                    "transmission": None,
                    "fuel_type": None,
                    "mileage_km": None,
                    "engine_capacity_cc": None,
                    "horsepower": None,
                    "powertrain_type": None,
                    "trim": None,
                },
                {
                    "brand": "Example",
                    "model": "B",
                    "year": 2024,
                    "condition": "used",
                    "price_egp": 900_000,
                    "body_type": "SUV",
                    "transmission": None,
                    "fuel_type": None,
                    "mileage_km": None,
                    "engine_capacity_cc": None,
                    "horsepower": None,
                    "powertrain_type": None,
                    "trim": None,
                },
            ],
        }
    )

    assert "ناقل الحركة:" not in response
    assert "الوقود:" not in response
    assert "الممشى:" not in response
    assert "سعة المحرك:" not in response
    assert "القوة:" not in response
    assert "نظام الدفع:" not in response
    assert "الفئة:" not in response
    assert "#2 Example B 2024 أرخص بـ 100,000 جنيه." in response
    assert "None" not in response
