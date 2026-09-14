"""Managed knowledge lifecycle and indexing-failure unit tests."""

from __future__ import annotations

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.exc import SQLAlchemyError

from app.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.rag.embeddings import DeterministicEmbeddingProvider, EmbeddingError
from app.services.knowledge_service import (
    KnowledgeIndexingError,
    KnowledgePersistenceError,
    KnowledgeService,
)


class CountingProvider(DeterministicEmbeddingProvider):
    def __init__(self):
        super().__init__()
        self.batch_calls = 0

    def embed_texts(self, texts):
        self.batch_calls += 1
        return super().embed_texts(texts)


class FailingProvider(DeterministicEmbeddingProvider):
    def embed_texts(self, texts):
        del texts
        raise EmbeddingError("synthetic provider outage")


class PartialProvider(DeterministicEmbeddingProvider):
    def embed_texts(self, texts):
        return super().embed_texts(texts)[:-1]


class WrongDimensionOutputProvider(DeterministicEmbeddingProvider):
    def embed_texts(self, texts):
        return [[0.0, 1.0] for _ in texts]


def test_create_indexes_document_and_update_replaces_old_chunks(db_session):
    service = KnowledgeService(db_session, DeterministicEmbeddingProvider())
    document = service.create_document(
        title="Test Drive Policy",
        category=" Test Drive Policy ",
        content="Phase3 verification policy alpha",
    )

    assert document.index_status == "indexed"
    assert document.content_version == document.indexed_version == 1
    assert document.category == "test drive policy"
    assert len(document.chunks) == 1
    assert len(document.chunks[0].embedding) == 768

    updated = service.update_document(document.id, content="Phase3 verification policy beta")
    chunks = list(
        db_session.scalars(select(KnowledgeChunk).where(KnowledgeChunk.document_id == document.id))
    )
    assert updated.content_version == updated.indexed_version == 2
    assert updated.index_status == "indexed"
    assert [chunk.content for chunk in chunks] == ["Phase3 verification policy beta"]


def test_metadata_only_and_noop_updates_do_not_reembed(db_session):
    provider = CountingProvider()
    service = KnowledgeService(db_session, provider)
    document = service.create_document(
        title="FAQ", category="faq", content="Synthetic test content"
    )
    assert provider.batch_calls == 1

    updated = service.update_document(
        document.id,
        title="Updated FAQ title",
        category="FAQ",
        content="Synthetic test content",
    )

    assert provider.batch_calls == 1
    assert updated.content_version == 1
    assert updated.index_status == "indexed"


@pytest.mark.parametrize("field", ["title", "category", "content"])
def test_create_validates_required_text(db_session, field):
    values = {"title": "FAQ", "category": "faq", "content": "Test fixture"}
    values[field] = "   "
    with pytest.raises(ValueError, match=f"{field} must not be blank"):
        KnowledgeService(db_session, DeterministicEmbeddingProvider()).create_document(**values)


@pytest.mark.parametrize(
    "provider",
    [FailingProvider(), PartialProvider(), WrongDimensionOutputProvider()],
)
def test_embedding_failures_persist_failed_state_without_current_chunks(db_session, provider):
    service = KnowledgeService(db_session, provider)
    with pytest.raises(KnowledgeIndexingError) as error:
        service.create_document(
            title="Synthetic", category="faq", content="Synthetic failure fixture"
        )

    document = db_session.get(KnowledgeDocument, error.value.document_id)
    assert document.index_status == "failed"
    assert document.index_error == "Embedding generation failed"
    assert document.indexed_version is None
    assert db_session.scalar(select(func.count()).select_from(KnowledgeChunk)) == 0


def test_failed_content_update_keeps_old_chunks_but_makes_them_stale(db_session):
    service = KnowledgeService(db_session, DeterministicEmbeddingProvider())
    document = service.create_document(
        title="Synthetic", category="faq", content="Indexed version alpha"
    )
    service.provider = FailingProvider()

    with pytest.raises(KnowledgeIndexingError):
        service.update_document(document.id, content="Failed version beta")

    db_session.refresh(document)
    chunks = list(
        db_session.scalars(select(KnowledgeChunk).where(KnowledgeChunk.document_id == document.id))
    )
    assert document.content_version == 2
    assert document.indexed_version == 1
    assert document.index_status == "failed"
    assert [chunk.content for chunk in chunks] == ["Indexed version alpha"]
    assert all(chunk.document_version != document.content_version for chunk in chunks)


def test_wrong_provider_dimension_is_rejected_before_database_work(db_session):
    with pytest.raises(KnowledgeIndexingError, match="768-dimensional"):
        KnowledgeService(db_session, DeterministicEmbeddingProvider(dimension=32))


def test_chunk_database_failure_rolls_back_and_records_failed_state(db_session):
    actual_session = db_session()
    failed_once = False

    def fail_chunk_flush(session, flush_context, instances):
        del flush_context, instances
        nonlocal failed_once
        if not failed_once and any(isinstance(item, KnowledgeChunk) for item in session.new):
            failed_once = True
            raise SQLAlchemyError("synthetic chunk failure")

    event.listen(actual_session, "before_flush", fail_chunk_flush)
    service = KnowledgeService(actual_session, DeterministicEmbeddingProvider())

    with pytest.raises(KnowledgePersistenceError):
        service.create_document(
            title="Synthetic", category="faq", content="Database failure fixture"
        )

    document = actual_session.scalar(select(KnowledgeDocument))
    assert document.index_status == "failed"
    assert document.index_error == "Chunk persistence failed"
    assert actual_session.scalar(select(func.count()).select_from(KnowledgeChunk)) == 0


def test_deactivate_reactivate_reindex_and_delete_are_predictable(db_session):
    service = KnowledgeService(db_session, DeterministicEmbeddingProvider())
    document = service.create_document(
        title="FAQ", category="faq", content="Synthetic lifecycle fixture"
    )
    chunk_count = service.repository.count_chunks(document.id)
    assert chunk_count == 1

    assert service.set_active(document.id, False).active is False
    assert service.set_active(document.id, True).index_status == "indexed"
    reindexed = service.reindex_document(document.id)
    assert reindexed.index_status == "indexed"
    assert service.repository.count_chunks(document.id) == chunk_count

    service.delete_document(document.id)
    assert db_session.get(KnowledgeDocument, document.id) is None
    assert db_session.scalar(select(func.count()).select_from(KnowledgeChunk)) == 0
