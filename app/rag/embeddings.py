"""Configurable embedding providers and strict dimension validation."""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any, Protocol


class EmbeddingError(RuntimeError):
    """Controlled embedding configuration, request, or output failure."""


class EmbeddingProvider(Protocol):
    dimension: int
    model_name: str

    def embed_text(self, text: str) -> list[float]: ...

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]: ...


def validate_embedding(values: Sequence[float], dimension: int) -> list[float]:
    if len(values) != dimension:
        raise EmbeddingError(
            f"Embedding dimension mismatch: expected {dimension}, received {len(values)}"
        )
    try:
        vector = [float(value) for value in values]
    except (TypeError, ValueError) as exc:
        raise EmbeddingError("Embedding contains a non-numeric value") from exc
    if not all(math.isfinite(value) for value in vector):
        raise EmbeddingError("Embedding contains a non-finite value")
    return vector


class DeterministicEmbeddingProvider:
    """Offline token-hash embeddings for reliable tests, never production fallback."""

    def __init__(self, *, dimension: int = 768, model_name: str = "deterministic-test-v1"):
        if dimension <= 0:
            raise ValueError("Embedding dimension must be positive")
        self.dimension = dimension
        self.model_name = model_name

    def embed_text(self, text: str) -> list[float]:
        if not isinstance(text, str) or not text.strip():
            raise EmbeddingError("Text to embed must not be blank")
        vector = [0.0] * self.dimension
        tokens = re.findall(r"\w+", text.casefold(), flags=re.UNICODE)
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            for offset in (0, 4, 8):
                index = int.from_bytes(digest[offset : offset + 4], "big") % self.dimension
                sign = 1.0 if digest[offset + 12] % 2 == 0 else -1.0
                vector[index] += sign
        magnitude = math.sqrt(sum(value * value for value in vector))
        if magnitude == 0:
            raise EmbeddingError("Text to embed produced no tokens")
        return [value / magnitude for value in vector]

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        return [self.embed_text(text) for text in texts]


class GeminiEmbeddingProvider:
    """Production adapter for the official Google Gen AI Python SDK."""

    def __init__(self, *, api_key: str | None, model_name: str, dimension: int = 768):
        self.api_key = api_key
        self.model_name = model_name
        self.dimension = dimension

    def embed_text(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        if not self.api_key:
            raise EmbeddingError("Gemini embedding credentials are not configured")
        if not texts or any(not isinstance(text, str) or not text.strip() for text in texts):
            raise EmbeddingError("Text to embed must not be blank")
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=self.api_key)
            # Gemini Embedding 2 aggregates multiple raw parts into one embedding.
            # Wrap each text in its own Content so one chunk always maps to one vector.
            contents = [types.Content(parts=[types.Part.from_text(text=text)]) for text in texts]
            response = client.models.embed_content(
                model=self.model_name,
                contents=contents,
                config=types.EmbedContentConfig(output_dimensionality=self.dimension),
            )
            embeddings = response.embeddings or []
            if len(embeddings) != len(texts):
                raise EmbeddingError("Gemini embedding response count does not match input count")
            return [
                validate_embedding(embedding.values or [], self.dimension)
                for embedding in embeddings
            ]
        except EmbeddingError:
            raise
        except Exception as exc:
            raise EmbeddingError("Gemini embedding request failed") from exc


def build_embedding_provider(config: Mapping[str, Any]) -> EmbeddingProvider:
    provider_name = str(config.get("EMBEDDING_PROVIDER", "gemini")).strip().lower()
    try:
        dimension = int(config.get("EMBEDDING_DIMENSION", 768))
    except (TypeError, ValueError) as exc:
        raise EmbeddingError("EMBEDDING_DIMENSION must be an integer") from exc
    model_name = str(config.get("EMBEDDING_MODEL", "gemini-embedding-2")).strip()
    if dimension != 768:
        raise EmbeddingError("The database schema requires EMBEDDING_DIMENSION=768")
    if provider_name == "gemini":
        return GeminiEmbeddingProvider(
            api_key=config.get("GEMINI_API_KEY"),
            model_name=model_name,
            dimension=dimension,
        )
    if provider_name == "deterministic":
        return DeterministicEmbeddingProvider(dimension=dimension, model_name=model_name)
    raise EmbeddingError(f"Unsupported embedding provider: {provider_name}")
