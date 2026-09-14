"""Deterministic ORM queries for the structured vehicle catalog."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import Select, case, func, select
from sqlalchemy.orm import Session

from app.domain.catalog_filters import CatalogFilters
from app.models.car import Car


class CatalogRepository:
    """Focused query access for cars without business-workflow concerns."""

    MAX_PAGE_SIZE = 100
    SORTS = {
        "price_asc",
        "price_desc",
        "year_desc",
        "year_desc_mileage_asc",
        "mileage_asc",
    }
    FACET_COLUMNS = {
        "brand": Car.brand,
        "body_type": Car.body_type,
        "transmission": Car.transmission,
        "fuel_type": Car.fuel_type,
    }

    def __init__(self, session: Session):
        self.session = session

    def get(self, car_id: int, *, active_only: bool = True) -> Car | None:
        statement = select(Car).where(Car.id == car_id)
        if active_only:
            statement = statement.where(Car.active.is_(True))
        return self.session.scalar(statement)

    def get_many(self, car_ids: Sequence[int], *, active_only: bool = True) -> list[Car]:
        """Return exact requested IDs in the caller's order, omitting missing rows."""
        if not car_ids:
            return []
        statement = select(Car).where(Car.id.in_(set(car_ids)))
        if active_only:
            statement = statement.where(Car.active.is_(True))
        by_id = {car.id: car for car in self.session.scalars(statement)}
        return [by_id[car_id] for car_id in car_ids if car_id in by_id]

    def search(
        self,
        filters: CatalogFilters | Mapping[str, Any] | None = None,
        *,
        sort_by: str = "price_asc",
        limit: int = 20,
        offset: int = 0,
        active_only: bool = True,
    ) -> list[Car]:
        """Search with validated filters, allowlisted ordering, and bounded pagination."""
        catalog_filters = self._validated_filters(filters)
        if sort_by not in self.SORTS:
            raise ValueError(f"Unsupported catalog sort: {sort_by}")
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= self.MAX_PAGE_SIZE
        ):
            raise ValueError(f"limit must be between 1 and {self.MAX_PAGE_SIZE}")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be a non-negative integer")

        statement = self._apply_filters(select(Car), catalog_filters, active_only=active_only)
        statement = statement.order_by(*self._sort_columns(sort_by)).limit(limit).offset(offset)
        return list(self.session.scalars(statement))

    def count(
        self,
        filters: CatalogFilters | Mapping[str, Any] | None = None,
        *,
        active_only: bool = True,
    ) -> int:
        """Count rows using exactly the same structured filters as ``search``."""
        catalog_filters = self._validated_filters(filters)
        statement = self._apply_filters(
            select(func.count(Car.id)),
            catalog_filters,
            active_only=active_only,
        )
        return int(self.session.scalar(statement) or 0)

    def facet_values(
        self,
        field_name: str,
        *,
        active_only: bool = True,
        limit: int = 100,
    ) -> list[str]:
        """Return bounded distinct values for allowlisted customer filter controls."""
        column = self.FACET_COLUMNS.get(field_name)
        if column is None:
            raise ValueError(f"Unsupported catalog facet: {field_name}")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise ValueError("facet limit must be between 1 and 200")

        statement = select(column).where(
            column.is_not(None),
            func.length(func.trim(column)) > 0,
        )
        if active_only:
            statement = statement.where(Car.active.is_(True))
        statement = statement.distinct().order_by(column.asc()).limit(limit)
        return [str(value) for value in self.session.scalars(statement) if value is not None]

    @staticmethod
    def _validated_filters(
        filters: CatalogFilters | Mapping[str, Any] | None,
    ) -> CatalogFilters:
        return (
            filters if isinstance(filters, CatalogFilters) else CatalogFilters.from_mapping(filters)
        )

    @staticmethod
    def _apply_filters(
        statement: Select,
        filters: CatalogFilters,
        *,
        active_only: bool,
    ) -> Select:
        if active_only:
            statement = statement.where(Car.active.is_(True))
        if filters.condition:
            statement = statement.where(Car.condition == filters.condition)
        for name in ("brand", "model", "body_type", "transmission", "fuel_type"):
            value = getattr(filters, name)
            if value:
                statement = statement.where(func.lower(getattr(Car, name)) == value.casefold())
        if filters.min_year is not None:
            statement = statement.where(Car.year >= filters.min_year)
        if filters.max_year is not None:
            statement = statement.where(Car.year <= filters.max_year)
        if filters.min_price is not None:
            statement = statement.where(Car.price_egp >= filters.min_price)
        if filters.max_price is not None:
            statement = statement.where(Car.price_egp <= filters.max_price)
        if filters.max_mileage is not None:
            statement = statement.where(
                Car.mileage_km.is_not(None), Car.mileage_km <= filters.max_mileage
            )
        return statement

    @staticmethod
    def _sort_columns(sort_by: str) -> tuple:
        if sort_by == "price_asc":
            return (Car.price_egp.asc(), Car.year.desc(), Car.id.asc())
        if sort_by == "price_desc":
            return (Car.price_egp.desc(), Car.year.desc(), Car.id.asc())
        if sort_by == "year_desc":
            return (Car.year.desc(), Car.price_egp.asc(), Car.id.asc())
        if sort_by == "year_desc_mileage_asc":
            return (
                Car.year.desc(),
                case((Car.mileage_km.is_(None), 1), else_=0).asc(),
                Car.mileage_km.asc(),
                Car.price_egp.asc(),
                Car.id.asc(),
            )
        # NULL mileage stays after known USED mileage.
        return (
            case((Car.mileage_km.is_(None), 1), else_=0).asc(),
            Car.mileage_km.asc(),
            Car.price_egp.asc(),
            Car.id.asc(),
        )
