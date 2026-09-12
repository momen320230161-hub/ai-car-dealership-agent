"""Small deterministic paragraph-aware text chunker."""

from __future__ import annotations

import re


class DeterministicChunker:
    """Split normalized text into stable chunks with bounded character overlap."""

    def __init__(self, *, max_chars: int = 1000, overlap_chars: int = 120):
        if max_chars < 100:
            raise ValueError("max_chars must be at least 100")
        if overlap_chars < 0 or overlap_chars >= max_chars:
            raise ValueError("overlap_chars must be non-negative and smaller than max_chars")
        self.max_chars = max_chars
        self.overlap_chars = overlap_chars

    def chunk(self, content: str) -> list[str]:
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Knowledge content must not be blank")
        paragraphs = [
            self._normalize_paragraph(paragraph)
            for paragraph in re.split(r"\n\s*\n", content.strip())
            if paragraph.strip()
        ]
        chunks: list[str] = []
        current = ""
        for paragraph in paragraphs:
            if len(paragraph) > self.max_chars:
                if current:
                    self._append_unique(chunks, current)
                    current = ""
                for part in self._split_long_paragraph(paragraph):
                    self._append_unique(chunks, part)
                continue

            candidate = f"{current}\n\n{paragraph}" if current else paragraph
            if len(candidate) <= self.max_chars:
                current = candidate
                continue

            self._append_unique(chunks, current)
            overlap = self._tail(current)
            candidate = f"{overlap}\n\n{paragraph}" if overlap else paragraph
            current = candidate if len(candidate) <= self.max_chars else paragraph

        if current:
            self._append_unique(chunks, current)
        if not chunks:
            raise ValueError("Knowledge content produced no chunks")
        return chunks

    @staticmethod
    def _normalize_paragraph(paragraph: str) -> str:
        return " ".join(paragraph.split())

    def _split_long_paragraph(self, paragraph: str) -> list[str]:
        chunks: list[str] = []
        start = 0
        while start < len(paragraph):
            end = min(start + self.max_chars, len(paragraph))
            if end < len(paragraph):
                boundary = paragraph.rfind(" ", start + self.max_chars // 2, end)
                if boundary > start:
                    end = boundary
            part = paragraph[start:end].strip()
            self._append_unique(chunks, part)
            if end >= len(paragraph):
                break
            next_start = max(0, end - self.overlap_chars)
            while next_start < end and not paragraph[next_start].isspace():
                next_start += 1
            start = next_start + 1 if next_start < end else end
        return chunks

    def _tail(self, text: str) -> str:
        if not self.overlap_chars:
            return ""
        tail = text[-self.overlap_chars :]
        first_space = tail.find(" ")
        return tail[first_space + 1 :].strip() if first_space >= 0 else tail.strip()

    @staticmethod
    def _append_unique(chunks: list[str], value: str) -> None:
        value = value.strip()
        if value and value not in chunks:
            chunks.append(value)
