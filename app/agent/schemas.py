"""Validated structured contracts for LLM understanding and public responses."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Intent = Literal[
    "catalog_search",
    "car_details",
    "car_compare",
    "car_selection",
    "knowledge_question",
    "test_drive",
    "cancel_test_drive",
    "sales_lead",
    "general",
]


class PreferenceUpdates(BaseModel):
    """Only the Phase 2 catalog filters may leave the LLM boundary."""

    model_config = ConfigDict(extra="forbid")

    brand: str | None = None
    model: str | None = None
    condition: str | None = None
    body_type: str | None = None
    transmission: str | None = None
    fuel_type: str | None = None
    min_year: int | None = None
    max_year: int | None = None
    min_price: float | None = None
    max_price: float | None = None
    max_mileage: int | None = None

    @field_validator("brand", "model", "condition", "body_type", "transmission", "fuel_type")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        return value.strip() if value and value.strip() else None


class RequestUnderstanding(BaseModel):
    """Schema-constrained request understanding; Python still validates its claims."""

    model_config = ConfigDict(extra="forbid")

    intent: Intent
    preference_updates: PreferenceUpdates = Field(default_factory=PreferenceUpdates)
    car_reference: str | int | None = None
    comparison_references: list[str | int] = Field(default_factory=list, max_length=5)
    explicit_car_id: int | None = Field(default=None, ge=1)
    knowledge_category_hint: str | None = None

    @field_validator("car_reference", "knowledge_category_hint")
    @classmethod
    def strip_optional_text(cls, value):
        if isinstance(value, str):
            return value.strip() or None
        return value


_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
_ORDINAL_REFERENCES = (
    (r"\b(?:الأولى|الاولى|الأول|الاول|أول|اول|first)\b", 1),
    (r"\b(?:التانية|الثاني|الثانية|تاني|second)\b", 2),
    (r"\b(?:التالتة|التالت|الثالثة|الثالث|third)\b", 3),
)


def explicit_visible_references(message: str) -> list[int]:
    """Extract only ordinals visibly present in the current user message."""
    normalized = message.translate(_ARABIC_DIGITS).casefold()
    if re.search(r"(?:أول|اول|first)\s+(?:اتنين|اثنين|two)", normalized):
        return [1, 2]
    references: list[tuple[int, int]] = []
    for pattern, position in _ORDINAL_REFERENCES:
        match = re.search(pattern, normalized)
        if match:
            references.append((match.start(), position))
    for match in re.finditer(r"(?:#|رقم\s*)([1-9][0-9]*)", normalized):
        references.append((match.start(), int(match.group(1))))
    comparison = re.search(
        r"(?:قارن|compare).*?\b([1-9][0-9]*)\b\s*(?:و|and|,)\s*\b([1-9][0-9]*)\b",
        normalized,
    )
    if comparison:
        references.extend(
            [
                (comparison.start(1), int(comparison.group(1))),
                (comparison.start(2), int(comparison.group(2))),
            ]
        )
    single = re.search(
        r"(?:تفاصيل|اختار|details|select)\s+(?:رقم\s*)?#?([1-9][0-9]?)\b",
        normalized,
    )
    if single:
        references.append((single.start(1), int(single.group(1))))
    ordered = [position for _, position in sorted(set(references))]
    return list(dict.fromkeys(ordered))


def sanitize_understanding(
    understanding: RequestUnderstanding, message: str
) -> RequestUnderstanding:
    """Reject invented IDs/references and leave catalog-value validation to Phase 2."""
    normalized = message.translate(_ARABIC_DIGITS)
    data = understanding.model_dump()
    references = explicit_visible_references(message)
    if understanding.intent == "car_compare":
        data["comparison_references"] = references
    elif references:
        data["car_reference"] = references[0]
    elif understanding.car_reference is not None:
        reference_text = str(understanding.car_reference).translate(_ARABIC_DIGITS)
        if isinstance(understanding.car_reference, int) or reference_text not in normalized:
            data["car_reference"] = None

    if understanding.explicit_car_id is not None:
        supplied = str(understanding.explicit_car_id)
        id_pattern = rf"(?:\bid\b|معرف|رقم\s+العربية)\s*[:#-]?\s*{re.escape(supplied)}\b"
        if not re.search(id_pattern, normalized, flags=re.IGNORECASE):
            data["explicit_car_id"] = None

    updates = understanding.preference_updates.model_dump(exclude_none=True)
    message_folded = normalized.casefold()
    if "condition" in updates:
        if "مستعمل" in message_folded or "used" in message_folded:
            updates["condition"] = "used"
        elif "جديد" in message_folded or "new" in message_folded:
            updates["condition"] = "new"
        else:
            updates.pop("condition")
    for name in ("brand", "model", "body_type"):
        if name in updates and str(updates[name]).casefold() not in message_folded:
            updates.pop(name)
    if "transmission" in updates:
        value = str(updates["transmission"]).casefold()
        automatic = value == "automatic" and any(
            term in message_folded for term in ("automatic", "اوتوماتيك", "أوتوماتيك")
        )
        manual = value == "manual" and any(
            term in message_folded for term in ("manual", "مانيوال", "يدوي")
        )
        if not (value in message_folded or automatic or manual):
            updates.pop("transmission")
    if "fuel_type" in updates:
        value = str(updates["fuel_type"]).casefold()
        if value not in message_folded:
            updates.pop("fuel_type")
    for name in ("min_year", "max_year", "min_price", "max_price", "max_mileage"):
        if name in updates:
            compact = str(int(updates[name]))
            digits = re.sub(r"[^0-9]", "", normalized)
            million_explicit = updates[name] == 1_000_000 and "مليون" in normalized
            if compact not in digits and not million_explicit:
                updates.pop(name)
    data["preference_updates"] = updates
    return RequestUnderstanding.model_validate(data)
