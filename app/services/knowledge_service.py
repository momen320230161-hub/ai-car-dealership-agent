"""Managed knowledge CRUD with versioned, failure-visible vector indexing."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.rag.chunker import DeterministicChunker
from app.rag.embeddings import EmbeddingError, EmbeddingProvider, validate_embedding
from app.repositories.knowledge_repository import KnowledgeRepository


class KnowledgeServiceError(RuntimeError):
    """Base controlled error for managed knowledge operations."""


class KnowledgeNotFoundError(KnowledgeServiceError):
    pass


class KnowledgeIndexingError(KnowledgeServiceError):
    def __init__(self, message: str, *, document_id: uuid.UUID | None = None):
        super().__init__(message)
        self.document_id = document_id


class KnowledgePersistenceError(KnowledgeServiceError):
    pass


class KnowledgeDuplicateError(KnowledgeServiceError):
    """Raised when a PDF with the same SHA-256 hash already exists."""

    def __init__(self, message: str, *, existing_id: uuid.UUID | None = None):
        super().__init__(message)
        self.existing_id = existing_id


@dataclass(frozen=True, slots=True)
class ReindexReport:
    requested: int
    indexed: int
    failed: int
    errors: list[str] = field(default_factory=list)


class KnowledgeService:
    """Synchronize document state and current vector chunks without long DB transactions."""

    def __init__(
        self,
        session: Session,
        embedding_provider: EmbeddingProvider,
        *,
        chunker: DeterministicChunker | None = None,
    ):
        if embedding_provider.dimension != 768:
            raise KnowledgeIndexingError("Knowledge storage requires 768-dimensional embeddings")
        self.session = session
        self.provider = embedding_provider
        self.chunker = chunker or DeterministicChunker()
        self.repository = KnowledgeRepository(session)

    def create_document(
        self,
        *,
        title: str,
        category: str,
        content: str,
        active: bool = True,
        document_id: uuid.UUID | None = None,
        # Optional PDF provenance — all default to None for manual documents
        source_type: str | None = None,
        source_name: str | None = None,
        source_url: str | None = None,
        source_filename: str | None = None,
        source_sha256: str | None = None,
        source_mime_type: str | None = None,
        source_file_size: int | None = None,
        source_page_count: int | None = None,
        ingested_at: datetime | None = None,
        extraction_method: str | None = None,
    ) -> KnowledgeDocument:
        title = self._required_text(title, "title")
        category = self._normalize_category(category)
        content = self._required_text(content, "content")
        active = self._required_bool(active, "active")
        if document_id is not None and not isinstance(document_id, uuid.UUID):
            raise ValueError("document_id must be a UUID")

        # Duplicate PDF protection: reject if sha256 already exists
        if source_sha256:
            existing = self.repository.get_document_by_sha256(source_sha256)
            if existing is not None:
                raise KnowledgeDuplicateError(
                    f"ملف PDF بنفس الـ SHA-256 موجود بالفعل: {existing.title!r}",
                    existing_id=existing.id,
                )

        document = KnowledgeDocument(
            id=document_id or uuid.uuid4(),
            title=title,
            category=category,
            content=content,
            content_version=1,
            index_status="pending",
            active=active,
            source_type=source_type,
            source_name=source_name,
            source_url=source_url,
            source_filename=source_filename,
            source_sha256=source_sha256,
            source_mime_type=source_mime_type,
            source_file_size=source_file_size,
            source_page_count=source_page_count,
            ingested_at=ingested_at,
            extraction_method=extraction_method,
        )
        try:
            self.session.add(document)
            self.session.commit()
            persisted_document_id = document.id
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise KnowledgePersistenceError("Knowledge document could not be created") from exc
        return self._index_document(persisted_document_id, version=1, content=content)

    def update_document(
        self,
        document_id: uuid.UUID,
        *,
        title: str | None = None,
        category: str | None = None,
        content: str | None = None,
        active: bool | None = None,
    ) -> KnowledgeDocument:
        try:
            document = self.repository.get_document_for_update(document_id)
            if document is None:
                raise KnowledgeNotFoundError("Knowledge document was not found")
            if title is not None:
                document.title = self._required_text(title, "title")
            if category is not None:
                document.category = self._normalize_category(category)
            if active is not None:
                document.active = self._required_bool(active, "active")

            content_changed = False
            if content is not None:
                normalized_content = self._required_text(content, "content")
                content_changed = normalized_content != document.content
                if content_changed:
                    document.content = normalized_content
                    document.content_version += 1
                    document.index_status = "pending"
                    document.index_error = None
            version = document.content_version
            current_content = document.content
            self.session.commit()
        except (KnowledgeServiceError, ValueError):
            self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise KnowledgePersistenceError("Knowledge document could not be updated") from exc

        if not content_changed:
            return self._require_document(document_id)
        return self._index_document(document_id, version=version, content=current_content)

    def set_active(self, document_id: uuid.UUID, active: bool) -> KnowledgeDocument:
        return self.update_document(document_id, active=active)

    def delete_document(self, document_id: uuid.UUID) -> None:
        try:
            document = self.repository.get_document_for_update(document_id)
            if document is None:
                raise KnowledgeNotFoundError("Knowledge document was not found")
            self.session.delete(document)
            self.session.commit()
        except KnowledgeServiceError:
            self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise KnowledgePersistenceError("Knowledge document could not be deleted") from exc

    def reindex_document(self, document_id: uuid.UUID) -> KnowledgeDocument:
        try:
            document = self.repository.get_document_for_update(document_id)
            if document is None:
                raise KnowledgeNotFoundError("Knowledge document was not found")
            document.index_status = "pending"
            document.index_error = None
            version = document.content_version
            content = document.content
            self.session.commit()
        except KnowledgeServiceError:
            self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise KnowledgePersistenceError("Knowledge reindex could not be started") from exc
        return self._index_document(document_id, version=version, content=content)

    def reindex_all(self, *, failed_only: bool = False) -> ReindexReport:
        documents = self.repository.list_documents(failed_only=failed_only)
        document_ids = [document.id for document in documents]
        self.session.rollback()
        indexed = 0
        errors: list[str] = []
        for document_id in document_ids:
            try:
                self.reindex_document(document_id)
                indexed += 1
            except KnowledgeServiceError:
                errors.append(f"{document_id}: indexing failed")
        return ReindexReport(
            requested=len(document_ids),
            indexed=indexed,
            failed=len(errors),
            errors=errors,
        )

    def _index_document(
        self, document_id: uuid.UUID, *, version: int, content: str
    ) -> KnowledgeDocument:
        try:
            chunks = self.chunker.chunk(content)
            embeddings = self.provider.embed_texts(chunks)
            if len(embeddings) != len(chunks):
                raise EmbeddingError("Embedding provider returned an incomplete batch")
            vectors = [
                validate_embedding(embedding, self.provider.dimension) for embedding in embeddings
            ]
        except (EmbeddingError, ValueError) as exc:
            self._mark_failed(document_id, version, "Embedding generation failed")
            raise KnowledgeIndexingError(
                "Knowledge document indexing failed", document_id=document_id
            ) from exc

        try:
            document = self.repository.get_document_for_update(document_id)
            if document is None:
                raise KnowledgeNotFoundError("Knowledge document was not found")
            if document.content_version != version or document.content != content:
                raise KnowledgeIndexingError(
                    "Knowledge document changed during indexing", document_id=document_id
                )
            self.repository.delete_chunks(document_id)
            self.session.add_all(
                [
                    KnowledgeChunk(
                        document_id=document_id,
                        chunk_index=index,
                        document_version=version,
                        content=chunk,
                        content_hash=hashlib.sha256(chunk.encode("utf-8")).hexdigest(),
                        embedding=vector,
                        embedding_model=self.provider.model_name,
                    )
                    for index, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True))
                ]
            )
            self.session.flush()
            if not chunks:
                raise KnowledgeIndexingError(
                    "Knowledge document produced no chunks", document_id=document_id
                )
            document.index_status = "indexed"
            document.indexed_version = version
            document.indexed_at = datetime.now(UTC)
            document.index_error = None
            document.embedding_model = self.provider.model_name
            self.session.commit()
            return document
        except KnowledgeServiceError:
            self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            self.session.rollback()
            self._mark_failed(document_id, version, "Chunk persistence failed")
            raise KnowledgePersistenceError("Knowledge chunks could not be persisted") from exc

    def _mark_failed(self, document_id: uuid.UUID, version: int, message: str) -> None:
        try:
            document = self.repository.get_document_for_update(document_id)
            if document is not None and document.content_version == version:
                document.index_status = "failed"
                document.index_error = message
                self.session.commit()
            else:
                self.session.rollback()
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise KnowledgePersistenceError(
                "Knowledge failure state could not be recorded"
            ) from exc

    def _require_document(self, document_id: uuid.UUID) -> KnowledgeDocument:
        document = self.repository.get_document(document_id)
        if document is None:
            raise KnowledgeNotFoundError("Knowledge document was not found")
        return document

    @staticmethod
    def _required_text(value: Any, name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must not be blank")
        return value.strip()

    @classmethod
    def _normalize_category(cls, value: Any) -> str:
        return cls._required_text(value, "category").casefold()

    @staticmethod
    def _required_bool(value: Any, name: str) -> bool:
        if not isinstance(value, bool):
            raise ValueError(f"{name} must be a boolean")
        return value
