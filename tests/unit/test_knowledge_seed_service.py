"""Approved production knowledge seed validation and idempotency tests."""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import select

from app.models.knowledge import KnowledgeDocument
from app.rag.embeddings import DeterministicEmbeddingProvider
from app.services.knowledge_seed_service import KnowledgeSeedError, KnowledgeSeedService
from app.services.knowledge_service import KnowledgeService


def _write_seed(path, documents, *, status="approved_for_seed", version="1.0"):
    normalized_documents = []
    for index, document in enumerate(documents):
        normalized = dict(document)
        normalized.setdefault(
            "id",
            str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"autodrive-seed-test:{index}:{normalized.get('title', '')}",
                )
            ),
        )
        normalized_documents.append(normalized)
    path.write_text(
        json.dumps(
            {
                "version": version,
                "status": status,
                "language": "ar-EG",
                "documents": normalized_documents,
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
    document_id = uuid.uuid4()
    base = {
        "id": str(document_id),
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
    document = db_session.get(KnowledgeDocument, document_id)
    assert document.content_version == 2
    assert document.indexed_version == 2
    assert document.index_status == "indexed"
    assert document.content == base["content"]


def test_seed_stable_id_allows_title_change_without_duplicate(db_session, tmp_path):
    path = tmp_path / "knowledge_seed.json"
    document_id = uuid.uuid4()
    payload = {
        "id": str(document_id),
        "title": "عنوان أول",
        "category": "faq",
        "content": "محتوى ثابت للاختبار.",
        "active": True,
    }
    _write_seed(path, [payload])
    assert _seed_service(db_session).seed_file(path).created == 1

    payload["title"] = "عنوان محدث"
    _write_seed(path, [payload])
    report = _seed_service(db_session).seed_file(path)

    assert report.updated == 1
    assert report.created == 0
    documents = list(db_session.scalars(select(KnowledgeDocument)))
    assert len(documents) == 1
    assert documents[0].id == document_id
    assert documents[0].title == "عنوان محدث"
    assert documents[0].content_version == 1


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


def test_seed_rejects_missing_or_invalid_document_id(db_session, tmp_path):
    path = tmp_path / "knowledge_seed.json"
    path.write_text(
        json.dumps(
            {
                "version": "1.0",
                "status": "approved_for_seed",
                "documents": [
                    {
                        "title": "FAQ",
                        "category": "faq",
                        "content": "Synthetic fixture",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(KnowledgeSeedError, match="UUID string"):
        _seed_service(db_session).seed_file(path)
