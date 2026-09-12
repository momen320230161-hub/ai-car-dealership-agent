"""Unit coverage for validated and idempotent catalog import behavior."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.models.car import Car
from app.services.catalog_import_service import (
    CatalogImportError,
    CatalogImportService,
)


def _row(**overrides) -> dict[str, str]:
    values = {name: "" for name in CatalogImportService.COLUMNS}
    values.update(
        {
            "brand": "Toyota",
            "model": "Corolla",
            "year": "2025",
            "condition": "new",
            "price_egp": "1250000.50",
            "body_type": "Sedan",
            "transmission": "Automatic",
            "fuel_type": "Gasoline",
            "source": "unit-import",
            "source_id": "car-1",
            "collected_at": "2026-09-02T21:13:08+00:00",
            "data_quality_status": "clean",
            "data_quality_metadata": '{"source_checked": true}',
            "active": "true",
        }
    )
    values.update(overrides)
    return values


def _write_csv(path: Path, rows: list[dict[str, str]], *, headers=None) -> None:
    fieldnames = list(headers or CatalogImportService.COLUMNS)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def test_import_normalizes_only_blank_new_mileage_and_is_idempotent(db_session, tmp_path):
    path = tmp_path / "catalog.csv"
    _write_csv(
        path,
        [
            _row(source_id="new-blank", mileage_km=""),
            _row(
                source_id="used-blank",
                condition="used",
                year="2022",
                mileage_km="",
                data_quality_metadata="{}",
            ),
        ],
    )
    service = CatalogImportService(db_session)

    first = service.import_file(path)
    new_car = db_session.scalar(select(Car).where(Car.source_id == "new-blank"))
    used_car = db_session.scalar(select(Car).where(Car.source_id == "used-blank"))
    new_id = new_car.id

    assert first.as_dict() | {"errors": []} == {
        "file_rows": 2,
        "inserted": 2,
        "updated": 0,
        "unchanged": 0,
        "rejected": 0,
        "errors": [],
    }
    assert new_car.mileage_km == 0
    assert new_car.data_quality_metadata["mileage_source_was_missing"] is True
    assert (
        new_car.data_quality_metadata["mileage_normalization"]
        == "defaulted_to_zero_for_new_condition"
    )
    assert used_car.mileage_km is None
    assert used_car.engine_capacity_cc is None

    second = service.import_file(path)
    assert second.inserted == 0
    assert second.updated == 0
    assert second.unchanged == 2
    assert db_session.scalar(select(func.count()).select_from(Car)) == 2
    assert db_session.scalar(select(Car.id).where(Car.source_id == "new-blank")) == new_id


def test_import_updates_existing_record_without_replacing_id(db_session, tmp_path):
    path = tmp_path / "catalog.csv"
    _write_csv(path, [_row(mileage_km="0")])
    service = CatalogImportService(db_session)
    service.import_file(path)
    original = db_session.scalar(select(Car).where(Car.source_id == "car-1"))
    original_id = original.id

    _write_csv(path, [_row(mileage_km="0", price_egp="1300000")])
    report = service.import_file(path)

    assert report.updated == 1
    refreshed = db_session.scalar(select(Car).where(Car.source_id == "car-1"))
    assert refreshed.id == original_id
    assert str(refreshed.price_egp) == "1300000.00"


def test_import_reports_bad_json_numbers_required_values_and_file_duplicates(
    db_session, tmp_path
):
    path = tmp_path / "bad.csv"
    _write_csv(
        path,
        [
            _row(source_id="good"),
            _row(source_id="bad-json", data_quality_metadata="{"),
            _row(source_id="bad-year", year="twenty"),
            _row(source_id="blank-brand", brand="  "),
            _row(source_id="good"),
        ],
    )

    report = CatalogImportService(db_session).import_file(path)

    assert report.file_rows == 5
    assert report.inserted == 1
    assert report.rejected == 4
    assert len(report.errors) == 4
    assert any("invalid JSON" in error for error in report.errors)
    assert any("year must be an integer" in error for error in report.errors)
    assert any("required field 'brand'" in error for error in report.errors)
    assert any("duplicate (source, source_id)" in error for error in report.errors)


def test_import_rejects_missing_headers(db_session, tmp_path):
    path = tmp_path / "missing.csv"
    headers = [name for name in CatalogImportService.COLUMNS if name != "source_id"]
    _write_csv(path, [_row()], headers=headers)

    with pytest.raises(CatalogImportError, match="missing headers: source_id"):
        CatalogImportService(db_session).import_file(path)


def test_import_rolls_back_all_database_writes_when_commit_fails(
    db_session, tmp_path, monkeypatch
):
    path = tmp_path / "catalog.csv"
    _write_csv(path, [_row(source_id="rollback")])

    def fail_commit():
        raise RuntimeError("simulated database failure")

    monkeypatch.setattr(db_session, "commit", fail_commit)
    with pytest.raises(CatalogImportError, match="transaction rolled back"):
        CatalogImportService(db_session).import_file(path)

    assert db_session.scalar(select(func.count()).select_from(Car)) == 0


def test_metadata_is_parsed_as_object(db_session, tmp_path):
    path = tmp_path / "catalog.csv"
    metadata = {"quality": "verified", "flags": ["reviewed"]}
    _write_csv(
        path,
        [_row(mileage_km="0", data_quality_metadata=json.dumps(metadata))],
    )

    CatalogImportService(db_session).import_file(path)
    car = db_session.scalar(select(Car))
    assert car.data_quality_metadata == metadata
