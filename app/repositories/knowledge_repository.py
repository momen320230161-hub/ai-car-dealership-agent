"""ORM and pgvector queries for managed dealership knowledge."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.rag.types import RetrievalResult


class KnowledgeRepository:
    """Persistence-only operations for documents, chunks, and vector retrieval."""

    def __init__(self, session: Session):
        self.session = session

    def get_document(self, document_id: uuid.UUID) -> KnowledgeDocument | None:
        return self.session.get(KnowledgeDocument, document_id)

    def get_document_for_update(self, document_id: uuid.UUID) -> KnowledgeDocument | None:
        return self.session.scalar(
            select(KnowledgeDocument).where(KnowledgeDocument.id == document_id).with_for_update()
        )

    def list_documents(
        self,
        *,
        category: str | None = None,
        active_only: bool = False,
        failed_only: bool = False,
    ) -> list[KnowledgeDocument]:
        statement = select(KnowledgeDocument)
        if category:
            statement = statement.where(
                func.lower(KnowledgeDocument.category) == category.strip().casefold()
            )
        if active_only:
            statement = statement.where(KnowledgeDocument.active.is_(True))
        if failed_only:
            statement = statement.where(KnowledgeDocument.index_status == "failed")
        statement = statement.order_by(KnowledgeDocument.title.asc(), KnowledgeDocument.id.asc())
        return list(self.session.scalars(statement))

    def delete_chunks(self, document_id: uuid.UUID) -> None:
        self.session.execute(
            delete(KnowledgeChunk).where(KnowledgeChunk.document_id == document_id)
        )

    def count_chunks(self, document_id: uuid.UUID) -> int:
        return self.session.scalar(
            select(func.count())
            .select_from(KnowledgeChunk)
            .where(KnowledgeChunk.document_id == document_id)
        )

    def search_similar(
        self,
        query_embedding: list[float],
        *,
        category: str | None,
        top_k: int,
        min_score: float | None,
    ) -> list[RetrievalResult]:
        """Execute cosine similarity in PostgreSQL against only current indexed chunks."""
        distance = KnowledgeChunk.embedding.cosine_distance(query_embedding)
        similarity = (1.0 - distance).label("similarity")
        statement = (
            select(KnowledgeDocument, KnowledgeChunk, similarity)
            .join(
                KnowledgeChunk,
                KnowledgeChunk.document_id == KnowledgeDocument.id,
            )
            .where(
                KnowledgeDocument.active.is_(True),
                KnowledgeDocument.index_status == "indexed",
                KnowledgeDocument.indexed_version == KnowledgeDocument.content_version,
                KnowledgeChunk.document_version == KnowledgeDocument.content_version,
            )
        )
        if category:
            statement = statement.where(
                func.lower(KnowledgeDocument.category) == category.strip().casefold()
            )
        if min_score is not None:
            statement = statement.where(distance <= 1.0 - min_score)
        statement = statement.order_by(
            distance.asc(),
            KnowledgeDocument.id.asc(),
            KnowledgeChunk.chunk_index.asc(),
        ).limit(top_k)

        return [
            RetrievalResult(
                document_id=document.id,
                title=document.title,
                category=document.category,
                chunk_id=chunk.id,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                similarity=float(score),
            )
            for document, chunk, score in self.session.execute(statement)
        ]
