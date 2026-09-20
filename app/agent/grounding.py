"""Conservative deterministic grounding checks for retrieved dealership knowledge."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any


_GENERIC_QUERY_TOKENS = {
    "عندكم",
    "ممكن",
    "عايز",
    "عاوز",
    "ايه",
    "هذه",
    "هذا",
    "هل",
    "قال",
    "المفروض",
    "كلمه",
    "كلمة",
    "العربيه",
    "عربيه",
    "السياره",
    "سياره",
    "انهي",
    "على",
    "علي",
    "الى",
    "إلى",
    "من",
    "في",
}


def normalize_arabic(text: str) -> str:
    normalized = text.casefold()
    normalized = normalized.translate(str.maketrans("أإآةى", "اااهي"))
    return re.sub(r"[^\w\u0600-\u06ff]+", " ", normalized).strip()


def detect_topic(message: str) -> str:
    text = normalize_arabic(message)
    ordinal_terms = (
        "الاول",
        "الاولى",
        "الثاني",
        "الثانيه",
        "التاني",
        "التانيه",
        "الثالث",
        "الثالثه",
        "التالت",
        "التالته",
        "ترتيب",
        "ترتيبيه",
        "ordinal",
    )
    vehicle_context = ("عربي", "سيار", "قائمه", "اختيار", "نتيج")
    if any(term in text for term in ordinal_terms) and any(
        term in text for term in vehicle_context
    ):
        return "visible_ordinal"
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
    """Choose the strongest supporting result, not merely the nearest vector."""
    topic = detect_topic(message)
    query_tokens = _query_tokens(message)
    candidates: list[dict[str, Any]] = []

    for result in results:
        title = normalize_arabic(str(result.get("title", "")))
        content = normalize_arabic(str(result.get("content", "")))
        category = str(result.get("category", "")).casefold()
        haystack = f"{title} {content} {category}"

        if topic == "visible_ordinal":
            if any(
                marker in haystack
                for marker in (
                    "الارقام الترتيبيه",
                    "الاول والثاني",
                    "قائمه السيارات",
                    "ظهرت فعليا",
                    "نتائج مخفيه",
                )
            ):
                candidates.append(result)
            continue
        if topic == "insurance":
            if "تامين" in haystack or "insurance" in haystack:
                candidates.append(result)
            continue
        if topic == "warranty":
            if "ضمان" in haystack or category == "warranty":
                candidates.append(result)
            continue
        if topic == "financing":
            if any(term in haystack for term in ("تمويل", "تقسيط")) or category == "financing":
                candidates.append(result)
            continue
        if topic == "test_drive":
            if "تجربه قياده" in haystack or category == "test drive policy":
                candidates.append(result)
            continue
        if topic == "availability_price":
            if (
                any(term in haystack for term in ("توافر", "السعر النهائي", "بيانات السيارات"))
                and category == "faq"
            ):
                candidates.append(result)
            continue

        overlap = _token_overlap(query_tokens, haystack)
        if overlap > 0:
            candidates.append(result)

    if not candidates:
        return None

    return max(candidates, key=lambda item: _support_score(query_tokens, item))


def _query_tokens(message: str) -> set[str]:
    return {
        token
        for token in normalize_arabic(message).split()
        if len(token) >= 4 and token not in _GENERIC_QUERY_TOKENS
    }


def _token_overlap(query_tokens: set[str], haystack: str) -> int:
    if not query_tokens:
        return 0
    tokens = set(normalize_arabic(haystack).split())
    return len(query_tokens.intersection(tokens))


def _support_score(query_tokens: set[str], result: dict[str, Any]) -> float:
    haystack = f"{result.get('title', '')} {result.get('content', '')}"
    overlap = _token_overlap(query_tokens, haystack)
    try:
        similarity = float(result.get("similarity") or 0.0)
    except (TypeError, ValueError):
        similarity = 0.0
    return (overlap * 10.0) + similarity
