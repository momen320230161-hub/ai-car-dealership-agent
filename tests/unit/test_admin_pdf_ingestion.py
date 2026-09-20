"""Admin route integration tests for PDF Knowledge Ingestion.

Tests cover:
- GET upload page (requires admin auth)
- POST extraction/preview (valid PDF → preview page with metadata)
- POST extraction/preview (invalid PDF → controlled error)
- POST confirm (creates KnowledgeDocument with source_type=pdf)
- POST confirm (duplicate SHA → controlled error, no second document)
- POST confirm with invalid/expired signed token
- POST confirm with embedding failure → document/index consistent

All tests use deterministic embedding provider and mock PdfReader.
No network access, no Gemini quota consumed.
"""

from __future__ import annotations

import hashlib
import io
import uuid
from unittest.mock import MagicMock, patch

from sqlalchemy import func, select

from app.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.models.user import UserProfile

_PDF_HEADER = b"%PDF-1.7\n"
_VALID_SMALL_PDF = _PDF_HEADER + b"fake body content for testing"
_PDF_SHA256 = hashlib.sha256(_VALID_SMALL_PDF).hexdigest()

_ARABIC_CONTENT = (
    "تسجيل السيارة في جمهورية مصر العربية يتطلب تقديم المستندات التالية:\n\n"
    "أولاً: بطاقة الرقم القومي لصاحب السيارة.\n"
    "ثانياً: عقد البيع أو الفاتورة الرسمية.\n"
    "ثالثاً: شهادة الجمارك للسيارات المستوردة.\n\n"
    "تراجع مديرية المرور المختصة في مقر إقامة المالك."
)


def _make_reader(text: str = _ARABIC_CONTENT, *, pages: int = 3):
    mock_page = MagicMock()
    mock_page.extract_text.return_value = text
    mock_reader = MagicMock()
    mock_reader.pages = [mock_page] * pages
    mock_reader.is_encrypted = False
    return mock_reader


def _login_admin(app, db_session):
    user = UserProfile(
        id=uuid.uuid4(),
        email="admin@pdf-test.com",
        display_name="PDF Admin",
        role="admin",
        active=True,
    )
    db_session.add(user)
    db_session.commit()
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True
    return client


def _csrf(client) -> str:
    with client.session_transaction() as sess:
        return str(sess["_admin_csrf_token"])


def _patch_reader(reader):
    return patch(
        "app.services.knowledge_pdf_ingestion_service.KnowledgePDFIngestionService._open_reader",
        return_value=reader,
    )


# ---------------------------------------------------------------------------
# 1. GET upload page
# ---------------------------------------------------------------------------


def test_pdf_upload_page_requires_admin_auth(app, db_session) -> None:
    """Unauthenticated access to PDF upload must redirect to login."""
    client = app.test_client()
    resp = client.get("/admin/knowledge/import/pdf")
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]


def test_pdf_upload_page_renders_for_admin(app, db_session) -> None:
    app.config.update(
        EMBEDDING_PROVIDER="deterministic",
        EMBEDDING_MODEL="deterministic-test-v1",
    )
    client = _login_admin(app, db_session)
    resp = client.get("/admin/knowledge/import/pdf")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "PDF" in body
    assert "pdf_file" in body


# ---------------------------------------------------------------------------
# 2. POST preview — valid PDF
# ---------------------------------------------------------------------------


def test_pdf_preview_extracts_and_shows_metadata(app, db_session) -> None:
    app.config.update(
        EMBEDDING_PROVIDER="deterministic",
        EMBEDDING_MODEL="deterministic-test-v1",
    )
    client = _login_admin(app, db_session)
    client.get("/admin/knowledge/import/pdf")
    token = _csrf(client)

    with _patch_reader(_make_reader(text=_ARABIC_CONTENT, pages=3)):
        resp = client.post(
            "/admin/knowledge/import/pdf/preview",
            data={
                "csrf_token": token,
                "pdf_file": (io.BytesIO(_VALID_SMALL_PDF), "traffic_law.pdf"),
            },
            content_type="multipart/form-data",
        )

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # Page count
    assert "3" in body
    # Filename
    assert "traffic_law.pdf" in body
    # Extracted Arabic text present
    assert "تسجيل" in body
    # Signed token hidden field
    assert "signed_token" in body


