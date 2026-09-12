"""Approved production knowledge seed validation and idempotency tests."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.models.knowledge import KnowledgeDocument
from app.rag.embeddings import DeterministicEmbeddingProvider
from app.services.knowledge_service import KnowledgeService
from app.services.knowledge_seed_service import KnowledgeSeedError, KnowledgeSeedService


def _write_seed(path, documents, *, status="approved_for_seed", version="1.0"):
    path.write_text(
        json.dumps(
            {
                "version": version,
                "status": status,
                "language": "ar-EG",
                "documents": documents,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _seed_service(db_session):
    knowledge = KnowledgeService(db_session, DeterministicEmbeddingProvider())
    return KnowledgeSeedService(knowledge)


def test_seed_file_creates_then_becomes_idempotent(db_session, tmp_path):
    path = tmp_path / "knowledge_seed.json"
    _write_seed(
        path,
        [
            {
                "title": "سياسة تجربة القيادة",
                "category": "Test Drive Policy",
                "content": "محتوى تجريبي معتمد للاختبار فقط.",
                "active": True,
            },
            {
                "title": "الضمان",
                "category": "Warranty",
                "content": "محتوى ضمان تجريبي للاختبار فقط.",
                "active": True,
            },
        ],
    )

    first = _seed_service(db_session).seed_file(path)
    assert first.total == 2
    assert first.created == 2
    assert first.updated == 0
    assert first.reindexed == 0
    assert first.unchanged == 0
    assert first.failed == 0

    second = _seed_service(db_session).seed_file(path)
    assert second.created == 0
    assert second.updated == 0
    assert second.reindexed == 0
    assert second.unchanged == 2
    assert second.failed == 0

    documents = list(db_session.scalars(select(KnowledgeDocument)))
    assert len(documents) == 2
    assert {document.category for document in documents} == {
        "test drive policy",
        "warranty",
    }
    assert all(document.index_status == "indexed" for document in documents)


def test_seed_content_change_updates_and_reindexes_current_version(db_session, tmp_path):
    path = tmp_path / "knowledge_seed.json"
    base = {
        "title": "معلومات التمويل",
        "category": "financing",
        "content": "الإصدار الأول من محتوى التمويل التجريبي.",
        "active": True,
    }
    _write_seed(path, [base])
    first = _seed_service(db_session).seed_file(path)
    assert first.created == 1

    base["content"] = "الإصدار الثاني من محتوى التمويل التجريبي بعد التحديث."
    _write_seed(path, [base], version="1.1")
    second = _seed_service(db_session).seed_file(path)

    assert second.version == "1.1"
    assert second.updated == 1
    assert second.failed == 0
    document = db_session.scalar(select(KnowledgeDocument))
    assert document.content_version == 2
    assert document.indexed_version == 2
    assert document.index_status == "indexed"
    assert document.content == base["content"]


def test_seed_repairs_matching_failed_document_by_reindexing(db_session, tmp_path):
    path = tmp_path / "knowledge_seed.json"
    document_payload = {
        "title": "معلومات الضمان",
        "category": "warranty",
        "content": "محتوى ثابت لإعادة الفهرسة.",
        "active": True,
    }
    _write_seed(path, [document_payload])
    service = _seed_service(db_session)
    assert service.seed_file(path).created == 1

    document = db_session.scalar(select(KnowledgeDocument))
    document.index_status = "failed"
    document.index_error = "synthetic failure"
    db_session.commit()

    repaired = _seed_service(db_session).seed_file(path)
    assert repaired.reindexed == 1
    assert repaired.failed == 0
    db_session.refresh(document)
    assert document.index_status == "indexed"
    assert document.indexed_version == document.content_version
    assert document.index_error is None


def test_seed_rejects_unapproved_or_duplicate_documents(db_session, tmp_path):
    path = tmp_path / "knowledge_seed.json"
    document = {
        "title": "FAQ",
        "category": "faq",
        "content": "Synthetic fixture",
        "active": True,
    }

    _write_seed(path, [document], status="draft_not_for_live_seed")
    with pytest.raises(KnowledgeSeedError, match="approved_for_seed"):
        _seed_service(db_session).seed_file(path)

    _write_seed(
        path,
        [
            document,
            {
                "title": " faq ",
                "category": "FAQ",
                "content": "Second synthetic fixture",
                "active": True,
            },
        ],
    )
    with pytest.raises(KnowledgeSeedError, match="duplicate title/category"):
        _seed_service(db_session).seed_file(path)
