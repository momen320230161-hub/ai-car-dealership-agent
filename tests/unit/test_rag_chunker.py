"""Deterministic chunking and embedding abstraction unit tests."""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from app.rag.chunker import DeterministicChunker
from app.rag.embeddings import (
    DeterministicEmbeddingProvider,
    EmbeddingError,
    GeminiEmbeddingProvider,
    validate_embedding,
)


def test_short_document_produces_one_normalized_chunk():
    chunks = DeterministicChunker().chunk("  First line.\nSecond line.  ")
    assert chunks == ["First line. Second line."]


def test_multiple_paragraphs_preserve_boundaries_when_they_fit():
    chunks = DeterministicChunker(max_chars=120, overlap_chars=20).chunk(
        "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
    )
    assert chunks == ["First paragraph.\n\nSecond paragraph.\n\nThird paragraph."]


def test_long_content_is_bounded_overlapping_deterministic_and_nonempty():
    content = " ".join(f"token{index}" for index in range(250))
    chunker = DeterministicChunker(max_chars=180, overlap_chars=35)

    first = chunker.chunk(content)
    second = chunker.chunk(content)

    assert first == second
    assert len(first) > 2
    assert all(chunk and len(chunk) <= 180 for chunk in first)
    assert len(first) == len(set(first))
    assert set(first[0].split()) & set(first[1].split())


def test_paragraph_rollover_adds_small_overlap():
    content = f"{'alpha ' * 15}\n\n{'beta ' * 15}\n\n{'gamma ' * 15}"
    chunks = DeterministicChunker(max_chars=120, overlap_chars=25).chunk(content)
    assert len(chunks) >= 2
    assert set(chunks[0].split()) & set(chunks[1].split())


@pytest.mark.parametrize("content", ["", "   ", "\n\n"])
def test_blank_content_is_rejected(content):
    with pytest.raises(ValueError, match="must not be blank"):
        DeterministicChunker().chunk(content)


def test_deterministic_embeddings_have_exact_dimension_and_unit_length():
    provider = DeterministicEmbeddingProvider()
    first = provider.embed_text("Phase3 verification policy alpha")
    second = provider.embed_text("Phase3 verification policy alpha")

    assert first == second
    assert len(first) == 768
    assert math.isclose(sum(value * value for value in first), 1.0)
    assert first != provider.embed_text("unrelated showroom information")


def test_wrong_dimension_and_non_finite_embeddings_are_rejected():
    with pytest.raises(EmbeddingError, match="dimension mismatch"):
        validate_embedding([0.1, 0.2], 768)
    with pytest.raises(EmbeddingError, match="non-finite"):
        validate_embedding([float("nan")], 1)


def test_gemini_credentials_are_checked_only_when_provider_is_used():
    provider = GeminiEmbeddingProvider(api_key=None, model_name="gemini-embedding-2", dimension=768)
    with pytest.raises(EmbeddingError, match="credentials are not configured"):
        provider.embed_text("query")


def test_gemini_multi_input_uses_separate_content_objects(monkeypatch):
    from google import genai
    from google.genai import types

    captured = {}

    class FakeModels:
        def embed_content(self, *, model, contents, config):
            captured["model"] = model
            captured["contents"] = contents
            captured["config"] = config
            return SimpleNamespace(
                embeddings=[
                    SimpleNamespace(values=[0.1] * 768),
                    SimpleNamespace(values=[0.2] * 768),
                ]
            )

    class FakeClient:
        def __init__(self, *, api_key):
            captured["api_key"] = api_key
            self.models = FakeModels()

    monkeypatch.setattr(genai, "Client", FakeClient)

    provider = GeminiEmbeddingProvider(
        api_key="test-key", model_name="gemini-embedding-2", dimension=768
    )
    vectors = provider.embed_texts(["first chunk", "second chunk"])

    assert captured["api_key"] == "test-key"
    assert captured["model"] == "gemini-embedding-2"
    assert captured["config"].output_dimensionality == 768
    assert all(isinstance(content, types.Content) for content in captured["contents"])
    assert [content.parts[0].text for content in captured["contents"]] == [
        "first chunk",
        "second chunk",
    ]
    assert len(vectors) == 2
    assert all(len(vector) == 768 for vector in vectors)


def test_gemini_rejects_incomplete_multi_input_response(monkeypatch):
    from google import genai

    class FakeModels:
        def embed_content(self, *, model, contents, config):
            del model, contents, config
            return SimpleNamespace(embeddings=[SimpleNamespace(values=[0.1] * 768)])

    class FakeClient:
        def __init__(self, *, api_key):
            del api_key
            self.models = FakeModels()

    monkeypatch.setattr(genai, "Client", FakeClient)

    provider = GeminiEmbeddingProvider(
        api_key="test-key", model_name="gemini-embedding-2", dimension=768
    )
    with pytest.raises(EmbeddingError, match="response count"):
        provider.embed_texts(["first chunk", "second chunk"])
