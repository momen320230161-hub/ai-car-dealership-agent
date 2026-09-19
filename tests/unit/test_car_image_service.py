"""Tests for deterministic Supabase catalog image resolution."""

from __future__ import annotations

import csv
from pathlib import Path

from app.services.car_image_service import (
    image_metadata_for_source_id,
    image_url_for_car,
    image_url_for_source_id,
    public_storage_url,
)

MANIFEST = Path("data/car_image_manifest.csv")


def _manifest_rows() -> list[dict[str, str]]:
    with MANIFEST.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def test_every_demo_catalog_row_resolves_to_public_storage_url() -> None:
    rows = _manifest_rows()

    assert len(rows) == 100
    for row in rows:
        metadata = image_metadata_for_source_id(row["source_id"])
        assert metadata is not None
        assert metadata["storage_path"] == row["storage_path"]

        url = image_url_for_source_id(
            row["source_id"],
            supabase_url="https://example.supabase.co",
        )
        assert url == (
            "https://example.supabase.co/storage/v1/object/public/"
            f"car-images/{row['storage_path']}"
        )


def test_missing_source_id_keeps_ui_fallback_available() -> None:
    assert image_metadata_for_source_id("not-a-real-source-id") is None
    assert (
        image_url_for_source_id(
            "not-a-real-source-id",
            supabase_url="https://example.supabase.co",
        )
        is None
    )


def test_storage_url_rejects_unsafe_paths() -> None:
    assert (
        public_storage_url(
            "../secret.webp",
            supabase_url="https://example.supabase.co",
        )
        is None
    )


def test_admin_uploaded_image_path_takes_priority_over_manifest() -> None:
    url = image_url_for_car(
        {"source_id": "missing", "image_storage_path": "admin/42/photo.webp"},
        supabase_url="https://example.supabase.co",
    )

    assert url == (
        "https://example.supabase.co/storage/v1/object/public/"
        "car-images/admin/42/photo.webp"
    )
