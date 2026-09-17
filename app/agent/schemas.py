"""Validated structured contracts for LLM understanding and public responses."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.agent.catalog_qualification import (
    explicit_body_type_from_message,
    explicit_brand_from_message,
    explicit_fuel_type_from_message,
    explicit_model_from_message,
)

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
    (r"\b(?:الأولى|الاولى|الأول|الاول|أول|اول|الأولانية|الاولانية|first)\b", 1),
    (r"\b(?:التانية|التانيه|الثاني|الثانية|الثانيه|تاني|تانيه|second)\b", 2),
    (r"\b(?:التالتة|التالته|التالت|الثالثة|الثالثه|الثالث|third)\b", 3),
    (r"\b(?:الرابعة|الرابعه|الرابع|fourth)\b", 4),
    (r"\b(?:الخامسة|الخامسه|الخامس|fifth)\b", 5),
)
_EXPLICIT_CAR_ID_RE = re.compile(
    r"(?:\bcar\s*id\b|\bid\b|رقم\s+العربية|العربية\s+(?:رقم|id))"
    r"\s*[:#-]?\s*([1-9][0-9]*)",
    re.IGNORECASE,
)
_MILLION_WORD_VALUES = {
    "واحد": 1.0,
    "واحدة": 1.0,
    "اتنين": 2.0,
    "اثنين": 2.0,
    "اثنان": 2.0,
    "تلاتة": 3.0,
    "ثلاثة": 3.0,
    "اربعة": 4.0,
    "أربعة": 4.0,
    "خمسة": 5.0,
    "ستة": 6.0,
    "سبعة": 7.0,
    "تمانية": 8.0,
    "ثمانية": 8.0,
    "تسعة": 9.0,
    "عشرة": 10.0,
}
_BUDGET_MARKERS = (
    "معايا",
    "معي",
    "ميزاني",
    "الميزانية",
    "تحت",
    "أقل من",
    "اقل من",
    "لحد",
    "حد أقصى",
    "حد اقصى",
    "budget",
    "under",
    "up to",
)
_TEST_DRIVE_INFO_MARKERS = (
    "نظام التست درايف",
    "نظام test drive",
    "سياسة التست درايف",
    "سياسه التست درايف",
    "متطلبات التست درايف",
    "المطلوب للتست درايف",
    "البيانات المطلوبة",
    "البيانات المطلوبه",
    "ايه المطلوب",
    "إيه المطلوب",
    "requirements",
    "policy",
)
_TEST_DRIVE_ACTION_PATTERNS = (
    r"(?:احجز|أحجز|عايز|عاوز|محتاج)\s+(?:لي\s+)?(?:تست\s*درايف|تجرب[ةه]\s*قياد[ةه]|test\s*drive)",
    r"(?:ينفع|ممكن)\s+(?:ا?جي\s+)?(?:ا?جرب|أجرب)\s+(?:ا?سوق|أسوق|سواقة|سواقه)",
    r"(?:عايز|عاوز|نفسي|محتاج)\s+(?:ا?جرب|أجرب)\s+(?:ا?سوق|أسوق)",
    r"(?:ا?جي\s+)?(?:ا?جرب|أجرب)\s+(?:ا?سوق|أسوق)ها",
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
    for match in re.finditer(r"(?:#|رقم\s*|(?:العربية|السيارة)\s*#?)([1-9][0-9]*)", normalized):
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


def explicit_car_id_from_message(message: str) -> int | None:
    """Extract a car ID only when the current message explicitly marks it as an ID."""
    normalized = message.translate(_ARABIC_DIGITS)
    match = _EXPLICIT_CAR_ID_RE.search(normalized)
    return int(match.group(1)) if match else None


def explicit_money_amounts(message: str) -> list[float]:
    """Parse customer-written EGP amounts without asking the LLM to prove arithmetic."""
    normalized = message.translate(_ARABIC_DIGITS).replace("٫", ".").replace("٬", ",").casefold()
    amounts: list[float] = []

    for match in re.finditer(r"(?<!\w)([0-9]+(?:\.[0-9]+)?)\s*مليون", normalized):
        amounts.append(float(match.group(1)) * 1_000_000)

    if re.search(r"\bمليونين\s*ونص\b", normalized):
        amounts.append(2_500_000.0)
    elif re.search(r"\bمليونين\b", normalized):
        amounts.append(2_000_000.0)

    words = "|".join(
        sorted((re.escape(word) for word in _MILLION_WORD_VALUES), key=len, reverse=True)
    )
    for match in re.finditer(rf"\b({words})\s*مليون\s*ونص\b", normalized):
        amounts.append((_MILLION_WORD_VALUES[match.group(1)] + 0.5) * 1_000_000)
    for match in re.finditer(rf"\b({words})\s*(ونص)?\s*مليون\b(?!\s*ونص)", normalized):
        value = _MILLION_WORD_VALUES[match.group(1)]
        if match.group(2):
            value += 0.5
        amounts.append(value * 1_000_000)

    compact = normalized.replace(",", "")
    for match in re.finditer(r"(?<![0-9])([1-9][0-9]{5,})(?![0-9])", compact):
        amounts.append(float(match.group(1)))

    if not amounts and re.search(r"\bمليون\s*ونص\b", normalized):
        amounts.append(1_500_000.0)
    if not amounts and re.search(r"(?<!\w)مليون(?!\w)", normalized):
        amounts.append(1_000_000.0)

    return list(dict.fromkeys(amounts))


def explicit_budget_ceiling(message: str) -> float | None:
    """Return a deterministic budget ceiling only when the message explicitly signals budget."""
    normalized = message.translate(_ARABIC_DIGITS).casefold()
    if not any(marker in normalized for marker in _BUDGET_MARKERS):
        return None
    amounts = explicit_money_amounts(message)
    return amounts[0] if amounts else None


def explicitly_requests_test_drive(message: str) -> bool:
    """Recognize direct driving/booking actions without swallowing policy questions."""
    normalized = " ".join(message.translate(_ARABIC_DIGITS).casefold().split())
    if any(marker in normalized for marker in _TEST_DRIVE_INFO_MARKERS):
        return False
    return any(re.search(pattern, normalized) for pattern in _TEST_DRIVE_ACTION_PATTERNS)


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

    # High-value business-action fallback: direct requests to try/drive a car are actions,
    # even if an LLM misclassifies them as dealership-policy questions. Informational test-drive
    # questions remain knowledge queries and therefore cannot create a pending action.
    if explicitly_requests_test_drive(message):
        data["intent"] = "test_drive"

    # IDs are owned by deterministic parsing of the current message, not by the LLM.
    data["explicit_car_id"] = explicit_car_id_from_message(message)

    updates = understanding.preference_updates.model_dump(exclude_none=True)
    message_folded = normalized.casefold()

    # Refine canonical values via allowlisted aliases when explicitly present,
    # but TRUST Gemini's structured extraction rather than throwing it away.
    if any(
        term in message_folded for term in ("مستعمل", "used", "استعمال", "استعمال خفيف", "كسر زيرو")
    ):
        updates["condition"] = "used"
    elif any(term in message_folded for term in ("جديد", "جديدة", "new", "زيرو")):
        updates["condition"] = "new"

    explicit_brand = explicit_brand_from_message(message)
    if explicit_brand is not None:
        updates["brand"] = explicit_brand

    explicit_model = explicit_model_from_message(message)
    if explicit_model is not None:
        updates["model"] = explicit_model

    explicit_body_type = explicit_body_type_from_message(message)
    if explicit_body_type is not None:
        updates["body_type"] = explicit_body_type

    explicit_fuel_type = explicit_fuel_type_from_message(message)
    if explicit_fuel_type is not None:
        updates["fuel_type"] = explicit_fuel_type

    explicit_budget = explicit_budget_ceiling(message)
    if explicit_budget is not None:
        updates["max_price"] = explicit_budget

    money_amounts = explicit_money_amounts(message)
    digits = re.sub(r"[^0-9]", "", normalized)
    has_money_words = any(
        w in message_folded
        for w in (
            "مليون",
            "الف",
            "ألف",
            "ميزانية",
            "ميزانيه",
            "معايا",
            "سعر",
            "تحت",
            "حد",
            "k",
        )
    )
    for name in ("min_price", "max_price"):
        if name in updates and updates[name] is not None:
            explicit_money = any(abs(float(updates[name]) - amount) < 1 for amount in money_amounts)
            if not digits and not explicit_money and not has_money_words:
                updates.pop(name)

    # Filter reset handling (customer requests clearing price ceiling or resetting search)
    budget_reset = (
        re.search(
            r"(?:شيل|إلغاء|الغاء|بدون|من غير)\s*(?:السعر|الميزانية|الميزانيه|حد أقصى|حد اقصى|سعر)",
            message_folded,
        )
        or "من غير حد أقصى" in message_folded
        or "بدون حد أقصى" in message_folded
    )
    if budget_reset:
        updates["max_price"] = None
        updates["min_price"] = None

    global_reset = (
        re.search(
            r"(?:شيل|إلغاء|الغاء|بدون|من غير)\s*(?:الفلتر|الفلاتر|التفضيلات|كل الشروط)",
            message_folded,
        )
        or "من الأول" in message_folded
        or "من الاول" in message_folded
        or "تصفير التفضيلات" in message_folded
    )
    if global_reset:
        for key in (
            "brand",
            "model",
            "condition",
            "body_type",
            "transmission",
            "fuel_type",
            "min_year",
            "max_year",
            "min_price",
            "max_price",
            "max_mileage",
        ):
            updates[key] = None

    data["preference_updates"] = updates
    return RequestUnderstanding.model_validate(data)
