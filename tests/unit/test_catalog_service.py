"""Unit tests for deterministic catalog querying and fact-only service output."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.car import Car
from app.repositories.catalog_repository import CatalogRepository
from app.services.catalog_service import CatalogService


def _seed(db_session):
    cars = [
        Car(
            brand="Toyota",
            model="Corolla",
            year=2022,
            condition="used",
            price_egp=Decimal("900000"),
            body_type="Sedan",
            transmission="Automatic",
            fuel_type="Gasoline",
            mileage_km=45000,
            source="catalog-test",
            source_id="toyota-used",
        ),
        Car(
            brand="Toyota",
            model="Corolla",
            year=2025,
            condition="new",
            price_egp=Decimal("1300000"),
            body_type="Sedan",
            transmission="Automatic",
            fuel_type="Gasoline",
            mileage_km=0,
            engine_capacity_cc=1600,
            source="catalog-test",
            source_id="toyota-new",
        ),
        Car(
            brand="Kia",
            model="Sportage",
            year=2024,
            condition="used",
            price_egp=Decimal("1700000"),
            body_type="SUV",
            transmission="Automatic",
            fuel_type="Gasoline",
            mileage_km=20000,
            source="catalog-test",
            source_id="kia-used",
        ),
        Car(
            brand="Hyundai",
            model="Tucson",
            year=2023,
            condition="used",
            price_egp=Decimal("1500000"),
            body_type="SUV",
            transmission="Manual",
            fuel_type="Diesel",
            mileage_km=None,
            source="catalog-test",
            source_id="inactive",
            active=False,
        ),
    ]
    db_session.add_all(cars)
    db_session.commit()
    return cars


def test_repository_supports_all_structured_filters_and_active_default(db_session):
    cars = _seed(db_session)
    repository = CatalogRepository(db_session)

    assert repository.search({"condition": "new"}) == [cars[1]]
    assert repository.search({"brand": "toyota", "model": "COROLLA"}) == [cars[0], cars[1]]
    assert repository.search({"min_year": 2023, "max_year": 2025}) == [cars[1], cars[2]]
    assert repository.search({"min_price": 1_000_000, "max_price": 1_500_000}) == [cars[1]]
    assert repository.search({"body_type": "suv"}) == [cars[2]]
    assert repository.search({"transmission": "manual"}) == []
    assert repository.search({"fuel_type": "diesel"}) == []
    assert repository.search({"condition": "used", "max_mileage": 30_000}) == [cars[2]]
    assert repository.search({}, active_only=False, sort_by="price_desc")[0] == cars[2]


def test_repository_sorting_and_pagination_are_deterministic_and_bounded(db_session):
    cars = _seed(db_session)
    repository = CatalogRepository(db_session)

    assert repository.search(sort_by="price_desc") == [cars[2], cars[1], cars[0]]
    assert repository.search(sort_by="year_desc") == [cars[1], cars[2], cars[0]]
    assert repository.search({"condition": "used"}, sort_by="mileage_asc") == [
        cars[2],
        cars[0],
    ]
    assert repository.search(limit=1, offset=1) == [cars[1]]

    for kwargs in ({"sort_by": "DROP TABLE cars"}, {"limit": 101}, {"offset": -1}):
        with pytest.raises(ValueError):
            repository.search(**kwargs)


def test_catalog_details_comparison_and_recommendations_use_only_recorded_facts(db_session):
    cars = _seed(db_session)
    service = CatalogService(db_session)

    details = service.get_car_details(cars[0].id)
    assert details["price_egp"] == Decimal("900000")
    assert details["engine_capacity_cc"] is None
    assert service.get_car_details(cars[3].id) is None

    comparison = service.compare_cars([cars[0].id, cars[2].id])
    assert comparison["car_ids"] == [cars[0].id, cars[2].id]
    assert comparison["cars"][0]["engine_capacity_cc"] is None
    assert comparison["cars"][0]["horsepower"] is None

    recommendations = service.recommend({"transmission": "automatic"}, limit=3)
    assert recommendations == [cars[1], cars[2], cars[0]]

    with pytest.raises(LookupError):
        service.compare_cars([cars[0].id, cars[3].id])


def test_recommendations_use_budget_ceiling_and_prefer_distinct_models(db_session):
    cars = [
        Car(
            brand="Shineray",
            model="X30",
            year=2026,
            condition="new",
            price_egp=Decimal("580000"),
            body_type="Van",
            transmission="Manual",
            mileage_km=0,
            color="Silver",
            source="catalog-budget-test",
            source_id="x30-silver",
        ),
        Car(
            brand="Shineray",
            model="X30",
            year=2026,
            condition="new",
            price_egp=Decimal("580000"),
            body_type="Van",
            transmission="Manual",
            mileage_km=0,
            color="Gray",
            source="catalog-budget-test",
            source_id="x30-gray",
        ),
        Car(
            brand="Audi",
            model="Q3",
            year=2026,
            condition="new",
            price_egp=Decimal("2500000"),
            body_type="SUV",
            transmission="Automatic",
            mileage_km=0,
            source="catalog-budget-test",
            source_id="q3",
        ),
        Car(
            brand="Skoda",
            model="Superb",
            year=2026,
            condition="new",
            price_egp=Decimal("2450000"),
            body_type="Sedan",
            transmission="Automatic",
            mileage_km=0,
            source="catalog-budget-test",
            source_id="superb",
        ),
        Car(
            brand="Kia",
            model="Sportage",
            year=2025,
            condition="used",
            price_egp=Decimal("2400000"),
            body_type="SUV",
            transmission="Automatic",
            mileage_km=12000,
            source="catalog-budget-test",
            source_id="sportage",
        ),
    ]
    db_session.add_all(cars)
    db_session.commit()

    recommendations = CatalogService(db_session).recommend({"max_price": 2_500_000}, limit=3)

    assert [car.model for car in recommendations] == ["Q3", "Superb", "Sportage"]
    assert [car.price_egp for car in recommendations] == [
        Decimal("2500000"),
        Decimal("2450000"),
        Decimal("2400000"),
    ]
    assert len({(car.brand, car.model) for car in recommendations}) == 3
