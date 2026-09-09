"""Cosine semantic retrieval with document provenance."""

from dataclasses import dataclass
from uuid import UUID

from flask import current_app
from sqlalchemy import select

from app.extensions import db
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.services.embeddings import EmbeddingService


@dataclass(frozen=True)
class RetrievalResult:
    chunk_id: UUID
    document_id: UUID
    document_title: str
    category: str | None
    chunk_index: int
    content: str
    similarity: float
    source_type: str | None
    source_reference: str | None
    metadata: dict


class RetrievalService:
    def __init__(self, embedding_service=None, session=None):
        self.embedding_service = embedding_service or EmbeddingService()
        self.session = session or db.session
        self.default_top_k = current_app.config["RAG_DEFAULT_TOP_K"]
        self.max_top_k = current_app.config["RAG_MAX_TOP_K"]

    def search_knowledge(
        self, query: str, *, top_k: int | None = None, category: str | None = None,
        min_similarity: float | None = None,
    ) -> list[RetrievalResult]:
        top_k = self.default_top_k if top_k is None else top_k
        if not isinstance(top_k, int) or not 1 <= top_k <= self.max_top_k:
            raise ValueError(f"top_k must be between 1 and {self.max_top_k}")
        if min_similarity is not None and not -1.0 <= min_similarity <= 1.0:
            raise ValueError("min_similarity must be between -1 and 1")
        vector = self.embedding_service.embed_query(query)
        distance = KnowledgeChunk.embedding.cosine_distance(vector)
        statement = (
            select(KnowledgeChunk, KnowledgeDocument, distance.label("distance"))
            .join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id)
        )
        if category:
            statement = statement.where(KnowledgeDocument.category == category)
        if min_similarity is not None:
            statement = statement.where(distance <= 1.0 - min_similarity)
        rows = self.session.execute(statement.order_by(distance).limit(top_k)).all()
        return [self._result(chunk, document, float(raw_distance)) for chunk, document, raw_distance in rows]

    @staticmethod
    def _result(chunk, document, distance) -> RetrievalResult:
        return RetrievalResult(
            chunk_id=chunk.id, document_id=document.id, document_title=document.title,
            category=document.category, chunk_index=chunk.chunk_index, content=chunk.content,
            similarity=1.0 - distance, source_type=document.source_type,
            source_reference=document.source_reference,
            metadata={"document": document.document_metadata, "chunk": chunk.chunk_metadata},
        )
