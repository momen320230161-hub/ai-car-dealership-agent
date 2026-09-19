"""Validation and repair for persisted business-action drafts."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date
from typing import Any


def sanitize_pending_action(
    pending: Mapping[str, Any] | None,
    *,
    car_is_active: Callable[[int], bool],
    today: date,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Remove only stale facts while preserving the customer's unfinished draft."""
    sanitized = dict(pending or {})
    fields = dict(sanitized.get("fields") or {})
    changes: list[str] = []

    if sanitized.get("type") in {"test_drive", "sales_lead"}:
        car_id = fields.get("car_id")
        try:
            resolved_car_id = int(car_id) if car_id is not None else None
        except (TypeError, ValueError):
            resolved_car_id = None
        if car_id is not None and (
            resolved_car_id is None or not car_is_active(resolved_car_id)
        ):
            fields.pop("car_id", None)
            changes.append("invalid_car_id")

    if sanitized.get("type") == "test_drive" and fields.get("preferred_date"):
        try:
            preferred_date = date.fromisoformat(str(fields["preferred_date"]))
        except ValueError:
            preferred_date = None
        if preferred_date is None or preferred_date < today:
            fields.pop("preferred_date", None)
            fields.pop("preferred_time", None)
            changes.append("expired_preferred_date")

    sanitized["fields"] = fields
    return sanitized, tuple(changes)
