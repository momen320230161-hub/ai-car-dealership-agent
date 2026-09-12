"""Independent retrieval-augmented-generation foundations (without an LLM orchestrator)."""

from app.rag.chunker import DeterministicChunker
from app.rag.embeddings import (
    DeterministicEmbeddingProvider,
    EmbeddingError,
    EmbeddingProvider,
    GeminiEmbeddingProvider,
    build_embedding_provider,
    validate_embedding,
)
from app.rag.types import RetrievalResult

__all__ = [
    "DeterministicChunker",
    "DeterministicEmbeddingProvider",
    "EmbeddingError",
    "EmbeddingProvider",
    "GeminiEmbeddingProvider",
    "RetrievalResult",
    "build_embedding_provider",
    "validate_embedding",
]
