"""Structured pgvector retrieval independent of LangGraph and response generation."""

from __future__ import annotations

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.rag.embeddings import EmbeddingError, EmbeddingProvider, validate_embedding
from app.rag.types import RetrievalResult
from app.repositories.knowledge_repository import KnowledgeRepository


class RAGRetrievalError(RuntimeError):
    """Controlled query-embedding or database retrieval failure."""


class RAGService:
    def __init__(
        self,
        session: Session,
        embedding_provider: EmbeddingProvider,
        *,
        default_top_k: int = 4,
        max_top_k: int = 20,
        default_min_score: float | None = None,
    ):
        if embedding_provider.dimension != 768:
            raise RAGRetrievalError("Knowledge retrieval requires 768-dimensional embeddings")
        if not 1 <= default_top_k <= max_top_k:
            raise ValueError("default_top_k must be within the allowed range")
        self.session = session
        self.provider = embedding_provider
        self.repository = KnowledgeRepository(session)
        self.default_top_k = default_top_k
        self.max_top_k = max_top_k
        self.default_min_score = self._validate_score(default_min_score)

    def retrieve(
        self,
        query: str,
        *,
        category: str | None = None,
        top_k: int | None = None,
        min_score: float | None = None,
    ) -> list[RetrievalResult]:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("RAG query must not be blank")
        resolved_top_k = self.default_top_k if top_k is None else top_k
        if (
            isinstance(resolved_top_k, bool)
            or not isinstance(resolved_top_k, int)
            or not 1 <= resolved_top_k <= self.max_top_k
        ):
            raise ValueError(f"top_k must be between 1 and {self.max_top_k}")
        resolved_score = (
            self.default_min_score if min_score is None else self._validate_score(min_score)
        )
        normalized_category = category.strip().casefold() if category and category.strip() else None
        try:
            embedding = validate_embedding(
                self.provider.embed_text(query.strip()), self.provider.dimension
            )
        except EmbeddingError as exc:
            raise RAGRetrievalError("RAG query embedding failed") from exc
        try:
            return self.repository.search_similar(
                embedding,
                category=normalized_category,
                top_k=resolved_top_k,
                min_score=resolved_score,
            )
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise RAGRetrievalError("RAG database retrieval failed") from exc

    @staticmethod
    def _validate_score(value: float | None) -> float | None:
        if value is None:
            return None
        score = float(value)
        if not -1.0 <= score <= 1.0:
            raise ValueError("min_score must be between -1 and 1")
        return score
