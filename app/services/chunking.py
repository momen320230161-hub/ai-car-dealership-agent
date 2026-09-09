"""Deterministic, paragraph-aware text normalization and chunking."""

import hashlib
import re


class ChunkingError(ValueError):
    pass


def normalize_content(content: str) -> str:
    """Normalize insignificant whitespace while preserving paragraph boundaries."""
    if not isinstance(content, str):
        raise ChunkingError("content must be text")
    paragraphs = []
    for paragraph in re.split(r"\n\s*\n", content.strip()):
        normalized = re.sub(r"\s+", " ", paragraph).strip()
        if normalized:
            paragraphs.append(normalized)
    if not paragraphs:
        raise ChunkingError("content must not be empty")
    return "\n\n".join(paragraphs)


def content_hash(content: str) -> str:
    return hashlib.sha256(normalize_content(content).encode("utf-8")).hexdigest()


def _tail(text: str, overlap: int) -> str:
    if overlap <= 0:
        return ""
    candidate = text[-overlap:]
    if len(text) > overlap and " " in candidate:
        candidate = candidate.split(" ", 1)[1]
    return candidate.strip()


def _split_long(text: str, chunk_size: int, overlap: int) -> list[str]:
    words = text.split()
    chunks: list[str] = []
    current: list[str] = []
    for word in words:
        proposed = " ".join([*current, word])
        if current and len(proposed) > chunk_size:
            finished = " ".join(current)
            chunks.append(finished)
            carry = _tail(finished, overlap).split()
            current = carry + [word]
            while len(" ".join(current)) > chunk_size and len(current) > 1:
                current.pop(0)
        else:
            current.append(word)
    if current:
        chunks.append(" ".join(current))
    return chunks


def chunk_text(content: str, *, chunk_size: int = 1000, overlap: int = 150) -> list[str]:
    """Chunk normalized text without cutting words and with deterministic order."""
    if chunk_size < 1:
        raise ChunkingError("chunk_size must be positive")
    if overlap < 0 or overlap >= chunk_size:
        raise ChunkingError("overlap must be non-negative and smaller than chunk_size")

    normalized = normalize_content(content)
    chunks: list[str] = []
    current = ""
    for paragraph in normalized.split("\n\n"):
        if len(paragraph) > chunk_size:
            if current:
                chunks.append(current)
                current = ""
            long_chunks = _split_long(paragraph, chunk_size, overlap)
            chunks.extend(long_chunks[:-1])
            current = long_chunks[-1]
            continue
        proposed = paragraph if not current else f"{current}\n\n{paragraph}"
        if len(proposed) <= chunk_size:
            current = proposed
        else:
            chunks.append(current)
            prefix = _tail(current, overlap)
            proposed = f"{prefix}\n\n{paragraph}" if prefix else paragraph
            current = proposed if len(proposed) <= chunk_size else paragraph
    if current:
        chunks.append(current)
    return [chunk for chunk in chunks if chunk.strip()]
