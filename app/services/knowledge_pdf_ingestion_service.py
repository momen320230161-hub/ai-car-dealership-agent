"""PDF-to-text extraction and validation layer for Knowledge ingestion.

This module is a pure ingestion adapter that sits in front of KnowledgeService.
It DOES NOT create embeddings, write KnowledgeChunks, or perform retrieval.
All vector indexing is delegated to the existing KnowledgeService pipeline.
"""

from __future__ import annotations

import hashlib
import io
import re
import unicodedata
from dataclasses import dataclass
from typing import IO, Any


class PDFIngestionError(ValueError):
    """Controlled, user-visible failure for PDF validation or extraction."""


@dataclass(frozen=True, slots=True)
class PDFExtractionResult:
    """Immutable extraction output from a validated PDF upload."""

    filename: str
    file_size: int
    page_count: int
    extracted_text: str
    sha256_hex: str
    mime_type: str
    extraction_method: str

    @property
    def char_count(self) -> int:
        return len(self.extracted_text)


class KnowledgePDFIngestionService:
    """Validate and extract text from uploaded PDF files.

    Responsibilities:
      - Validate PDF upload (extension, signature, size, page count)
      - Extract page text via pypdf
      - Normalize extracted text (whitespace, control chars, Unicode)
      - Calculate SHA-256 of the raw PDF bytes
      - Return PDFExtractionResult for the Admin preview/confirm flow

    This service MUST NOT:
      - Create embeddings
      - Write KnowledgeChunk records
      - Perform vector retrieval
      - Contain Flask route logic
    """

    MAX_BYTES_DEFAULT = 10 * 1024 * 1024  # 10 MB
    MAX_PAGES_DEFAULT = 50
    MAX_CHARS_DEFAULT = 100_000
    PDF_SIGNATURE = b"%PDF-"
    MIME_TYPE = "application/pdf"
    EXTRACTION_METHOD = "pypdf"

    def __init__(
        self,
        *,
        max_bytes: int = MAX_BYTES_DEFAULT,
        max_pages: int = MAX_PAGES_DEFAULT,
        max_chars: int = MAX_CHARS_DEFAULT,
    ) -> None:
        self.max_bytes = max_bytes
        self.max_pages = max_pages
        self.max_chars = max_chars

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract_from_stream(
        self,
        stream: IO[bytes],
        *,
        filename: str,
    ) -> PDFExtractionResult:
        """Validate and extract text from a PDF file stream.

        Args:
            stream: Raw binary file-like object from the upload.
            filename: Original filename as submitted by the browser.

        Returns:
            PDFExtractionResult with extracted text and provenance metadata.

        Raises:
            PDFIngestionError: Any controlled validation or extraction failure.
        """
        filename = self._validate_filename(filename)
        raw_bytes = self._read_and_validate_bytes(stream, filename)
        sha256_hex = hashlib.sha256(raw_bytes).hexdigest()
        reader = self._open_reader(raw_bytes, filename)
        page_count = self._validate_page_count(reader, filename)
        raw_text = self._extract_text(reader, filename)
        normalized_text = self._normalize_text(raw_text)
        self._validate_extracted_text(normalized_text, filename)
        return PDFExtractionResult(
            filename=filename,
            file_size=len(raw_bytes),
            page_count=page_count,
            extracted_text=normalized_text,
            sha256_hex=sha256_hex,
            mime_type=self.MIME_TYPE,
            extraction_method=self.EXTRACTION_METHOD,
        )

    def extract_from_bytes(self, raw_bytes: bytes, *, filename: str) -> PDFExtractionResult:
        """Convenience wrapper for extraction from pre-read bytes."""
        return self.extract_from_stream(io.BytesIO(raw_bytes), filename=filename)

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_filename(filename: Any) -> str:
        if not isinstance(filename, str) or not filename.strip():
            raise PDFIngestionError("اسم الملف غير موجود أو فارغ.")
        filename = filename.strip()
        # Reject path traversal — keep only the basename
        safe_name = filename.replace("\\", "/").split("/")[-1]
        if not safe_name:
            raise PDFIngestionError("اسم الملف غير صالح.")
        if not safe_name.lower().endswith(".pdf"):
            raise PDFIngestionError(
                "الملف يجب أن يكون بامتداد .pdf — نوع الملف غير مدعوم."
            )
        return safe_name

    def _read_and_validate_bytes(self, stream: IO[bytes], filename: str) -> bytes:
        try:
            raw_bytes = stream.read()
        except OSError as exc:
            raise PDFIngestionError(f"تعذر قراءة الملف المرفوع: {filename}") from exc

        if not raw_bytes:
            raise PDFIngestionError("الملف المرفوع فارغ.")

        if len(raw_bytes) > self.max_bytes:
            mb = self.max_bytes / (1024 * 1024)
            raise PDFIngestionError(
                f"حجم الملف يتجاوز الحد المسموح ({mb:.0f} MB). "
                "يُرجى رفع ملف أصغر."
            )

        if not raw_bytes.startswith(self.PDF_SIGNATURE):
            raise PDFIngestionError(
                "الملف لا يبدأ بتوقيع PDF الصحيح (%PDF-). "
                "تأكد من أن الملف المرفوع هو PDF حقيقي."
            )

        return raw_bytes

    @staticmethod
    def _open_reader(raw_bytes: bytes, filename: str) -> Any:
        try:
            from pypdf import PdfReader  # type: ignore[import-untyped]
        except ImportError as exc:
            raise PDFIngestionError(
                "مكتبة pypdf غير متوفرة — تأكد من تثبيت المتطلبات."
            ) from exc

        try:
            reader = PdfReader(io.BytesIO(raw_bytes), strict=False)
        except Exception as exc:
            raise PDFIngestionError(
                f"تعذر فتح ملف PDF: {filename} — قد يكون الملف تالفاً."
            ) from exc

        try:
            if reader.is_encrypted:
                try:
                    decrypt_result = reader.decrypt("")
                    # decrypt_result of 0 means wrong password
                    if decrypt_result == 0:
                        raise PDFIngestionError(
                            "ملف PDF محمي بكلمة مرور — لا يمكن استخراج النص."
                        )
                except Exception as exc:
                    if isinstance(exc, PDFIngestionError):
                        raise
                    raise PDFIngestionError(
                        "ملف PDF محمي بكلمة مرور — لا يمكن استخراج النص."
                    ) from exc
        except PDFIngestionError:
            raise
        except Exception:
            # is_encrypted itself may raise on malformed PDFs
            pass

        return reader

    def _validate_page_count(self, reader: Any, filename: str) -> int:
        try:
            page_count = len(reader.pages)
        except Exception as exc:
            raise PDFIngestionError(
                f"تعذر قراءة صفحات PDF: {filename}"
            ) from exc

        if page_count == 0:
            raise PDFIngestionError("ملف PDF لا يحتوي على صفحات.")

        if page_count > self.max_pages:
            raise PDFIngestionError(
                f"ملف PDF يحتوي على {page_count} صفحة، "
                f"الحد المسموح هو {self.max_pages} صفحة."
            )

        return page_count

    @staticmethod
    def _extract_text(reader: Any, filename: str) -> str:
        parts: list[str] = []
        try:
            for page in reader.pages:
                try:
                    page_text = page.extract_text() or ""
                    parts.append(page_text)
                except Exception:
                    # Individual page failure — skip silently, preserve others
                    parts.append("")
        except Exception as exc:
            raise PDFIngestionError(
                f"تعذر استخراج النص من PDF: {filename}"
            ) from exc
        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Text normalization
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_text(raw_text: str) -> str:
        """Normalize extracted PDF text while preserving Arabic Unicode.

        Rules:
        - Remove NUL and other binary control characters (except LF, CR, TAB)
        - Normalize Unicode to NFC form (important for Arabic composites)
        - Convert CR/CRLF line endings to LF
        - Collapse runs of more than 2 blank lines into 2 (preserve paragraphs)
        - Collapse runs of spaces/tabs within a line to a single space
        - Strip trailing whitespace from lines
        - Do NOT collapse everything into one line
        - Do NOT semantically alter the content
        """
        if not raw_text:
            return ""

        # NFC normalize (correct for Arabic)
        text = unicodedata.normalize("NFC", raw_text)

        # Remove NUL and other binary control chars (keep \n \r \t)
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)

        # Normalize CRLF → LF
        text = text.replace("\r\n", "\n").replace("\r", "\n")

        # Collapse intra-line whitespace (spaces/tabs) to single space
        lines = text.split("\n")
        normalized_lines: list[str] = []
        for line in lines:
            # Collapse horizontal whitespace within line
            normalized_line = re.sub(r"[ \t]+", " ", line).strip()
            normalized_lines.append(normalized_line)

        text = "\n".join(normalized_lines)

        # Collapse runs of 3+ blank lines to exactly 2 blank lines
        text = re.sub(r"\n{3,}", "\n\n", text)

        return text.strip()

    def _validate_extracted_text(self, text: str, filename: str) -> None:
        if not text or not text.strip():
            raise PDFIngestionError(
                f"لم يتم استخراج أي نص من PDF: {filename} — "
                "قد يكون الملف مسحاً ضوئياً (صور) ويحتاج OCR غير مدعوم."
            )
        if len(text) > self.max_chars:
            raise PDFIngestionError(
                f"النص المستخرج ({len(text):,} حرف) يتجاوز الحد المسموح "
                f"({self.max_chars:,} حرف). يُرجى استخدام مستند أصغر."
            )
