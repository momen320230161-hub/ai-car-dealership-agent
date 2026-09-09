"""Validation-first, idempotent import of the approved vehicle dataset."""

import csv
import json
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert

from app.extensions import db
from app.models.vehicle import Vehicle


EXPECTED_COLUMNS = {
    "brand", "model", "year", "condition", "price_egp", "kilometers", "fuel_type",
    "transmission_type", "engine_capacity_cc", "body_type", "trim", "horsepower", "color",
    "source", "source_url", "source_id", "collected_at", "data_quality_status", "powertrain_type",
}
CANONICAL_COLUMNS = {
    "brand", "model", "year", "condition", "price_egp", "kilometers", "fuel_type",
    "transmission_type", "engine_capacity_cc", "body_type", "trim", "horsepower", "color",
    "powertrain_type", "source", "source_url", "source_id", "collected_at", "data_quality_status",
}
ARABIC_RE = re.compile(r"[\u0600-\u06FF]")


class VehicleImportValidationError(ValueError):
    """Raised before any write when the CSV cannot be safely imported."""


@dataclass(frozen=True)
class ImportResult:
    attempted: int
    inserted: int
    updated: int
    skipped: int
    rejected: int


def _text(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def _integer(value: str | None, field: str, row_number: int, *, required: bool = False) -> int | None:
    value = _text(value)
    if value is None:
        if required:
            raise VehicleImportValidationError(f"row {row_number}: {field} is required")
        return None
    try:
        decimal = Decimal(value)
    except InvalidOperation as error:
        raise VehicleImportValidationError(f"row {row_number}: {field} is not numeric") from error
    if decimal != decimal.to_integral_value():
        raise VehicleImportValidationError(f"row {row_number}: {field} must be a whole number")
    return int(decimal)


def _decimal(value: str | None, field: str, row_number: int) -> Decimal | None:
    value = _text(value)
    if value is None:
        return None
    try:
        return Decimal(value)
    except InvalidOperation as error:
        raise VehicleImportValidationError(f"row {row_number}: {field} is not numeric") from error


def _timestamp(value: str | None, row_number: int) -> datetime | None:
    value = _text(value)
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise VehicleImportValidationError(f"row {row_number}: collected_at is invalid") from error


def _metadata(row: dict[str, str]) -> dict[str, str]:
    # Every non-canonical source field is retained as provenance/audit metadata.
    return {key: value for key, value in row.items() if key not in CANONICAL_COLUMNS and _text(value) is not None}


def _vehicle_values(row: dict[str, str], row_number: int) -> dict:
    brand, model = _text(row.get("brand")), _text(row.get("model"))
    source_id, source = _text(row.get("source_id")), _text(row.get("source"))
    condition = _text(row.get("condition"))
    transmission_type = _text(row.get("transmission_type"))
    if not brand or not model or not source_id or not source or not condition or not transmission_type:
        raise VehicleImportValidationError(f"row {row_number}: required production field is missing")
    if ARABIC_RE.search(brand) or ARABIC_RE.search(model):
        raise VehicleImportValidationError(f"row {row_number}: canonical brand/model contains Arabic script")
    if condition not in {"new", "used"}:
        raise VehicleImportValidationError(f"row {row_number}: invalid condition")
    year = _integer(row.get("year"), "year", row_number, required=True)
    price = _integer(row.get("price_egp"), "price_egp", row_number, required=True)
    kilometers = _integer(row.get("kilometers"), "kilometers", row_number)
    engine = _integer(row.get("engine_capacity_cc"), "engine_capacity_cc", row_number)
    horsepower = _decimal(row.get("horsepower"), "horsepower", row_number)
    if not 1900 <= year <= 2100 or price < 0 or (kilometers is not None and kilometers < 0):
        raise VehicleImportValidationError(f"row {row_number}: numeric range is invalid")
    if engine is not None and engine <= 0 or horsepower is not None and horsepower <= 0:
        raise VehicleImportValidationError(f"row {row_number}: engine capacity/horsepower must be positive")
    return {
        "brand": brand, "model": model, "year": year, "condition": condition, "price_egp": price,
        "kilometers": kilometers, "fuel_type": _text(row.get("fuel_type")), "transmission_type": transmission_type,
        "engine_capacity_cc": engine, "body_type": _text(row.get("body_type")), "trim": _text(row.get("trim")),
        "horsepower": horsepower, "color": _text(row.get("color")), "powertrain_type": _text(row.get("powertrain_type")),
        "source": source, "source_url": _text(row.get("source_url")), "source_id": source_id,
        "collected_at": _timestamp(row.get("collected_at"), row_number),
        "data_quality_status": _text(row.get("data_quality_status")) or "unknown",
        "data_quality_metadata": _metadata(row),
    }


def validate_vehicle_csv(csv_path: Path) -> list[dict]:
    """Load and validate the entire file before the database transaction begins."""
    if not csv_path.is_file():
        raise VehicleImportValidationError(f"CSV does not exist: {csv_path}")
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = set(reader.fieldnames or [])
        missing = EXPECTED_COLUMNS - headers
        if missing:
            raise VehicleImportValidationError(f"CSV missing required columns: {', '.join(sorted(missing))}")
        values, source_ids = [], set()
        for row_number, row in enumerate(reader, start=2):
            value = _vehicle_values(row, row_number)
            if value["source_id"] in source_ids:
                raise VehicleImportValidationError(f"row {row_number}: duplicate source_id")
            source_ids.add(value["source_id"])
            values.append(value)
    if not values:
        raise VehicleImportValidationError("CSV has no vehicle rows")
    return values


def import_vehicles(csv_path: Path) -> ImportResult:
    """Insert new vehicles and update existing source IDs atomically."""
    values = validate_vehicle_csv(csv_path)
    source_ids = [value["source_id"] for value in values]
    existing = {
        vehicle.source_id: vehicle
        for vehicle in db.session.scalars(select(Vehicle).where(Vehicle.source_id.in_(source_ids)))
    }
    inserted = updated = 0
    try:
        inserted = sum(value["source_id"] not in existing for value in values)
        updated = len(values) - inserted
        if db.engine.dialect.name == "postgresql":
            # Bounded PostgreSQL upserts keep the production import fast while
            # retaining source_id as the single import identity.
            for offset in range(0, len(values), 500):
                chunk = values[offset : offset + 500]
                statement = postgresql_insert(Vehicle).values(chunk)
                update_values = {
                    key: getattr(statement.excluded, key)
                    for key in chunk[0]
                    if key != "source_id"
                }
                update_values["updated_at"] = func.now()
                db.session.execute(
                    statement.on_conflict_do_update(
                        index_elements=[Vehicle.source_id], set_=update_values
                    )
                )
        else:
            for value in values:
                vehicle = existing.get(value["source_id"])
                if vehicle is None:
                    db.session.add(Vehicle(**value))
                else:
                    for key, item in value.items():
                        setattr(vehicle, key, item)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return ImportResult(len(values), inserted, updated, 0, 0)
