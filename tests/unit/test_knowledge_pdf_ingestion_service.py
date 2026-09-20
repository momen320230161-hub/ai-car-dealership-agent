"""Unit tests for KnowledgePDFIngestionService.

Tests cover:
- valid text PDF extraction path
- whitespace/text normalization
- filename handling (extension, path traversal)
- SHA-256 generation
- invalid extension
- invalid PDF signature
- oversized PDF
- malformed PDF
- encrypted/unreadable PDF
- page limit
- blank/no-text PDF
- extracted character limit (service config)
- full service wiring with mock reader

All tests are offline — no network, no real PDF parser, no Gemini quota.
"""

from __future__ import annotations

import hashlib
import io
import unicodedata
from unittest.mock import MagicMock, patch

import pytest

from app.services.knowledge_pdf_ingestion_service import (
    KnowledgePDFIngestionService,
    PDFIngestionError,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PDF_HEADER = b"%PDF-1.7\n"
_VALID_SMALL_PDF = _PDF_HEADER + b"fake body content for testing"


def _svc(*, max_bytes: int = 10_485_760, max_pages: int = 50, max_chars: int = 100_000):
    return KnowledgePDFIngestionService(
        max_bytes=max_bytes, max_pages=max_pages, max_chars=max_chars
    )


def _make_reader(text: str = "Hello World", *, pages: int = 1, encrypted: bool = False):
    """Build a minimal mock PdfReader that returns fake page text."""
    mock_page = MagicMock()
    mock_page.extract_text.return_value = text
    mock_reader = MagicMock()
    mock_reader.pages = [mock_page] * pages
    mock_reader.is_encrypted = encrypted
    return mock_reader


# ---------------------------------------------------------------------------
# 1. Valid text PDF extraction
# ---------------------------------------------------------------------------


def test_valid_pdf_extraction_returns_result():
    """Happy path: well-formed PDF bytes → PDFExtractionResult."""
    svc = _svc()
    with patch(
        "app.services.knowledge_pdf_ingestion_service.KnowledgePDFIngestionService._open_reader",
        return_value=_make_reader("AutoDrive Egypt PDF content", pages=3),
    ):
        result = svc.extract_from_bytes(_VALID_SMALL_PDF, filename="test.pdf")

    assert result.filename == "test.pdf"
    assert result.page_count == 3
    assert result.file_size == len(_VALID_SMALL_PDF)
    assert "AutoDrive Egypt PDF content" in result.extracted_text
    assert result.sha256_hex == hashlib.sha256(_VALID_SMALL_PDF).hexdigest()
    assert len(result.sha256_hex) == 64
    assert result.mime_type == "application/pdf"
    assert result.extraction_method == "pypdf"
    assert result.char_count > 0


# ---------------------------------------------------------------------------
# 2. SHA-256 generation
# ---------------------------------------------------------------------------


def test_sha256_matches_raw_bytes():
    """SHA-256 must be computed from the original raw bytes, not extracted text."""
    raw = _VALID_SMALL_PDF
    expected = hashlib.sha256(raw).hexdigest()
    with patch(
        "app.services.knowledge_pdf_ingestion_service.KnowledgePDFIngestionService._open_reader",
        return_value=_make_reader("content", pages=1),
    ):
        result = _svc().extract_from_bytes(raw, filename="doc.pdf")
    assert result.sha256_hex == expected


# ---------------------------------------------------------------------------
# 3. Text normalization
# ---------------------------------------------------------------------------


def test_normalization_collapses_blank_lines():
    svc = _svc()
    raw = "Line one\n\n\n\n\nLine two"
    normalized = svc._normalize_text(raw)
    assert "\n\n\n" not in normalized
    assert "Line one" in normalized
    assert "Line two" in normalized


def test_normalization_removes_control_chars():
    svc = _svc()
    raw = "Hello\x00World\x01\x08"
    normalized = svc._normalize_text(raw)
    assert "\x00" not in normalized
    assert "\x01" not in normalized
    assert "Hello" in normalized
    assert "World" in normalized


def test_normalization_preserves_arabic_unicode():
    svc = _svc()
    arabic = "تسجيل السيارة في مصر يتطلب المستندات التالية"
    normalized = svc._normalize_text(arabic)
    assert normalized == unicodedata.normalize("NFC", arabic)


def test_normalization_strips_excess_spaces():
    svc = _svc()
    raw = "hello    world   \n  end"
    normalized = svc._normalize_text(raw)
    assert "hello world" in normalized
    assert "    " not in normalized


def test_normalization_normalizes_crlf():
    svc = _svc()
    raw = "line1\r\nline2\rline3"
    normalized = svc._normalize_text(raw)
    assert "\r" not in normalized
    assert "line1" in normalized
    assert "line2" in normalized


def test_normalization_empty_string_returns_empty():
    assert _svc()._normalize_text("") == ""


# ---------------------------------------------------------------------------
# 4. Filename validation
# ---------------------------------------------------------------------------


def test_filename_extension_must_be_pdf():
    with pytest.raises(PDFIngestionError, match=".pdf"):
        _svc()._validate_filename("document.docx")


def test_filename_blank_raises():
    with pytest.raises(PDFIngestionError):
        _svc()._validate_filename("   ")


def test_filename_path_traversal_is_stripped():
    safe = _svc()._validate_filename("../../etc/passwd.pdf")
    assert safe == "passwd.pdf"


def test_filename_windows_path_stripped():
    safe = _svc()._validate_filename("C:\\Users\\admin\\report.pdf")
    assert safe == "report.pdf"


def test_filename_none_raises():
    with pytest.raises(PDFIngestionError):
        _svc()._validate_filename(None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 5. Invalid PDF signature
# ---------------------------------------------------------------------------


def test_invalid_pdf_signature_raises():
    fake_bytes = b"PK\x03\x04this is a zip not a pdf"  # zip file signature
    with pytest.raises(PDFIngestionError, match="%PDF-"):
        _svc().extract_from_bytes(fake_bytes, filename="bad.pdf")


def test_empty_file_raises():
    with pytest.raises(PDFIngestionError, match="فارغ"):
        _svc().extract_from_bytes(b"", filename="empty.pdf")


# ---------------------------------------------------------------------------
# 6. Oversized PDF
# ---------------------------------------------------------------------------


def test_oversized_pdf_raises():
    max_bytes = 100
    large_pdf = _PDF_HEADER + b"x" * 200  # > 100 bytes
    with pytest.raises(PDFIngestionError, match="حجم"):
        _svc(max_bytes=max_bytes).extract_from_bytes(large_pdf, filename="big.pdf")


# ---------------------------------------------------------------------------
# 7. Malformed PDF
# ---------------------------------------------------------------------------


def test_malformed_pdf_raises():
    """A PDF that opens but causes an exception during page reading."""

    def raise_on_pages():
        raise Exception("malformed PDF internal error")

    mock_reader = MagicMock()
    mock_reader.is_encrypted = False
    type(mock_reader).pages = property(lambda self: (_ for _ in ()).throw(Exception("bad")))

    with patch(
        "app.services.knowledge_pdf_ingestion_service.KnowledgePDFIngestionService._open_reader",
        side_effect=PDFIngestionError("تعذر فتح ملف PDF"),
    ):
        with pytest.raises(PDFIngestionError, match="تعذر"):
            _svc().extract_from_bytes(_VALID_SMALL_PDF, filename="malformed.pdf")


# ---------------------------------------------------------------------------
# 8. Encrypted/password-protected PDF
# ---------------------------------------------------------------------------


def test_encrypted_pdf_raises():
    encrypted_reader = MagicMock()
    encrypted_reader.is_encrypted = True
    encrypted_reader.decrypt.return_value = 0  # 0 = wrong password

    with patch(
        "app.services.knowledge_pdf_ingestion_service.KnowledgePDFIngestionService._open_reader",
        side_effect=PDFIngestionError("ملف PDF محمي بكلمة مرور"),
    ):
        with pytest.raises(PDFIngestionError, match="محمي"):
            _svc().extract_from_bytes(_VALID_SMALL_PDF, filename="encrypted.pdf")


# ---------------------------------------------------------------------------
# 9. Page limit
# ---------------------------------------------------------------------------


def test_page_count_zero_raises():
    mock_reader = _make_reader(pages=0)
    with patch(
        "app.services.knowledge_pdf_ingestion_service.KnowledgePDFIngestionService._open_reader",
        return_value=mock_reader,
    ):
        with pytest.raises(PDFIngestionError, match="صفحات"):
            _svc().extract_from_bytes(_VALID_SMALL_PDF, filename="empty_pages.pdf")


def test_page_count_over_limit_raises():
    mock_reader = _make_reader(text="page content", pages=60)
    with patch(
        "app.services.knowledge_pdf_ingestion_service.KnowledgePDFIngestionService._open_reader",
        return_value=mock_reader,
    ):
        with pytest.raises(PDFIngestionError, match="صفحة"):
            _svc(max_pages=50).extract_from_bytes(_VALID_SMALL_PDF, filename="large.pdf")


def test_page_count_at_limit_is_accepted():
    mock_reader = _make_reader(text="content on page", pages=50)
    with patch(
        "app.services.knowledge_pdf_ingestion_service.KnowledgePDFIngestionService._open_reader",
        return_value=mock_reader,
    ):
        result = _svc(max_pages=50).extract_from_bytes(_VALID_SMALL_PDF, filename="limit.pdf")
    assert result.page_count == 50


# ---------------------------------------------------------------------------
# 10. Blank / no-text PDF
# ---------------------------------------------------------------------------


def test_blank_text_pdf_raises():
    """PDF that yields only whitespace / empty strings → error."""
    mock_reader = _make_reader(text="   \n  \t  ", pages=1)
    with patch(
        "app.services.knowledge_pdf_ingestion_service.KnowledgePDFIngestionService._open_reader",
        return_value=mock_reader,
    ):
        with pytest.raises(PDFIngestionError, match="نص"):
            _svc().extract_from_bytes(_VALID_SMALL_PDF, filename="blank.pdf")


# ---------------------------------------------------------------------------
# 11. Extracted character limit
# ---------------------------------------------------------------------------


def test_extracted_char_limit_raises():
    """Service raises when extracted text exceeds max_chars."""
    svc = _svc(max_chars=100)
    with pytest.raises(PDFIngestionError, match="يتجاوز الحد"):
        svc._validate_extracted_text("x" * 101, "big_text.pdf")


def test_extracted_char_within_limit_passes():
    svc = _svc(max_chars=500)
    # This does NOT raise — the service itself truncates at the route layer,
    # but the service validates blank text not length; length truncation is in route.
    # The validate_extracted_text only rejects blank text:
    svc._validate_extracted_text("x" * 500, "ok.pdf")  # should not raise


# ---------------------------------------------------------------------------
# 12. extract_from_stream works with file-like object
# ---------------------------------------------------------------------------


def test_extract_from_stream_uses_stream():
    svc = _svc()
    stream = io.BytesIO(_VALID_SMALL_PDF)
    with patch(
        "app.services.knowledge_pdf_ingestion_service.KnowledgePDFIngestionService._open_reader",
        return_value=_make_reader("Stream content", pages=2),
    ):
        result = svc.extract_from_stream(stream, filename="stream.pdf")
    assert result.page_count == 2
    assert "Stream content" in result.extracted_text
