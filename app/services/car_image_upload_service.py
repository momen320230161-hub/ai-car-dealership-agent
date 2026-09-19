"""Validated server-side uploads for admin-managed catalog images."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath
from urllib.parse import quote

import httpx
from PIL import Image, ImageOps, UnidentifiedImageError
from werkzeug.datastructures import FileStorage


class CarImageError(RuntimeError):
    """Base error for controlled catalog image failures."""


class CarImageValidationError(CarImageError):
    """Raised when an uploaded file is not an allowed image."""


class CarImageStorageError(CarImageError):
    """Raised when Supabase Storage is unavailable or misconfigured."""


@dataclass(frozen=True, slots=True)
class ValidatedCarImage:
    content: bytes
    content_type: str
    extension: str


_IMAGE_SIGNATURES = (
    (lambda data: data.startswith(b"\xff\xd8\xff"), "image/jpeg", "jpg"),
    (lambda data: data.startswith(b"\x89PNG\r\n\x1a\n"), "image/png", "png"),
    (
        lambda data: len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP",
        "image/webp",
        "webp",
    ),
)
_MAX_IMAGE_DIMENSIONS = (1600, 1200)
Image.MAX_IMAGE_PIXELS = 25_000_000


def validate_car_image(
    upload: FileStorage | None,
    *,
    max_bytes: int,
) -> ValidatedCarImage | None:
    """Read and validate one optional JPEG, PNG, or WebP upload by its bytes."""

    if upload is None or not str(upload.filename or "").strip():
        return None

    content = upload.stream.read(max_bytes + 1)
    if not content:
        raise CarImageValidationError("Image file is empty")
    if len(content) > max_bytes:
        raise CarImageValidationError("Image file is larger than the allowed limit")

    for matches, _content_type, _extension in _IMAGE_SIGNATURES:
        if matches(content):
            break
    else:
        raise CarImageValidationError("Only valid JPEG, PNG, and WebP images are allowed")

    try:
        with Image.open(BytesIO(content)) as source:
            source.load()
            normalized = ImageOps.exif_transpose(source)
            has_alpha = "A" in normalized.getbands() or "transparency" in normalized.info
            normalized = normalized.convert("RGBA" if has_alpha else "RGB")
            normalized.thumbnail(_MAX_IMAGE_DIMENSIONS, Image.Resampling.LANCZOS)
            output = BytesIO()
            normalized.save(output, format="WEBP", quality=84, method=6, optimize=True)
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError, ValueError) as exc:
        raise CarImageValidationError("Uploaded file could not be decoded as an image") from exc

    return ValidatedCarImage(output.getvalue(), "image/webp", "webp")


class SupabaseCarImageStorage:
    """Upload trusted image bytes with a server-only Supabase secret key."""

    def __init__(
        self,
        *,
        supabase_url: str | None,
        secret_key: str | None,
        bucket: str = "car-images",
        timeout_seconds: float = 20.0,
    ) -> None:
        self.supabase_url = str(supabase_url or "").strip().rstrip("/")
        self.secret_key = str(secret_key or "").strip()
        self.bucket = str(bucket or "").strip()
        self.timeout_seconds = timeout_seconds
        if not self.supabase_url or not self.secret_key or not self.bucket:
            raise CarImageStorageError("Supabase Storage is not configured")

    def upload(self, car_id: int, image: ValidatedCarImage) -> str:
        storage_path = f"admin/{car_id}/{uuid.uuid4().hex}.{image.extension}"
        endpoint = self._object_endpoint(storage_path)
        try:
            response = httpx.post(
                endpoint,
                content=image.content,
                headers={
                    **self._headers(),
                    "Content-Type": image.content_type,
                    "x-upsert": "false",
                    "Cache-Control": "public, max-age=31536000, immutable",
                },
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise CarImageStorageError("Supabase Storage upload failed") from exc
        return storage_path

    def delete(self, storage_path: str) -> None:
        """Best-effort removal through the Storage API, never direct SQL."""

        safe_path = self._safe_path(storage_path)
        endpoint = (
            f"{self.supabase_url}/storage/v1/object/{quote(self.bucket, safe='')}"
        )
        try:
            response = httpx.request(
                "DELETE",
                endpoint,
                json={"prefixes": [safe_path]},
                headers=self._headers(),
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise CarImageStorageError("Supabase Storage delete failed") from exc

    def _object_endpoint(self, storage_path: str) -> str:
        safe_path = self._safe_path(storage_path)
        encoded_path = "/".join(quote(part, safe="") for part in safe_path.split("/"))
        return (
            f"{self.supabase_url}/storage/v1/object/"
            f"{quote(self.bucket, safe='')}/{encoded_path}"
        )

    def _headers(self) -> dict[str, str]:
        headers = {"apikey": self.secret_key}
        # New sb_secret keys are opaque API keys and must not be parsed as JWTs.
        # Legacy service_role JWTs still use the Authorization bearer header.
        if not self.secret_key.startswith("sb_secret_"):
            headers["Authorization"] = f"Bearer {self.secret_key}"
        return headers

    @staticmethod
    def _safe_path(storage_path: str) -> str:
        path = str(storage_path or "").strip().replace("\\", "/").lstrip("/")
        if not path or ".." in PurePosixPath(path).parts:
            raise CarImageStorageError("Unsafe Supabase Storage path")
        return path
