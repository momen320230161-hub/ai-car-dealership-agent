"""RAG service validation, structured output, and controlled failure tests."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.rag.embeddings import DeterministicEmbeddingProvider, EmbeddingError
from app.rag.types import RetrievalResult
from app.services.rag_service import RAGRetrievalError, RAGService


class StubRepository:
    def __init__(self, results=None, error=None):
        self.results = results or []
        self.error = error
        self.call = None

    def search_similar(self, embedding, *, category, top_k, min_score):
        if self.error:
            raise self.error
        self.call = {
            "embedding": embedding,
            "category": category,
            "top_k": top_k,
            "min_score": min_score,
        }
        return self.results


class FailingQueryProvider(DeterministicEmbeddingProvider):
    def embed_text(self, text):
        del text
        raise EmbeddingError("synthetic query failure")


def test_retrieve_returns_structured_results_and_normalizes_options(db_session):
    expected = RetrievalResult(
        document_id=uuid.uuid4(),
        title="Test FAQ",
        category="faq",
        chunk_id=7,
        chunk_index=0,
        content="Synthetic answer text",
        similarity=0.875,
    )
    service = RAGService(db_session, DeterministicEmbeddingProvider())
    repository = StubRepository([expected])
    service.repository = repository

    results = service.retrieve("synthetic answer", category=" FAQ ", top_k=2, min_score=0.2)

    assert results == [expected]
    assert repository.call["category"] == "faq"
    assert repository.call["top_k"] == 2
    assert repository.call["min_score"] == 0.2
    assert len(repository.call["embedding"]) == 768


@pytest.mark.parametrize("top_k", [0, -1, 21, True, 1.5])
def test_top_k_is_strictly_bounded(db_session, top_k):
    with pytest.raises(ValueError, match="top_k must be between"):
        RAGService(db_session, DeterministicEmbeddingProvider()).retrieve("query", top_k=top_k)


def test_blank_query_and_invalid_min_score_are_rejected(db_session):
    service = RAGService(db_session, DeterministicEmbeddingProvider())
    with pytest.raises(ValueError, match="must not be blank"):
        service.retrieve("  ")
    with pytest.raises(ValueError, match="between -1 and 1"):
        service.retrieve("query", min_score=1.1)


def test_no_indexed_documents_returns_empty_list(db_session):
    service = RAGService(db_session, DeterministicEmbeddingProvider())
    service.repository = StubRepository([])
    assert service.retrieve("nothing indexed") == []


def test_embedding_and_database_failures_are_controlled(db_session):
    with pytest.raises(RAGRetrievalError, match="query embedding failed"):
        RAGService(db_session, FailingQueryProvider()).retrieve("query")

    service = RAGService(db_session, DeterministicEmbeddingProvider())
    service.repository = StubRepository(error=SQLAlchemyError("database unavailable"))
    with pytest.raises(RAGRetrievalError, match="database retrieval failed"):
        service.retrieve("query")
