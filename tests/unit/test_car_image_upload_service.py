"""Security and Storage API tests for admin catalog image uploads."""

from __future__ import annotations

from io import BytesIO

import httpx
import pytest
from PIL import Image
from werkzeug.datastructures import FileStorage

from app.services.car_image_upload_service import (
    CarImageStorageError,
    CarImageValidationError,
    SupabaseCarImageStorage,
    validate_car_image,
)


def _upload(content: bytes, filename: str = "car.png") -> FileStorage:
    return FileStorage(stream=BytesIO(content), filename=filename)


def _image_bytes(format_name: str) -> bytes:
    output = BytesIO()
    Image.new("RGB", (12, 8), color=(15, 23, 42)).save(output, format=format_name)
    return output.getvalue()


def test_validate_car_image_accepts_supported_magic_bytes() -> None:
    png = validate_car_image(
        _upload(_image_bytes("PNG")),
        max_bytes=1024,
    )

    assert png is not None
    assert png.content_type == "image/webp"
    assert png.extension == "webp"
    assert png.content.startswith(b"RIFF") and png.content[8:12] == b"WEBP"


def test_validate_car_image_rejects_spoofed_and_oversized_files() -> None:
    with pytest.raises(CarImageValidationError):
        validate_car_image(_upload(b"not-an-image", "fake.png"), max_bytes=1024)

    with pytest.raises(CarImageValidationError):
        validate_car_image(
            _upload(_image_bytes("PNG")),
            max_bytes=10,
        )


def test_supabase_upload_uses_server_auth_and_unique_admin_path(monkeypatch) -> None:
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_post)
    storage = SupabaseCarImageStorage(
        supabase_url="https://project.supabase.co",
        secret_key="sb_secret_server-secret",
    )
    image = validate_car_image(_upload(_image_bytes("JPEG"), "car.jpg"), max_bytes=1024)
    assert image is not None

    path = storage.upload(42, image)

    assert path.startswith("admin/42/") and path.endswith(".webp")
    assert captured["url"].endswith(f"/car-images/{path}")
    assert captured["headers"]["apikey"] == "sb_secret_server-secret"
    assert "Authorization" not in captured["headers"]
    assert captured["headers"]["x-upsert"] == "false"


def test_supabase_storage_rejects_missing_config_and_unsafe_path() -> None:
    with pytest.raises(CarImageStorageError):
        SupabaseCarImageStorage(supabase_url="", secret_key="")

    storage = SupabaseCarImageStorage(
        supabase_url="https://project.supabase.co",
        secret_key="server-secret",
    )
    with pytest.raises(CarImageStorageError):
        storage.delete("../other-bucket/file.png")
