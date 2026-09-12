"""Relational KnowledgeDocument model for dealership knowledge base."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import GUID, Base, TimestampMixin


class KnowledgeDocument(Base, TimestampMixin):
    """Represents approved unstructured dealership knowledge (FAQs, policies, guides)."""

    __tablename__ = "knowledge_documents"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), nullable=False
    )

    __table_args__ = (
        Index("ix_knowledge_documents_category", "category"),
        Index("ix_knowledge_documents_active", "active"),
        Index("ix_knowledge_documents_category_active", "category", "active"),
    )

    def __repr__(self) -> str:
        return f"<KnowledgeDocument id={self.id} title={self.title!r} category={self.category!r}>"
