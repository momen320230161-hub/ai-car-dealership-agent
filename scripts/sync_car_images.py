"""Download, normalize, and optionally upload catalog car images to Supabase Storage.

This is an assessment/demo asset pipeline. It reads data/car_image_manifest.csv,
downloads each mapped source image, converts it to bounded WebP, and uploads it
under the deterministic storage_path recorded in the manifest.

Usage:
    uv run --with pillow python scripts/sync_car_images.py --download-only
    uv run --with pillow python scripts/sync_car_images.py --upload
    uv run --with pillow python scripts/sync_car_images.py --upload --missing-only
    uv run --with pillow python scripts/sync_car_images.py --upload --limit 10

Required for upload:
    SUPABASE_URL
    SUPABASE_SECRET_KEY (preferred) or SUPABASE_SERVICE_ROLE_KEY

Never expose the secret key to browser code.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import io
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import httpx
from dotenv import load_dotenv
from PIL import Image, ImageOps, UnidentifiedImageError

DEFAULT_MANIFEST = Path("data/car_image_manifest.csv")
DEFAULT_OUTPUT_DIR = Path(".artifacts/car-images")
DEFAULT_BUCKET = "car-images"
DEFAULT_MAX_WIDTH = 1400
DEFAULT_MAX_HEIGHT = 900
DEFAULT_WEBP_QUALITY = 82
MAX_SOURCE_BYTES = 20 * 1024 * 1024

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0 Safari/537.36 AutoDriveImageSync/1.0"
)


@dataclass(frozen=True, slots=True)
class ImageManifestRow:
    row_no: int
    source_id: str
    brand: str
    model: str
    year: int
    image_source_url: str
    image_source_page: str
    image_display_color: str
    match_quality: str
    storage_path: str
    status: str

    @classmethod
    def from_dict(cls, value: dict[str, str]) -> ImageManifestRow:
        return cls(
            row_no=int(value["row_no"]),
            source_id=value["source_id"].strip(),
            brand=value["brand"].strip(),
            model=value["model"].strip(),
            year=int(value["year"]),
            image_source_url=value["image_source_url"].strip(),
            image_source_page=value["image_source_page"].strip(),
            image_display_color=value["image_display_color"].strip(),
            match_quality=value["match_quality"].strip(),
            storage_path=_safe_storage_path(value["storage_path"]),
            status=value["status"].strip(),
        )


@dataclass(frozen=True, slots=True)
class SyncResult:
    row_no: int
    storage_path: str
    local_path: Path | None
    uploaded: bool
    error: str | None


def _safe_storage_path(value: str) -> str:
    path = value.strip().replace("\\", "/").lstrip("/")
    if not path or ".." in Path(path).parts:
        raise ValueError(f"Unsafe storage path: {value!r}")
    if not path.lower().endswith(".webp"):
        raise ValueError(f"Storage path must end in .webp: {path!r}")
    return path


def _load_manifest(path: Path) -> list[ImageManifestRow]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = [ImageManifestRow.from_dict(row) for row in csv.DictReader(handle)]
    if not rows:
        raise ValueError(f"No image rows found in {path}")

    row_numbers = [row.row_no for row in rows]
    if len(row_numbers) != len(set(row_numbers)):
        raise ValueError("Manifest contains duplicate row_no values")

    storage_paths = [row.storage_path for row in rows]
    if len(storage_paths) != len(set(storage_paths)):
        raise ValueError("Manifest contains duplicate storage_path values")

    return rows


def _source_cache_path(cache_dir: Path, source_url: str) -> Path:
    digest = hashlib.sha256(source_url.encode("utf-8")).hexdigest()
    return cache_dir / f"{digest}.source"


def _validate_image_response(response: httpx.Response) -> bytes:
    response.raise_for_status()
    content = response.content
    if not content:
        raise ValueError("Downloaded image is empty")
    if len(content) > MAX_SOURCE_BYTES:
        raise ValueError(
            f"Source image exceeds {MAX_SOURCE_BYTES // (1024 * 1024)} MB safety limit"
        )

    content_type = response.headers.get("content-type", "").lower()
    if content_type and "image" not in content_type:
        raise ValueError(f"Source returned non-image content type: {content_type}")
    return content


def _fetch_image(
    client: httpx.Client,
    image_url: str,
    *,
    referer: str | None = None,
) -> bytes:
    headers = {}
    if referer:
        headers["Referer"] = referer
    response = client.get(image_url, headers=headers)
    return _validate_image_response(response)


def _extract_page_image_url(page_html: str) -> str | None:
    patterns = (
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
        r'<meta[^>]+name=["\']twitter:image(?::src)?["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image(?::src)?["\']',
    )
    for pattern in patterns:
        match = re.search(pattern, page_html, flags=re.IGNORECASE)
        if match:
            return html.unescape(match.group(1).strip())
    return None


def _download_source(
    client: httpx.Client,
    source_url: str,
    *,
    source_page: str,
    cache_dir: Path,
    force: bool,
) -> bytes:
    cache_path = _source_cache_path(cache_dir, source_url)
    if cache_path.exists() and not force:
        return cache_path.read_bytes()

    first_error: Exception | None = None
    try:
        content = _fetch_image(client, source_url, referer=source_page or None)
    except (httpx.HTTPError, ValueError) as exc:
        first_error = exc
        if not source_page:
            raise

        page_response = client.get(
            source_page,
            headers={"Referer": source_page},
        )
        page_response.raise_for_status()
        candidate = _extract_page_image_url(page_response.text)
        if not candidate:
            raise first_error from None

        content = _fetch_image(client, candidate, referer=source_page)

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(content)
    return content


def _normalize_to_webp(
    source_bytes: bytes,
    *,
    max_width: int,
    max_height: int,
    quality: int,
) -> bytes:
    try:
        with Image.open(io.BytesIO(source_bytes)) as source:
            image = ImageOps.exif_transpose(source)
            if image.mode not in {"RGB", "RGBA"}:
                image = image.convert("RGB")
            elif image.mode == "RGBA":
                background = Image.new("RGB", image.size, "white")
                background.paste(image, mask=image.getchannel("A"))
                image = background
            else:
                image = image.copy()

            image.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            image.save(
                output,
                format="WEBP",
                quality=quality,
                method=6,
                optimize=True,
            )
            return output.getvalue()
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("Downloaded file could not be decoded as an image") from exc


def _write_local(output_dir: Path, storage_path: str, webp_bytes: bytes) -> Path:
    target = output_dir / storage_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(webp_bytes)
    return target


def _supabase_secret() -> str:
    return (
        os.getenv("SUPABASE_SECRET_KEY", "").strip()
        or os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    )


def _upload_to_supabase(
    client: httpx.Client,
    *,
    supabase_url: str,
    secret_key: str,
    bucket: str,
    storage_path: str,
    webp_bytes: bytes,
) -> None:
    encoded_path = "/".join(quote(part, safe="") for part in storage_path.split("/"))
    endpoint = (
        f"{supabase_url.rstrip('/')}/storage/v1/object/"
        f"{quote(bucket, safe='')}/{encoded_path}"
    )
    response = client.post(
        endpoint,
        content=webp_bytes,
        headers={
            "Authorization": f"Bearer {secret_key}",
            "apikey": secret_key,
            "Content-Type": "image/webp",
            "x-upsert": "true",
            "Cache-Control": "public, max-age=31536000, immutable",
        },
    )
    if response.is_error:
        message = response.text[:500].replace("\n", " ")
        raise RuntimeError(f"Supabase Storage upload failed ({response.status_code}): {message}")


def public_image_url(supabase_url: str, bucket: str, storage_path: str) -> str:
    encoded_path = "/".join(quote(part, safe="") for part in storage_path.split("/"))
    return (
        f"{supabase_url.rstrip('/')}/storage/v1/object/public/"
        f"{quote(bucket, safe='')}/{encoded_path}"
    )


def _select_rows(
    rows: list[ImageManifestRow],
    *,
    limit: int | None,
    row_numbers: set[int],
) -> list[ImageManifestRow]:
    selected = rows
    if row_numbers:
        selected = [row for row in selected if row.row_no in row_numbers]
    if limit is not None:
        selected = selected[:limit]
    return selected


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--bucket", default=DEFAULT_BUCKET)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--download-only", action="store_true")
    mode.add_argument("--upload", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--row",
        type=int,
        action="append",
        default=[],
        help="Sync one manifest row. Repeat to select multiple rows.",
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--missing-only",
        action="store_true",
        help="When uploading, skip objects that already exist in the public bucket.",
    )
    parser.add_argument("--max-width", type=int, default=DEFAULT_MAX_WIDTH)
    parser.add_argument("--max-height", type=int, default=DEFAULT_MAX_HEIGHT)
    parser.add_argument("--quality", type=int, default=DEFAULT_WEBP_QUALITY)
    return parser.parse_args()


def main() -> int:
    load_dotenv()
    args = _parse_args()
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit must be positive")
    if args.max_width < 100 or args.max_height < 100:
        raise SystemExit("Image dimensions are unrealistically small")
    if not 1 <= args.quality <= 100:
        raise SystemExit("--quality must be between 1 and 100")

    rows = _load_manifest(args.manifest)
    rows = _select_rows(rows, limit=args.limit, row_numbers=set(args.row))
    if not rows:
        raise SystemExit("No manifest rows matched the requested selection")

    incomplete = [
        row.row_no
        for row in rows
        if row.status != "sourced" or not row.image_source_url or not row.storage_path
    ]
    if incomplete:
        raise SystemExit(f"Manifest rows are not ready for sync: {incomplete}")

    supabase_url = os.getenv("SUPABASE_URL", "").strip()
    secret_key = _supabase_secret()
    if args.upload and (not supabase_url or not secret_key):
        raise SystemExit(
            "--upload requires SUPABASE_URL and SUPABASE_SECRET_KEY "
            "(or SUPABASE_SERVICE_ROLE_KEY)"
        )

    cache_dir = args.output_dir / ".source-cache"
    timeout = httpx.Timeout(45.0, connect=20.0)
    results: list[SyncResult] = []

    with httpx.Client(
        follow_redirects=True,
        timeout=timeout,
        headers={"User-Agent": USER_AGENT, "Accept": "image/*,*/*;q=0.8"},
    ) as client:
        for index, row in enumerate(rows, start=1):
            label = f"[{index}/{len(rows)}] row {row.row_no} {row.brand} {row.model} {row.year}"
            try:
                if args.upload and args.missing_only:
                    existing_url = public_image_url(
                        supabase_url,
                        args.bucket,
                        row.storage_path,
                    )
                    existing_response = client.head(existing_url)
                    if existing_response.status_code == 200:
                        print(f"{label}: skipped existing -> {row.storage_path}")
                        results.append(
                            SyncResult(
                                row_no=row.row_no,
                                storage_path=row.storage_path,
                                local_path=None,
                                uploaded=True,
                                error=None,
                            )
                        )
                        continue

                source_bytes = _download_source(
                    client,
                    row.image_source_url,
                    source_page=row.image_source_page,
                    cache_dir=cache_dir,
                    force=args.force,
                )
                webp_bytes = _normalize_to_webp(
                    source_bytes,
                    max_width=args.max_width,
                    max_height=args.max_height,
                    quality=args.quality,
                )
                local_path = _write_local(args.output_dir, row.storage_path, webp_bytes)

                uploaded = False
                if args.upload:
                    _upload_to_supabase(
                        client,
                        supabase_url=supabase_url,
                        secret_key=secret_key,
                        bucket=args.bucket,
                        storage_path=row.storage_path,
                        webp_bytes=webp_bytes,
                    )
                    uploaded = True

                size_kb = len(webp_bytes) / 1024
                action = "uploaded" if uploaded else "prepared"
                print(f"{label}: {action} {size_kb:.1f} KB -> {row.storage_path}")
                results.append(
                    SyncResult(
                        row_no=row.row_no,
                        storage_path=row.storage_path,
                        local_path=local_path,
                        uploaded=uploaded,
                        error=None,
                    )
                )
            except (httpx.HTTPError, OSError, RuntimeError, ValueError) as exc:
                print(f"{label}: FAILED: {exc}", file=sys.stderr)
                results.append(
                    SyncResult(
                        row_no=row.row_no,
                        storage_path=row.storage_path,
                        local_path=None,
                        uploaded=False,
                        error=str(exc),
                    )
                )

    failures = [result for result in results if result.error]
    succeeded = len(results) - len(failures)
    print()
    print(f"Processed: {len(results)}")
    print(f"Succeeded: {succeeded}")
    print(f"Failed: {len(failures)}")

    if args.upload and supabase_url:
        print(
            "Public base URL: "
            f"{supabase_url.rstrip('/')}/storage/v1/object/public/{args.bucket}/"
        )

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
