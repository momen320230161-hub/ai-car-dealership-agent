"""Validated, idempotent import of the authoritative Phase 2 vehicle catalog."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.car import Car


class CatalogImportError(RuntimeError):
    """Raised for file-level or transactional import failures."""


@dataclass(slots=True)
class ImportReport:
    file_rows: int = 0
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    rejected: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class CatalogImportService:
    """Parse the official CSV completely, then atomically insert/update valid rows."""

    COLUMNS = (
        "brand",
        "model",
        "year",
        "condition",
        "price_egp",
        "body_type",
        "transmission",
        "fuel_type",
        "mileage_km",
        "engine_capacity_cc",
        "horsepower",
        "powertrain_type",
        "trim",
        "color",
        "location",
        "vin",
        "stock_number",
        "source",
        "source_url",
        "source_id",
        "collected_at",
        "data_quality_status",
        "data_quality_metadata",
        "active",
    )
    REQUIRED_VALUES = ("brand", "model", "year", "condition", "price_egp", "source", "source_id")
    OPTIONAL_TEXT = (
        "body_type",
        "transmission",
        "fuel_type",
        "powertrain_type",
        "trim",
        "color",
        "location",
        "vin",
        "stock_number",
        "source_url",
        "data_quality_status",
    )
    IMPORT_FIELDS = tuple(name for name in COLUMNS if name not in {"data_quality_metadata"}) + (
        "data_quality_metadata",
    )

    def __init__(self, session: Session):
        self.session = session

    def import_file(self, path: str | Path) -> ImportReport:
        csv_path = Path(path)
        if not csv_path.is_file():
            raise CatalogImportError(f"Catalog file does not exist: {csv_path}")

        report = ImportReport()
        parsed_rows: list[dict[str, Any]] = []
        seen_identities: set[tuple[str, str]] = set()
        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            self._validate_headers(reader.fieldnames)
            for line_no, raw in enumerate(reader, start=2):
                report.file_rows += 1
                try:
                    values = self._parse_row(raw)
                    identity = (values["source"], values["source_id"])
                    if identity in seen_identities:
                        raise ValueError("duplicate (source, source_id) within import file")
                    seen_identities.add(identity)
                    parsed_rows.append(values)
                except (TypeError, ValueError) as exc:
                    report.rejected += 1
                    report.errors.append(f"row {line_no}: {exc}")

        try:
            existing = {
                (car.source, car.source_id): car
                for car in self.session.scalars(select(Car)).all()
            }
            for values in parsed_rows:
                identity = (values["source"], values["source_id"])
                car = existing.get(identity)
                if car is None:
                    car = Car(**values)
                    self.session.add(car)
                    existing[identity] = car
                    report.inserted += 1
                elif self._update_if_changed(car, values):
                    report.updated += 1
                else:
                    report.unchanged += 1
            self.session.commit()
        except Exception as exc:
            self.session.rollback()
            raise CatalogImportError("Catalog import transaction rolled back") from exc
        return report

    @classmethod
    def _validate_headers(cls, headers: list[str] | None) -> None:
        if headers is None:
            raise CatalogImportError("Catalog CSV has no header row")
        missing = set(cls.COLUMNS) - set(headers)
        if missing:
            names = ", ".join(sorted(missing))
            raise CatalogImportError(f"Catalog CSV is missing headers: {names}")

    @classmethod
    def _parse_row(cls, raw: dict[str, str | None]) -> dict[str, Any]:
        for name in cls.REQUIRED_VALUES:
            if not cls._text(raw.get(name)):
                raise ValueError(f"required field {name!r} is blank")

        condition = cls._text(raw.get("condition")).lower()
        if condition not in {"new", "used"}:
            raise ValueError("condition must be 'new' or 'used'")

        metadata_text = cls._text(raw.get("data_quality_metadata"))
        try:
            metadata = json.loads(metadata_text) if metadata_text else {}
        except json.JSONDecodeError as exc:
            raise ValueError(f"data_quality_metadata is invalid JSON: {exc.msg}") from exc
        if not isinstance(metadata, dict):
            raise ValueError("data_quality_metadata must be a JSON object")

        mileage = cls._optional_int(raw.get("mileage_km"), "mileage_km", minimum=0)
        if condition == "new" and mileage is None:
            mileage = 0
            metadata = dict(metadata)
            metadata.update(
                {
                    "mileage_normalization": "defaulted_to_zero_for_new_condition",
                    "mileage_source_was_missing": True,
                }
            )

        values: dict[str, Any] = {
            "brand": cls._text(raw.get("brand")),
            "model": cls._text(raw.get("model")),
            "year": cls._required_int(raw.get("year"), "year", minimum=1900),
            "condition": condition,
            "price_egp": cls._required_decimal(raw.get("price_egp"), "price_egp", minimum=0),
            "mileage_km": mileage,
            "engine_capacity_cc": cls._optional_int(
                raw.get("engine_capacity_cc"), "engine_capacity_cc", minimum=1
            ),
            "horsepower": cls._optional_decimal(raw.get("horsepower"), "horsepower", minimum=0),
            "source": cls._text(raw.get("source")),
            "source_id": cls._text(raw.get("source_id")),
            "collected_at": cls._optional_datetime(raw.get("collected_at")),
            "data_quality_metadata": metadata,
            "active": cls._required_bool(raw.get("active")),
        }
        values.update({name: cls._optional_text(raw.get(name)) for name in cls.OPTIONAL_TEXT})
        return values

    @staticmethod
    def _text(value: str | None) -> str:
        return "" if value is None else value.strip()

    @classmethod
    def _optional_text(cls, value: str | None) -> str | None:
        return cls._text(value) or None

    @classmethod
    def _required_int(cls, value: str | None, name: str, *, minimum: int) -> int:
        parsed = cls._optional_int(value, name, minimum=minimum)
        if parsed is None:
            raise ValueError(f"required field {name!r} is blank")
        return parsed

    @classmethod
    def _optional_int(cls, value: str | None, name: str, *, minimum: int) -> int | None:
        text = cls._text(value)
        if not text:
            return None
        try:
            parsed = int(text)
        except ValueError as exc:
            raise ValueError(f"{name} must be an integer") from exc
        if parsed < minimum:
            raise ValueError(f"{name} must be at least {minimum}")
        return parsed

    @classmethod
    def _required_decimal(
        cls, value: str | None, name: str, *, minimum: int
    ) -> Decimal:
        parsed = cls._optional_decimal(value, name, minimum=minimum)
        if parsed is None:
            raise ValueError(f"required field {name!r} is blank")
        return parsed

    @classmethod
    def _optional_decimal(
        cls, value: str | None, name: str, *, minimum: int
    ) -> Decimal | None:
        text = cls._text(value)
        if not text:
            return None
        try:
            parsed = Decimal(text)
        except InvalidOperation as exc:
            raise ValueError(f"{name} must be numeric") from exc
        if not parsed.is_finite() or parsed < minimum:
            raise ValueError(f"{name} must be a finite value of at least {minimum}")
        return parsed

    @classmethod
    def _optional_datetime(cls, value: str | None) -> datetime | None:
        text = cls._text(value)
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("collected_at must be an ISO-8601 datetime") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("collected_at must include a timezone")
        return parsed

    @classmethod
    def _required_bool(cls, value: str | None) -> bool:
        normalized = cls._text(value).lower()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
        raise ValueError("active must be a boolean")

    @classmethod
    def _update_if_changed(cls, car: Car, values: dict[str, Any]) -> bool:
        changed = False
        for name, value in values.items():
            current = getattr(car, name)
            if isinstance(value, datetime):
                current = cls._utc_datetime(current)
                value = cls._utc_datetime(value)
            if current != value:
                setattr(car, name, value)
                changed = True
        return changed

    @staticmethod
    def _utc_datetime(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
