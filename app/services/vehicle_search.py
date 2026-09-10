"""Strict ORM-only inventory search for validated agent filters."""

from flask import current_app
from sqlalchemy import func, select

from app.agent.schemas import VehicleFilters, VehicleResult
from app.extensions import db
from app.models.vehicle import Vehicle


class VehicleSearchService:
    def __init__(self, session=None):
        self.session = session or db.session
        self.default_limit = current_app.config["AGENT_VEHICLE_RESULT_LIMIT"]
        self.max_limit = current_app.config["AGENT_MAX_VEHICLE_RESULTS"]

    def search(self, filters: VehicleFilters, *, limit: int | None = None) -> list[VehicleResult]:
        if not isinstance(filters, VehicleFilters):
            raise TypeError("filters must be a validated VehicleFilters instance")
        limit = self.default_limit if limit is None else limit
        if not isinstance(limit, int) or not 1 <= limit <= self.max_limit:
            raise ValueError(f"limit must be between 1 and {self.max_limit}")

        statement = select(Vehicle)
        for values, column in (
            (filters.brands, Vehicle.brand), (filters.models, Vehicle.model),
            (filters.fuel_types, Vehicle.fuel_type),
            (filters.transmission_types, Vehicle.transmission_type),
            (filters.body_types, Vehicle.body_type),
        ):
            if values:
                statement = statement.where(func.lower(column).in_([value.lower() for value in values]))
        if filters.condition:
            statement = statement.where(Vehicle.condition == filters.condition)
        for value, expression in (
            (filters.min_year, Vehicle.year >= filters.min_year if filters.min_year is not None else None),
            (filters.max_year, Vehicle.year <= filters.max_year if filters.max_year is not None else None),
            (filters.min_price_egp, Vehicle.price_egp >= filters.min_price_egp if filters.min_price_egp is not None else None),
            (filters.max_price_egp, Vehicle.price_egp <= filters.max_price_egp if filters.max_price_egp is not None else None),
            (filters.max_kilometers, Vehicle.kilometers <= filters.max_kilometers if filters.max_kilometers is not None else None),
        ):
            if value is not None:
                statement = statement.where(expression)
        statement = statement.order_by(Vehicle.price_egp.asc(), Vehicle.year.desc(), Vehicle.id.asc()).limit(limit)
        return [self._safe_result(vehicle) for vehicle in self.session.scalars(statement).all()]

    @staticmethod
    def _safe_result(vehicle: Vehicle) -> VehicleResult:
        return VehicleResult.model_validate({field: getattr(vehicle, field) for field in VehicleResult.model_fields})
