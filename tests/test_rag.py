from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.extensions import db
from app.models import KnowledgeChunk, KnowledgeDocument
from app.services.chunking import ChunkingError, chunk_text, content_hash, normalize_content
from app.services.embeddings import (
    EmbeddingAPIError,
    EmbeddingService,
    EmbeddingValidationError,
)
from app.services.knowledge import KnowledgeService
from app.services.retrieval import RetrievalService


class FakeEmbeddingService:
    model = "gemini-embedding-2"
    dimensions = 768

    def __init__(self):
        self.document_calls = 0

    def embed_documents(self, texts):
        self.document_calls += 1
        return [[float(index % 7) for index in range(768)] for _ in texts]

    def embed_query(self, _text):
        return [0.0] * 768


class SDKClient:
    def __init__(self, side_effects):
        self.calls = 0
        self.side_effects = list(side_effects)
        self.models = self

    def embed_content(self, **_kwargs):
        self.calls += 1
        outcome = self.side_effects.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(
            embeddings=[SimpleNamespace(values=vector) for vector in outcome]
        )


class APIException(Exception):
    def __init__(self, code):
        super().__init__(f"status {code}")
        self.code = code


def test_chunking_rejects_empty_and_is_deterministic():
    with pytest.raises(ChunkingError):
        chunk_text("  \n\n  ")
    text = "First paragraph has useful words.\n\nSecond paragraph also has useful words."
    assert chunk_text(text, chunk_size=45, overlap=10) == chunk_text(
        text, chunk_size=45, overlap=10
    )


def test_chunking_preserves_order_overlap_and_no_empty_chunks():
    text = " ".join(f"word{index}" for index in range(60))
    chunks = chunk_text(text, chunk_size=90, overlap=20)
    assert len(chunks) > 1
    assert all(chunk.strip() and len(chunk) <= 90 for chunk in chunks)
    assert set(chunks[0].split()) & set(chunks[1].split())
    assert chunks[0].startswith("word0")


def test_content_hash_uses_normalized_content():
    assert content_hash("Alpha   beta\n\nGamma") == content_hash("Alpha beta\n\nGamma")
    assert content_hash("Alpha beta") != content_hash("Alpha changed")
    assert normalize_content(" A   B \n\n C ") == "A B\n\nC"


def test_embedding_validation(app):
    service = EmbeddingService(api_key="test", client=SDKClient([]), sleep=lambda _: None)
    with pytest.raises(EmbeddingValidationError):
        service.validate_vectors([[0.0] * 767], 1)
    with pytest.raises(EmbeddingValidationError):
        service.validate_vectors([[float("nan")] * 768], 1)
    with pytest.raises(EmbeddingValidationError):
        service.validate_vectors([], 1)


def test_embedding_batch_mapping_and_transient_retry(app):
    good = [[0.1] * 768]
    client = SDKClient([APIException(503), good])
    service = EmbeddingService(
        api_key="test", client=client, batch_size=1, sleep=lambda _: None
    )
    assert len(service.embed_documents(["one"])[0]) == 768
    assert client.calls == 2


def test_embedding_non_transient_error_is_not_retried(app):
    client = SDKClient([APIException(403)])
    service = EmbeddingService(api_key="test", client=client, sleep=lambda _: None)
    with pytest.raises(EmbeddingAPIError) as raised:
        service.embed_query("query")
    assert raised.value.category == "permission"
    assert client.calls == 1


def test_knowledge_create_metadata_update_and_delete(app):
    embeddings = FakeEmbeddingService()
    service = KnowledgeService(embedding_service=embeddings)
    document = service.create_document(
        title="Synthetic fixture", content="Synthetic content only.",
        category="test", metadata={"synthetic": True},
    )
    assert len(document.chunks) == 1
    assert document.chunks[0].embedding_dimensions == 768
    initial_hash = document.content_hash
    initial_chunk_id = document.chunks[0].id
    service.update_document(document.id, title="Renamed fixture", metadata={"version": 2})
    assert embeddings.document_calls == 1
    assert document.content_hash == initial_hash
    assert document.chunks[0].id == initial_chunk_id
    service.delete_document(document.id)
    assert db.session.get(KnowledgeDocument, document.id) is None
    assert db.session.scalar(db.select(db.func.count()).select_from(KnowledgeChunk)) == 0


def test_changed_content_replaces_chunks(app):
    embeddings = FakeEmbeddingService()
    service = KnowledgeService(embedding_service=embeddings)
    document = service.create_document(title="Synthetic fixture", content="Old synthetic text.")
    old_hash, old_chunk = document.content_hash, document.chunks[0].id
    service.update_document(document.id, content="New synthetic text with a different subject.")
    assert embeddings.document_calls == 2
    assert document.content_hash != old_hash
    assert document.chunks[0].id != old_chunk


def test_normalized_equivalent_content_avoids_reembedding(app):
    embeddings = FakeEmbeddingService()
    service = KnowledgeService(embedding_service=embeddings)
    document = service.create_document(title="Synthetic fixture", content="Same normalized text.")
    original_chunk_id = document.chunks[0].id
    service.update_document(document.id, content="  Same   normalized text.  ")
    assert embeddings.document_calls == 1
    assert document.chunks[0].id == original_chunk_id


def test_embedding_failure_preserves_working_document(app):
    embeddings = FakeEmbeddingService()
    service = KnowledgeService(embedding_service=embeddings)
    document = service.create_document(title="Synthetic fixture", content="Stable content.")
    old_hash, old_content = document.content_hash, document.content
    embeddings.embed_documents = lambda _texts: (_ for _ in ()).throw(EmbeddingAPIError("quota/rate-limit", 429))
    with pytest.raises(EmbeddingAPIError):
        service.update_document(document.id, content="Replacement that cannot be embedded.")
    db.session.refresh(document)
    assert (document.content_hash, document.content) == (old_hash, old_content)


def test_retrieval_result_similarity_and_top_k_bound(app):
    service = RetrievalService(embedding_service=FakeEmbeddingService())
    with pytest.raises(ValueError):
        service.search_knowledge("query", top_k=service.max_top_k + 1)
    document = SimpleNamespace(
        id=uuid4(), title="Fixture", category="test", source_type="internal",
        source_reference="fixture", document_metadata={"synthetic": True},
    )
    chunk = SimpleNamespace(
        id=uuid4(), chunk_index=0, content="Synthetic", chunk_metadata={}
    )
    result = service._result(chunk, document, 0.2)
    assert result.similarity == pytest.approx(0.8)
    assert result.document_title == "Fixture"
    assert result.metadata["document"]["synthetic"] is True
