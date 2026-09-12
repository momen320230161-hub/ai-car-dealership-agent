"""Conservative deterministic grounding checks for retrieved dealership knowledge."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any


def normalize_arabic(text: str) -> str:
    normalized = text.casefold()
    normalized = normalized.translate(str.maketrans("أإآةى", "اااهي"))
    return re.sub(r"[^\w\u0600-\u06ff]+", " ", normalized).strip()


def detect_topic(message: str) -> str:
    text = normalize_arabic(message)
    if any(term in text for term in ("تامين", "حوادث", "insurance")):
        return "insurance"
    if any(term in text for term in ("ضمان", "warranty")):
        return "warranty"
    if any(term in text for term in ("تمويل", "تقسيط", "فايده", "فائده", "finance")):
        return "financing"
    if any(term in text for term in ("تجربه قياده", "تست درايف", "test drive")):
        return "test_drive"
    if any(term in text for term in ("السعر النهائي", "متاح", "المعرض", "availability")):
        return "availability_price"
    return "other"


def choose_grounded_result(
    message: str, results: Sequence[dict[str, Any]]
) -> dict[str, Any] | None:
    """Return the first result that supports the detected topic, never merely the nearest."""
    topic = detect_topic(message)
    for result in results:
        title = normalize_arabic(str(result.get("title", "")))
        content = normalize_arabic(str(result.get("content", "")))
        category = str(result.get("category", "")).casefold()
        haystack = f"{title} {content} {category}"
        if topic == "insurance":
            if "تامين" in haystack or "insurance" in haystack:
                return result
            continue
        if topic == "warranty" and ("ضمان" in haystack or category == "warranty"):
            return result
        if topic == "financing" and (
            any(term in haystack for term in ("تمويل", "تقسيط")) or category == "financing"
        ):
            return result
        if topic == "test_drive" and (
            "تجربه قياده" in haystack or category == "test drive policy"
        ):
            return result
        if topic == "availability_price" and (
            any(term in haystack for term in ("توافر", "السعر النهائي", "بيانات السيارات"))
            and category == "faq"
        ):
            return result
    if topic != "other":
        return None

    query_tokens = {
        token
        for token in normalize_arabic(message).split()
        if len(token) >= 4 and token not in {"عندكم", "ممكن", "عايز", "ايه", "هذه"}
    }
    for result in results:
        haystack = normalize_arabic(
            f"{result.get('title', '')} {result.get('content', '')}"
        )
        if query_tokens and any(token in haystack for token in query_tokens):
            return result
    return None
