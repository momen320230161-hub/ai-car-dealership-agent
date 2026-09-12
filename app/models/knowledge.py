"""Relational KnowledgeDocument model for dealership-owned knowledge."""

from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import GUID, Base, TimestampMixin


class KnowledgeDocument(Base, TimestampMixin):
    """Approved FAQ, policy, warranty, financing, or dealership knowledge."""

    __tablename__ = "knowledge_documents"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_version: Mapped[int] = mapped_column(
        Integer, default=1, server_default=text("1"), nullable=False
    )
    index_status: Mapped[str] = mapped_column(
        String(20), default="pending", server_default="pending", nullable=False
    )
    indexed_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    index_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default=text("true"),
        nullable=False,
    )
    chunks: Mapped[list[KnowledgeChunk]] = relationship(
        "KnowledgeChunk",
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="KnowledgeChunk.chunk_index",
    )

    __table_args__ = (
        CheckConstraint(
            "length(trim(title)) > 0",
            name="knowledge_document_title_not_blank_check",
        ),
        CheckConstraint(
            "length(trim(category)) > 0",
            name="knowledge_document_category_not_blank_check",
        ),
        CheckConstraint(
            "length(trim(content)) > 0",
            name="knowledge_document_content_not_blank_check",
        ),
        CheckConstraint(
            "content_version > 0",
            name="knowledge_document_content_version_positive_check",
        ),
        CheckConstraint(
            "indexed_version IS NULL OR indexed_version > 0",
            name="knowledge_document_indexed_version_positive_check",
        ),
        CheckConstraint(
            "index_status IN ('pending', 'indexed', 'failed')",
            name="knowledge_document_index_status_check",
        ),
        Index("ix_knowledge_documents_category", "category"),
        Index("ix_knowledge_documents_active", "active"),
        Index("ix_knowledge_documents_category_active", "category", "active"),
        Index(
            "ix_knowledge_documents_retrieval_state",
            "active",
            "index_status",
            "indexed_version",
            "content_version",
        ),
    )

    def __repr__(self) -> str:
        return f"<KnowledgeDocument id={self.id} title={self.title!r} category={self.category!r}>"


class KnowledgeChunk(Base):
    """One deterministic, versioned pgvector chunk for a knowledge document."""

    __tablename__ = "knowledge_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        ForeignKey(
            "knowledge_documents.id",
            ondelete="CASCADE",
            name="fk_knowledge_chunks_document_id_knowledge_documents",
        ),
        nullable=False,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    document_version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding: Mapped[list[float]] = mapped_column(VECTOR(768), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    document: Mapped[KnowledgeDocument] = relationship(
        "KnowledgeDocument", back_populates="chunks"
    )

    __table_args__ = (
        CheckConstraint("chunk_index >= 0", name="knowledge_chunk_index_non_negative_check"),
        CheckConstraint(
            "document_version > 0", name="knowledge_chunk_document_version_positive_check"
        ),
        CheckConstraint(
            "length(trim(content)) > 0", name="knowledge_chunk_content_not_blank_check"
        ),
        CheckConstraint(
            "length(content_hash) = 64", name="knowledge_chunk_content_hash_length_check"
        ),
        CheckConstraint(
            "length(trim(embedding_model)) > 0",
            name="knowledge_chunk_embedding_model_not_blank_check",
        ),
        Index("ix_knowledge_chunks_document_id", "document_id"),
        Index(
            "ix_knowledge_chunks_document_version",
            "document_id",
            "document_version",
            unique=False,
        ),
        Index(
            "uq_knowledge_chunks_document_version_index",
            "document_id",
            "document_version",
            "chunk_index",
            unique=True,
        ),
        Index(
            "ix_knowledge_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<KnowledgeChunk id={self.id} document_id={self.document_id} "
            f"version={self.document_version} index={self.chunk_index}>"
        )
