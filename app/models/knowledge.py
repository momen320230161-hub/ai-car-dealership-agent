"""Relational KnowledgeDocument model for dealership-owned knowledge."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, CheckConstraint, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import GUID, Base, TimestampMixin


class KnowledgeDocument(Base, TimestampMixin):
    """Approved FAQ, policy, warranty, financing, or dealership knowledge."""

    __tablename__ = "knowledge_documents"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default=text("true"),
        nullable=False,
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
        Index("ix_knowledge_documents_category", "category"),
        Index("ix_knowledge_documents_active", "active"),
        Index("ix_knowledge_documents_category_active", "category", "active"),
    )

    def __repr__(self) -> str:
        return f"<KnowledgeDocument id={self.id} title={self.title!r} category={self.category!r}>"
