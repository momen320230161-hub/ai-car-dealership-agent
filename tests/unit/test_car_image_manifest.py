"""Regression checks for the demo car-image sourcing manifest."""

from __future__ import annotations

import csv
from pathlib import Path

MANIFEST = Path("data/car_image_manifest.csv")
ALLOWED_MATCH_QUALITY = {
    "exact",
    "exact_model_year",
    "exact_model_different_color",
    "same_generation",
    "closest_reference",
}


def _rows() -> list[dict[str, str]]:
    with MANIFEST.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def test_car_image_manifest_covers_all_demo_catalog_rows() -> None:
    rows = _rows()

    assert len(rows) == 100
    assert {int(row["row_no"]) for row in rows} == set(range(1, 101))
    assert len({row["source_id"] for row in rows}) == 100


def test_car_image_manifest_is_fully_sourced_and_storage_paths_are_safe() -> None:
    rows = _rows()
    storage_paths = [row["storage_path"] for row in rows]

    assert len(storage_paths) == len(set(storage_paths))

    for row in rows:
        assert row["status"] == "sourced"
        assert row["image_source"]
        assert row["image_source_page"].startswith(("http://", "https://"))
        assert row["image_source_url"].startswith(("http://", "https://"))
        assert row["image_display_color"]
        assert row["match_quality"] in ALLOWED_MATCH_QUALITY
        assert row["storage_path"].endswith(".webp")
        assert not row["storage_path"].startswith("/")
        assert ".." not in Path(row["storage_path"]).parts
