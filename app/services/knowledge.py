"""Transactional knowledge-document lifecycle management."""

from uuid import UUID

from flask import current_app
from sqlalchemy import select

from app.extensions import db
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.services.chunking import chunk_text, content_hash, normalize_content
from app.services.embeddings import EmbeddingService


class KnowledgeError(ValueError):
    pass


class KnowledgeNotFoundError(KnowledgeError):
    pass


class KnowledgeService:
    def __init__(self, embedding_service=None, session=None):
        self.embedding_service = embedding_service or EmbeddingService()
        self.session = session or db.session
        self.chunk_size = current_app.config["RAG_CHUNK_SIZE"]
        self.chunk_overlap = current_app.config["RAG_CHUNK_OVERLAP"]

    def create_document(
        self, *, title: str, content: str, category: str | None = None,
        source_type: str | None = None, source_reference: str | None = None,
        metadata: dict | None = None,
    ) -> KnowledgeDocument:
        title = self._title(title)
        normalized = normalize_content(content)
        chunks = chunk_text(normalized, chunk_size=self.chunk_size, overlap=self.chunk_overlap)
        vectors = self.embedding_service.embed_documents(chunks)
        document = KnowledgeDocument(
            title=title, content=normalized, category=self._optional(category),
            source_type=self._optional(source_type), source_reference=self._optional(source_reference),
            content_hash=content_hash(normalized), document_metadata=dict(metadata or {}),
        )
        document.chunks = self._chunks(chunks, vectors)
        try:
            self.session.add(document)
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        return document

    def update_document(self, document_id: UUID | str, **changes) -> KnowledgeDocument:
        document = self.get_document(document_id)
        new_content = changes.pop("content", None)
        if new_content is not None:
            normalized = normalize_content(new_content)
            new_hash = content_hash(normalized)
        else:
            normalized, new_hash = document.content, document.content_hash

        replacements = None
        if new_hash != document.content_hash:
            chunk_contents = chunk_text(
                normalized, chunk_size=self.chunk_size, overlap=self.chunk_overlap
            )
            vectors = self.embedding_service.embed_documents(chunk_contents)
            replacements = self._chunks(chunk_contents, vectors)

        for field in ("title", "category", "source_type", "source_reference"):
            if field in changes:
                value = changes[field]
                setattr(document, field, self._title(value) if field == "title" else self._optional(value))
        if "metadata" in changes:
            document.document_metadata = dict(changes["metadata"] or {})
        if replacements is not None:
            document.content = normalized
            document.content_hash = new_hash
            document.chunks.clear()
            self.session.flush()
            document.chunks.extend(replacements)
        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        return document

    def delete_document(self, document_id: UUID | str) -> None:
        document = self.get_document(document_id)
        try:
            self.session.delete(document)
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

    def get_document(self, document_id: UUID | str) -> KnowledgeDocument:
        try:
            identifier = UUID(str(document_id))
        except ValueError as error:
            raise KnowledgeNotFoundError("invalid knowledge document identifier") from error
        document = self.session.get(KnowledgeDocument, identifier)
        if document is None:
            raise KnowledgeNotFoundError("knowledge document not found")
        return document

    def list_documents(self) -> list[KnowledgeDocument]:
        return list(self.session.scalars(select(KnowledgeDocument).order_by(KnowledgeDocument.created_at)))

    def _chunks(self, contents, vectors):
        return [
            KnowledgeChunk(
                chunk_index=index, content=content, content_hash=content_hash(content),
                embedding=vector, embedding_model=self.embedding_service.model,
                embedding_dimensions=self.embedding_service.dimensions,
                character_count=len(content), chunk_metadata={},
            )
            for index, (content, vector) in enumerate(zip(contents, vectors, strict=True))
        ]

    @staticmethod
    def _title(value):
        value = value.strip() if isinstance(value, str) else ""
        if not value or len(value) > 255:
            raise KnowledgeError("title must contain 1-255 characters")
        return value

    @staticmethod
    def _optional(value):
        return value.strip() if isinstance(value, str) and value.strip() else None
