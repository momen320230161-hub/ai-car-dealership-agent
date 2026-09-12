"""Stable structured return types for retrieval."""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    document_id: uuid.UUID
    title: str
    category: str
    chunk_id: int
    chunk_index: int
    content: str
    similarity: float
