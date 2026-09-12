"""Validated structured filters used by catalog queries and preference state."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields
from decimal import Decimal, InvalidOperation
from typing import Any


@dataclass(frozen=True, slots=True)
class CatalogFilters:
    """The deliberately small, structured Phase 2 catalog filter set."""

    condition: str | None = None
    brand: str | None = None
    model: str | None = None
    min_year: int | None = None
    max_year: int | None = None
    min_price: Decimal | None = None
    max_price: Decimal | None = None
    body_type: str | None = None
    transmission: str | None = None
    fuel_type: str | None = None
    max_mileage: int | None = None

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any] | None) -> CatalogFilters:
        """Build validated filters without accepting arbitrary fields."""
        if not values:
            return cls()

        allowed = {field.name for field in fields(cls)}
        unknown = set(values) - allowed
        if unknown:
            names = ", ".join(sorted(unknown))
            raise ValueError(f"Unsupported catalog filters: {names}")

        normalized: dict[str, Any] = {}
        for name, value in values.items():
            if value is None or (isinstance(value, str) and not value.strip()):
                continue
            if name in {"condition", "brand", "model", "body_type", "transmission", "fuel_type"}:
                normalized[name] = str(value).strip()
            elif name in {"min_year", "max_year", "max_mileage"}:
                try:
                    normalized[name] = int(value)
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"{name} must be an integer") from exc
                if normalized[name] < 0:
                    raise ValueError(f"{name} must not be negative")
            else:
                try:
                    normalized[name] = Decimal(str(value))
                except (InvalidOperation, TypeError, ValueError) as exc:
                    raise ValueError(f"{name} must be numeric") from exc
                if normalized[name] < 0:
                    raise ValueError(f"{name} must not be negative")

        condition = normalized.get("condition")
        if condition is not None:
            condition = condition.lower()
            if condition not in {"new", "used"}:
                raise ValueError("condition must be 'new' or 'used'")
            normalized["condition"] = condition

        if normalized.get("min_year", 0) > normalized.get("max_year", 9999):
            raise ValueError("min_year must not exceed max_year")
        if normalized.get("min_price", Decimal(0)) > normalized.get(
            "max_price", Decimal("999999999999")
        ):
            raise ValueError("min_price must not exceed max_price")
        return cls(**normalized)

    def as_dict(self) -> dict[str, Any]:
        """Return JSON-safe non-null criteria for snapshot persistence."""
        result: dict[str, Any] = {}
        for field in fields(self):
            value = getattr(self, field.name)
            if value is None:
                continue
            result[field.name] = float(value) if isinstance(value, Decimal) else value
        return result
