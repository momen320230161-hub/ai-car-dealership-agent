"""Conservative deterministic grounding checks for retrieved dealership knowledge."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any


def normalize_arabic(text: str) -> str:
    normalized = text.casefold()
    # Normalize alef variants, taa marbuta -> h, alef maqsura -> y
    normalized = normalized.translate(str.maketrans("أإآةى", "اااهي"))
    return re.sub(r"[^\w\u0600-\u06ff]+", " ", normalized).strip()


# Topic detection strings are pre-normalized so morphological Arabic variants
# ("تجربة القيادة" vs "تجربه قياده", "فائدة" vs "فايده") all match correctly.
_TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "insurance": ("تامين", "حوادث", "insurance"),
    "warranty": ("ضمان", "warranty"),
    "financing": ("تمويل", "تقسيط", "فايده", "فائده", "finance"),
    # Normalized variants of "تجربة القيادة", "تست درايف", etc.
    "test_drive": ("تجربه القياده", "تجربه قياده", "تست درايف", "test drive", "الغاء", "إلغاء"),
    "availability_price": ("السعر النهائي", "متاح", "المعرض", "availability"),
}

# Category values stored in the knowledge DB for each topic.
_TOPIC_CATEGORIES: dict[str, set[str]] = {
    "insurance": {"insurance"},
    "warranty": {"warranty"},
    "financing": {"financing"},
    "test_drive": {"test drive policy", "test_drive_policy"},
    "availability_price": {"faq"},
}

# Content terms that confirm a chunk is actually about the topic (normalized).
_TOPIC_CONTENT_TERMS: dict[str, tuple[str, ...]] = {
    "insurance": ("تامين", "insurance"),
    "warranty": ("ضمان",),
    "financing": ("تمويل", "تقسيط"),
    "test_drive": ("تجربه", "قياده", "الغاء", "cancel"),
    "availability_price": ("توافر", "السعر النهائي", "بيانات السيارات"),
}


def detect_topic(message: str) -> str:
    text = normalize_arabic(message)
    for topic, keywords in _TOPIC_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return topic
    return "other"


def _chunk_supports_topic(result: dict[str, Any], topic: str) -> bool:
    """Return True when a retrieved chunk is thematically about the detected topic."""
    title = normalize_arabic(str(result.get("title", "")))
    content = normalize_arabic(str(result.get("content", "")))
    category = str(result.get("category", "")).casefold().strip()
    haystack = f"{title} {content}"

    # Category match is a strong signal (the knowledge-seed/PDF was tagged for this topic).
    if category in _TOPIC_CATEGORIES.get(topic, set()):
        return True

    # Content/title term match is the fallback.
    return any(term in haystack for term in _TOPIC_CONTENT_TERMS.get(topic, ()))


def choose_grounded_result(
    message: str, results: Sequence[dict[str, Any]]
) -> dict[str, Any] | None:
    """Return the most relevant result that supports the detected topic.

    The pgvector backend already ranks by embedding similarity, so we use that
    ordering as the primary sort and apply topic-support as a filter.  For
    ``topic == "other"`` (no recognised domain) we fall back to the
    highest-similarity chunk that shares at least one meaningful token with the
    query, rather than the first arbitrary result.
    """
    if not results:
        return None

    topic = detect_topic(message)

    if topic != "other":
        candidates = [r for r in results if _chunk_supports_topic(r, topic)]
        if not candidates:
            return None

        # When a specific query has meaningful keywords (e.g. "عقد", "البيانات الأساسية"),
        # prefer the candidate chunk with the strongest query token overlap rather than
        # blindly returning the first chunk that merely shares the topic category.
        stop_words = {"عندكم", "ممكن", "عايز", "ايه", "هذه", "اللي", "تكون", "المفروض"}
        query_tokens = {
            token
            for token in normalize_arabic(message).split()
            if len(token) >= 3 and token not in stop_words
        }
        if query_tokens:
            best = candidates[0]
            max_matches = 0
            for r in candidates:
                haystack = normalize_arabic(f"{r.get('title', '')} {r.get('content', '')}")
                matches = sum(1 for token in query_tokens if token in haystack)
                if matches > max_matches:
                    max_matches = matches
                    best = r
            if max_matches > 1:
                return best
        return candidates[0]

    # Generic topic: pick the highest-similarity chunk with meaningful token overlap.
    query_tokens = {
        token
        for token in normalize_arabic(message).split()
        if len(token) >= 4 and token not in {"عندكم", "ممكن", "عايز", "ايه", "هذه", "اللي"}
    }
    if not query_tokens:
        return None

    best: dict[str, Any] | None = None
    best_score: float = -1.0
    for result in results:
        haystack = normalize_arabic(f"{result.get('title', '')} {result.get('content', '')}")
        if not any(token in haystack for token in query_tokens):
            continue
        score = float(result.get("similarity") or 0.0)
        if score > best_score:
            best_score = score
            best = result

    return best