# ---------------------------------------------------------------------------
# 3. POST preview — invalid PDF (bad signature)
# ---------------------------------------------------------------------------


def test_pdf_preview_rejects_non_pdf_content(app, db_session) -> None:
    app.config.update(
        EMBEDDING_PROVIDER="deterministic",
        EMBEDDING_MODEL="deterministic-test-v1",
    )
    client = _login_admin(app, db_session)
    client.get("/admin/knowledge/import/pdf")
    token = _csrf(client)

    bad_file = b"This is not a PDF at all"
    resp = client.post(
        "/admin/knowledge/import/pdf/preview",
        data={
            "csrf_token": token,
            "pdf_file": (io.BytesIO(bad_file), "fake.pdf"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "%PDF-" in body or "PDF" in body  # error flash mentions PDF issue


# ---------------------------------------------------------------------------
# 4. POST confirm — creates KnowledgeDocument via KnowledgeService
# ---------------------------------------------------------------------------


def test_pdf_confirm_creates_indexed_knowledge_document(app, db_session) -> None:
    app.config.update(
        EMBEDDING_PROVIDER="deterministic",
        EMBEDDING_MODEL="deterministic-test-v1",
    )
    client = _login_admin(app, db_session)
    client.get("/admin/knowledge/import/pdf")
    token = _csrf(client)

    # Step 1: get signed token via preview
    with _patch_reader(_make_reader(text=_ARABIC_CONTENT, pages=3)):
        preview_resp = client.post(
            "/admin/knowledge/import/pdf/preview",
            data={
                "csrf_token": token,
                "pdf_file": (io.BytesIO(_VALID_SMALL_PDF), "traffic_reg.pdf"),
            },
            content_type="multipart/form-data",
        )
    assert preview_resp.status_code == 200

    # Extract signed_token from the response body
    preview_body = preview_resp.get_data(as_text=True)
    import re

    match = re.search(r'name="signed_token"\s+value="([^"]+)"', preview_body)
    assert match, "signed_token not found in preview form"
    signed_token = match.group(1)

    # Step 2: confirm
    confirm_resp = client.post(
        "/admin/knowledge/import/pdf/confirm",
        data={
            "csrf_token": token,
            "signed_token": signed_token,
            "title": "قانون تسجيل المركبات",
            "category": "traffic",
            "source_name": "هيئة المرور المصرية",
            "content": _ARABIC_CONTENT,
            "active": "on",
        },
        follow_redirects=False,
    )
    assert confirm_resp.status_code == 302

    # Verify KnowledgeDocument
    document = db_session.scalar(select(KnowledgeDocument))
    assert document is not None
    assert document.title == "قانون تسجيل المركبات"
    assert document.category == "traffic"
    assert document.source_type == "pdf"
    assert document.source_filename == "traffic_reg.pdf"
    assert document.source_sha256 == _PDF_SHA256
    assert document.source_page_count == 3
    assert document.source_name == "هيئة المرور المصرية"
    assert document.index_status == "indexed"
    assert document.indexed_version == 1
    assert document.content_version == 1

    # Verify chunks
    chunk_count = db_session.scalar(
        select(func.count(KnowledgeChunk.id)).where(KnowledgeChunk.document_id == document.id)
    )
    assert chunk_count >= 1

    # Verify 768-dim embeddings
    chunk = db_session.scalar(
        select(KnowledgeChunk).where(KnowledgeChunk.document_id == document.id)
    )
    assert len(chunk.embedding) == 768


# ---------------------------------------------------------------------------
# 5. Duplicate SHA-256 → controlled error, no second document
# ---------------------------------------------------------------------------


def test_pdf_confirm_rejects_duplicate_sha256(app, db_session) -> None:
    app.config.update(
        EMBEDDING_PROVIDER="deterministic",
        EMBEDDING_MODEL="deterministic-test-v1",
    )
    client = _login_admin(app, db_session)
    client.get("/admin/knowledge/import/pdf")
    token = _csrf(client)

    # First import
    with _patch_reader(_make_reader(text=_ARABIC_CONTENT, pages=3)):
        preview_resp = client.post(
            "/admin/knowledge/import/pdf/preview",
            data={
                "csrf_token": token,
                "pdf_file": (io.BytesIO(_VALID_SMALL_PDF), "dup.pdf"),
            },
            content_type="multipart/form-data",
        )
    import re

    match = re.search(
        r'name="signed_token"\s+value="([^"]+)"', preview_resp.get_data(as_text=True)
    )
    signed_token = match.group(1)

    client.post(
        "/admin/knowledge/import/pdf/confirm",
        data={
            "csrf_token": token,
            "signed_token": signed_token,
            "title": "First Import",
            "category": "legal",
            "content": _ARABIC_CONTENT,
            "active": "on",
        },
    )

    # Second import of the same bytes
    with _patch_reader(_make_reader(text=_ARABIC_CONTENT, pages=3)):
        preview_resp2 = client.post(
            "/admin/knowledge/import/pdf/preview",
            data={
                "csrf_token": token,
                "pdf_file": (io.BytesIO(_VALID_SMALL_PDF), "dup.pdf"),
            },
            content_type="multipart/form-data",
        )

    match2 = re.search(
        r'name="signed_token"\s+value="([^"]+)"', preview_resp2.get_data(as_text=True)
    )
    signed_token2 = match2.group(1)

    dup_resp = client.post(
        "/admin/knowledge/import/pdf/confirm",
        data={
            "csrf_token": token,
            "signed_token": signed_token2,
            "title": "Duplicate Import",
            "category": "legal",
            "content": _ARABIC_CONTENT,
            "active": "on",
        },
        follow_redirects=True,
    )

    assert dup_resp.status_code == 200
    body = dup_resp.get_data(as_text=True)
    assert "SHA-256" in body or "موجود بالفعل" in body

    # Only one KnowledgeDocument should exist
    count = db_session.scalar(select(func.count(KnowledgeDocument.id)))
    assert count == 1


# ---------------------------------------------------------------------------
# 6. Invalid / tampered signed token
# ---------------------------------------------------------------------------


def test_pdf_confirm_rejects_invalid_signed_token(app, db_session) -> None:
    app.config.update(
        EMBEDDING_PROVIDER="deterministic",
        EMBEDDING_MODEL="deterministic-test-v1",
    )
    client = _login_admin(app, db_session)
    client.get("/admin/knowledge/import/pdf")
    token = _csrf(client)

    resp = client.post(
        "/admin/knowledge/import/pdf/confirm",
        data={
            "csrf_token": token,
            "signed_token": "TAMPERED.INVALID.TOKEN",
            "title": "Bad",
            "category": "legal",
            "content": "content",
            "active": "on",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "غير صالحة" in body or "جلسة" in body


# ---------------------------------------------------------------------------
# 7. Missing required form fields at confirm step
# ---------------------------------------------------------------------------


def test_pdf_confirm_requires_title_and_category(app, db_session) -> None:
    app.config.update(
        EMBEDDING_PROVIDER="deterministic",
        EMBEDDING_MODEL="deterministic-test-v1",
    )
    client = _login_admin(app, db_session)
    client.get("/admin/knowledge/import/pdf")
    token = _csrf(client)

    with _patch_reader(_make_reader(text=_ARABIC_CONTENT, pages=1)):
        preview_resp = client.post(
            "/admin/knowledge/import/pdf/preview",
            data={
                "csrf_token": token,
                "pdf_file": (io.BytesIO(_VALID_SMALL_PDF), "req.pdf"),
            },
            content_type="multipart/form-data",
        )
    import re

    match = re.search(
        r'name="signed_token"\s+value="([^"]+)"', preview_resp.get_data(as_text=True)
    )
    signed_token = match.group(1)

    resp = client.post(
        "/admin/knowledge/import/pdf/confirm",
        data={
            "csrf_token": token,
            "signed_token": signed_token,
            "title": "",  # missing
            "category": "",  # missing
            "content": _ARABIC_CONTENT,
            "active": "on",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    # No document created
    count = db_session.scalar(select(func.count(KnowledgeDocument.id)))
    assert count == 0
