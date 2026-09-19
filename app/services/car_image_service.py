"""Deterministic catalog image lookup backed by the checked-in image manifest."""

from __future__ import annotations

import csv
import os
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import quote

_MANIFEST_PATH = Path(__file__).resolve().parents[2] / "data" / "car_image_manifest.csv"
_DEFAULT_BUCKET = "car-images"


@lru_cache(maxsize=1)
def _manifest_by_source_id() -> dict[str, dict[str, str]]:
    """Load the immutable demo mapping once per process.

    The manifest is keyed by the catalog's stable source_id rather than the
    database autoincrement ID so a catalog re-import does not scramble images.
    """

    if not _MANIFEST_PATH.exists():
        return {}

    with _MANIFEST_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = csv.DictReader(handle)
        return {
            str(row.get("source_id") or "").strip(): dict(row)
            for row in rows
            if str(row.get("source_id") or "").strip()
            and str(row.get("storage_path") or "").strip()
            and str(row.get("status") or "").strip().lower() == "sourced"
        }


def image_metadata_for_source_id(source_id: str | None) -> dict[str, str] | None:
    """Return manifest metadata for one stable catalog source ID."""

    normalized = str(source_id or "").strip()
    if not normalized:
        return None
    row = _manifest_by_source_id().get(normalized)
    return dict(row) if row else None


def public_storage_url(
    storage_path: str | None,
    *,
    supabase_url: str | None = None,
    bucket: str = _DEFAULT_BUCKET,
) -> str | None:
    """Build a public Supabase Storage URL without storing environment-specific hosts."""

    path = str(storage_path or "").strip().replace("\\", "/").lstrip("/")
    base = str(supabase_url or os.getenv("SUPABASE_URL") or "").strip().rstrip("/")
    if not base or not path or ".." in Path(path).parts:
        return None

    encoded_bucket = quote(bucket, safe="")
    encoded_path = "/".join(quote(part, safe="") for part in path.split("/"))
    return f"{base}/storage/v1/object/public/{encoded_bucket}/{encoded_path}"


def image_url_for_source_id(
    source_id: str | None,
    *,
    supabase_url: str | None = None,
) -> str | None:
    metadata = image_metadata_for_source_id(source_id)
    if metadata is None:
        return None
    return public_storage_url(metadata.get("storage_path"), supabase_url=supabase_url)


def image_url_for_car(car: Any, *, supabase_url: str | None = None) -> str | None:
    """Resolve an ORM car or mapping-like object to its public image URL."""

    if isinstance(car, dict):
        source_id = car.get("source_id")
    else:
        source_id = getattr(car, "source_id", None)
    return image_url_for_source_id(source_id, supabase_url=supabase_url)
