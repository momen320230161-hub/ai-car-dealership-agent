"""HTTP and service regressions for the required admin dashboard."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.models.user import UserProfile


def _login_admin(app, db_session):
    user = UserProfile(
        id=uuid.uuid4(),
        email="admin@example.com",
        display_name="Admin User",
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


def test_admin_dashboard_requires_authentication(unauthed_client) -> None:
    response = unauthed_client.get("/admin/")

    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


def test_customer_cannot_access_admin_dashboard(client) -> None:
    response = client.get("/admin/")

    assert response.status_code == 403


def test_admin_can_open_required_dashboard_sections(app, db_session) -> None:
    client = _login_admin(app, db_session)

    assert client.get("/admin/").status_code == 200
    assert client.get("/admin/cars").status_code == 200
    assert client.get("/admin/test-drives").status_code == 200
    assert client.get("/admin/leads").status_code == 200
    assert client.get("/admin/knowledge").status_code == 200


def test_admin_knowledge_write_requires_csrf(app, db_session) -> None:
    app.config.update(
        EMBEDDING_PROVIDER="deterministic",
        EMBEDDING_MODEL="deterministic-test-v1",
    )
    client = _login_admin(app, db_session)

    response = client.post(
        "/admin/knowledge/new",
        data={"title": "Warranty", "category": "warranty", "content": "Coverage text."},
    )

    assert response.status_code == 400
    assert db_session.scalar(select(func.count(KnowledgeDocument.id))) == 0


def test_admin_rag_crud_reindexes_updated_content(app, db_session) -> None:
    app.config.update(
        EMBEDDING_PROVIDER="deterministic",
        EMBEDDING_MODEL="deterministic-test-v1",
    )
    client = _login_admin(app, db_session)

    form = client.get("/admin/knowledge/new")
    assert form.status_code == 200
    token = _csrf(client)

    created = client.post(
        "/admin/knowledge/new",
        data={
            "csrf_token": token,
            "title": "Test Drive Policy",
            "category": "test drive policy",
            "content": "Bring a valid driving licence for the requested test drive.",
            "active": "on",
        },
        follow_redirects=False,
    )
    assert created.status_code == 302

    document = db_session.scalar(select(KnowledgeDocument))
    assert document is not None
    assert document.index_status == "indexed"
    assert document.content_version == 1
    assert document.indexed_version == 1
    first_chunk_count = int(
        db_session.scalar(
            select(func.count(KnowledgeChunk.id)).where(KnowledgeChunk.document_id == document.id)
        )
        or 0
    )
    assert first_chunk_count >= 1

    updated = client.post(
        f"/admin/knowledge/{document.id}/edit",
        data={
            "csrf_token": token,
            "title": "Test Drive Policy",
            "category": "test drive policy",
            "content": "Bring a valid driving licence and arrive ten minutes before the request.",
            "active": "on",
        },
        follow_redirects=False,
    )
    assert updated.status_code == 302
    db_session.refresh(document)
    assert document.content_version == 2
    assert document.indexed_version == 2
    assert document.index_status == "indexed"

    reindexed = client.post(
        f"/admin/knowledge/{document.id}/reindex",
        data={"csrf_token": token},
        follow_redirects=False,
    )
    assert reindexed.status_code == 302
    db_session.refresh(document)
    assert document.index_status == "indexed"
    assert document.indexed_version == 2

    deleted = client.post(
        f"/admin/knowledge/{document.id}/delete",
        data={"csrf_token": token},
        follow_redirects=False,
    )
    assert deleted.status_code == 302
    assert db_session.get(KnowledgeDocument, document.id) is None
    assert db_session.scalar(select(func.count(KnowledgeChunk.id))) == 0
