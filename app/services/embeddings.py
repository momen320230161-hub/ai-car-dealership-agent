"""Validated Gemini embeddings for documents and retrieval queries."""

import math
import time
from collections.abc import Callable, Sequence

from flask import current_app
from google import genai
from google.genai import types


class EmbeddingError(RuntimeError):
    pass


class EmbeddingConfigurationError(EmbeddingError):
    pass


class EmbeddingAPIError(EmbeddingError):
    def __init__(self, category: str, code=None):
        super().__init__(f"Gemini embedding request failed: {category}")
        self.category = category
        self.code = code


class EmbeddingValidationError(EmbeddingError):
    pass


def _error_code(error):
    return getattr(error, "code", None) or getattr(error, "status_code", None)


def _classify(error) -> str:
    code = _error_code(error)
    message = str(error).lower()
    if code == 401 or "unauthenticated" in message or "api key" in message:
        return "authentication"
    if code == 403 or "permission_denied" in message:
        return "permission"
    if code == 429 or "quota" in message or "rate limit" in message:
        return "quota/rate-limit"
    if code == 503:
        return "service-unavailable"
    if code == 504:
        return "deadline-exceeded"
    if code == 404 or "model" in message and "not found" in message:
        return "invalid-model"
    if code == 400 or "invalid_argument" in message:
        return "invalid-request"
    if "connection" in message or "dns" in message or "network" in message:
        return "network"
    return "unexpected-api-error"


class EmbeddingService:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        dimensions: int | None = None,
        batch_size: int | None = None,
        client=None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        config = current_app.config
        self.api_key = api_key if api_key is not None else config["GEMINI_API_KEY"]
        self.model = model or config["GEMINI_EMBEDDING_MODEL"]
        self.dimensions = dimensions or config["EMBEDDING_DIMENSIONS"]
        self.batch_size = batch_size or config["RAG_EMBEDDING_BATCH_SIZE"]
        if not self.api_key:
            raise EmbeddingConfigurationError("GEMINI_API_KEY is required")
        if self.dimensions != 768:
            raise EmbeddingConfigurationError("embedding dimensions must be 768")
        if self.batch_size < 1:
            raise EmbeddingConfigurationError("embedding batch size must be positive")
        self.client = client or genai.Client(
            api_key=self.api_key, http_options=types.HttpOptions(timeout=120000)
        )
        self.sleep = sleep

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts or any(not isinstance(text, str) or not text.strip() for text in texts):
            raise EmbeddingValidationError("document texts must be non-empty")
        result: list[list[float]] = []
        for offset in range(0, len(texts), self.batch_size):
            batch = list(texts[offset : offset + self.batch_size])
            result.extend(self._request(batch, "RETRIEVAL_DOCUMENT"))
        return result

    def embed_query(self, text: str) -> list[float]:
        if not isinstance(text, str) or not text.strip():
            raise EmbeddingValidationError("query must be non-empty")
        return self._request([text], "RETRIEVAL_QUERY")[0]

    def _request(self, texts: list[str], task_type: str) -> list[list[float]]:
        for attempt in range(2):
            try:
                response = self.client.models.embed_content(
                    model=self.model,
                    contents=texts,
                    config=types.EmbedContentConfig(
                        output_dimensionality=self.dimensions, task_type=task_type
                    ),
                )
                embeddings = getattr(response, "embeddings", None) or []
                vectors = [embedding.values for embedding in embeddings]
                return self.validate_vectors(vectors, len(texts))
            except EmbeddingValidationError:
                raise
            except Exception as error:
                code = _error_code(error)
                if code in {429, 503, 504} and attempt == 0:
                    self.sleep(0.5)
                    continue
                raise EmbeddingAPIError(_classify(error), code) from error
        raise EmbeddingAPIError("unexpected-api-error")

    def validate_vectors(
        self, vectors: Sequence[Sequence[float]], expected_count: int
    ) -> list[list[float]]:
        if len(vectors) != expected_count:
            raise EmbeddingValidationError("embedding count does not match input count")
        validated = []
        for vector in vectors:
            if len(vector) != self.dimensions:
                raise EmbeddingValidationError("embedding dimensionality mismatch")
            if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in vector):
                raise EmbeddingValidationError("embedding contains non-finite or non-numeric values")
            validated.append([float(value) for value in vector])
        return validated
