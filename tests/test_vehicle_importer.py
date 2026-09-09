import csv

import pytest

from app.extensions import db
from app.models import Vehicle
from app.services.vehicle_importer import VehicleImportValidationError, import_vehicles, validate_vehicle_csv


HEADERS = ["brand", "model", "year", "condition", "price_egp", "kilometers", "fuel_type", "transmission_type", "engine_capacity_cc", "body_type", "trim", "horsepower", "color", "source", "source_url", "source_id", "collected_at", "data_quality_status", "powertrain_type"]


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(rows)


def row(**overrides):
    value = {key: "" for key in HEADERS}
    value.update({"brand": "Ford", "model": "Focus", "year": "2020", "condition": "new", "price_egp": "750000", "transmission_type": "Automatic", "source": "fixture", "source_id": "source-1", "data_quality_status": "clean", "powertrain_type": "BEV"})
    value.update(overrides)
    return value


def test_import_is_idempotent_and_updates_existing_row(app, tmp_path):
    path = tmp_path / "vehicles.csv"
    write_csv(path, [row()])
    first = import_vehicles(path)
    assert (first.inserted, first.updated) == (1, 0)
    write_csv(path, [row(price_egp="800000")])
    second = import_vehicles(path)
    assert (second.inserted, second.updated) == (0, 1)
    assert db.session.scalar(db.select(Vehicle.price_egp)) == 800000


def test_import_validation_rejects_duplicate_and_arabic_canonical_values(app, tmp_path):
    duplicate = tmp_path / "duplicate.csv"
    write_csv(duplicate, [row(), row()])
    with pytest.raises(VehicleImportValidationError):
        validate_vehicle_csv(duplicate)

    arabic = tmp_path / "arabic.csv"
    write_csv(arabic, [row(brand="فورد")])
    with pytest.raises(VehicleImportValidationError):
        import_vehicles(arabic)
    assert db.session.scalar(db.select(db.func.count()).select_from(Vehicle)) == 0


def test_malformed_file_never_changes_existing_data(app, tmp_path):
    valid = tmp_path / "valid.csv"
    write_csv(valid, [row()])
    import_vehicles(valid)

    invalid = tmp_path / "invalid.csv"
    write_csv(invalid, [row(source_id="source-2", price_egp="-10")])
    with pytest.raises(VehicleImportValidationError):
        import_vehicles(invalid)

    assert db.session.scalar(db.select(db.func.count()).select_from(Vehicle)) == 1
