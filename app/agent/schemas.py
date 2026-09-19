"""Validated structured contracts for LLM understanding and public responses."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.catalog_language import (
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

PreferenceField = Literal[
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
]
DialogueAction = Literal[
    "recommend",
    "refine",
    "broaden",
    "paginate",
    "reset",
    "continue",
    "discuss_budget",
    "repair",
    "social",
]
UnderstandingConfidence = Literal["low", "medium", "high"]
ReferenceScope = Literal["none", "visible_results", "selected_car"]
BudgetChange = Literal[
    "none",
    "increase_unspecified",
    "decrease_unspecified",
    "remove_limit",
]
PendingFieldAnswer = Literal[
    "none",
    "customer_name",
    "phone",
    "preferred_date",
    "preferred_time",
    "request_id",
]
RequestedCarField = Literal[
    "price_egp",
    "mileage_km",
    "year",
    "condition",
    "body_type",
    "transmission",
    "fuel_type",
    "engine_capacity_cc",
    "horsepower",
    "color",
]
ConditionPreference = Literal["new", "used"]
VisibleReferenceField = Literal[
    "none",
    "price_egp",
    "mileage_km",
    "year",
    "condition",
    "transmission",
    "body_type",
    "fuel_type",
]
VisibleReferenceOperator = Literal["none", "min", "max", "equals"]


class VisibleReferenceSelector(BaseModel):
    """Semantic description of one currently visible car; Python resolves the position."""

    model_config = ConfigDict(extra="forbid")

    field: VisibleReferenceField = "none"
    operator: VisibleReferenceOperator = "none"
    value: str = ""

    @field_validator("value")
    @classmethod
    def strip_value(cls, value: str) -> str:
        return value.strip()


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


class VehicleReferenceTarget(BaseModel):
    """A semantic pointer to a car, kept separate from search-preference mutations."""

    model_config = ConfigDict(extra="forbid")

    scope: ReferenceScope = "none"
    position: int | None = Field(default=None, ge=1, le=20)
    constraints: PreferenceUpdates = Field(default_factory=PreferenceUpdates)
    confidence: UnderstandingConfidence = "medium"


class RequestUnderstanding(BaseModel):
    """Schema-constrained request understanding; Python still validates its claims."""

    model_config = ConfigDict(extra="forbid")

    intent: Intent
    preference_updates: PreferenceUpdates = Field(default_factory=PreferenceUpdates)
    confidence: UnderstandingConfidence = "medium"
    dialogue_action: DialogueAction | None = None
    preference_clears: list[PreferenceField] = Field(default_factory=list, max_length=11)
    budget_change: BudgetChange = "none"
    pending_field_answer: PendingFieldAnswer = "none"
    requested_car_fields: list[RequestedCarField] = Field(default_factory=list, max_length=10)
    condition_preference_order: list[ConditionPreference] = Field(
        default_factory=list,
        max_length=2,
    )
    visible_reference_selector: VisibleReferenceSelector = Field(
        default_factory=VisibleReferenceSelector
    )
    reference_target: VehicleReferenceTarget = Field(default_factory=VehicleReferenceTarget)
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
    (r"\b(?:الأولى|الاولى|الأول|الاول|الأولانية|الاولانية)\b", 1),
    (r"\b(?:التانية|التانيه|التاني|الثاني|الثانية|الثانيه)\b", 2),
    (r"\b(?:التالتة|التالته|التالت|الثالثة|الثالثه|الثالث)\b", 3),
    (r"\b(?:الرابعة|الرابعه|الرابع)\b", 4),
    (r"\b(?:الخامسة|الخامسه|الخامس)\b", 5),
)
_BARE_ORDINAL_REFERENCES = (
    (r"(?:أول|اول|first)", 1),
    (r"(?:تاني|تانيه|second)", 2),
    (r"(?:تالت|تالته|third)", 3),
    (r"(?:رابع|fourth)", 4),
    (r"(?:خامس|fifth)", 5),
)
_REFERENCE_NOUN = (
    r"(?:عربية|العربية|سيارة|السيارة|اختيار|الاختيار|واحدة|واحد|"
    r"نتيجة|النتيجة|car|option|one|listing|result)"
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
    """Extract visible positions without confusing "more/again" language with ordinals.

    Bare forms such as "تاني"/"second" are references only when they are the whole
    reply or directly attached to a vehicle/option noun. Definite Arabic ordinals
    such as "التانية" remain safe references anywhere in the turn.
    """
    normalized = " ".join(message.translate(_ARABIC_DIGITS).casefold().split())
    if re.search(r"(?:أول|اول|first)\s+(?:اتنين|اثنين|two)", normalized):
        return [1, 2]

    references: list[tuple[int, int]] = []
    for pattern, position in _ORDINAL_REFERENCES:
        match = re.search(pattern, normalized)
        if match:
            references.append((match.start(), position))

    for bare_pattern, position in _BARE_ORDINAL_REFERENCES:
        standalone = re.fullmatch(rf"(?:{bare_pattern})", normalized)
        contextual = re.search(
            rf"(?<!\w)(?:{bare_pattern})\s+{_REFERENCE_NOUN}(?!\w)"
            rf"|(?<!\w){_REFERENCE_NOUN}\s+(?:{bare_pattern})(?!\w)",
            normalized,
        )
        match = standalone or contextual
        if match:
            references.append((match.start(), position))

    for match in re.finditer(
        r"(?:#|رقم\s*|(?:العربية|السيارة)\s*#?)([1-9][0-9]*)",
        normalized,
    ):
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

    for match in re.finditer(
        r"(?<!\w)([0-9]+(?:\.[0-9]+)?)\s*(?:و\s*)?نص\s*مليون",
        normalized,
    ):
        amounts.append((float(match.group(1)) + 0.5) * 1_000_000)

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
        contextual_intent = understanding.intent in {
            "car_selection",
            "car_details",
            "test_drive",
            "sales_lead",
        }
        try:
            contextual_position = int(reference_text)
        except (TypeError, ValueError):
            contextual_position = None
        contextual_reference = (
            contextual_intent
            and contextual_position is not None
            and 1 <= contextual_position <= 20
        )
        if contextual_reference:
            # A small visible position may be inferred from bounded conversation
            # history. The active recommendation snapshot validates it downstream.
            data["car_reference"] = contextual_position
        else:
            # Explicit ordinals/numbers were already recovered above from the
            # current message. Everything else is an untrusted LLM reference.
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

    # Preserve the model's scoped semantic extraction. A surface token must never
    # override it: "مش عايز المستعملة، عايز الجديدة" contains both condition words.
    # The deterministic fallback is intentionally conservative and runs only for a
    # single, non-negated condition family.
    if "condition" not in updates:
        has_negation = bool(re.search(r"\b(?:مش|لا|not|dont|don't)\b", message_folded))
        used_mentioned = any(
            term in message_folded
            for term in ("مستعمل", "used", "استعمال", "استعمال خفيف", "كسر زيرو")
        )
        new_mentioned = any(
            term in message_folded for term in ("جديد", "جديدة", "new", "زيرو")
        )
        if not has_negation and used_mentioned != new_mentioned:
            updates["condition"] = "used" if used_mentioned else "new"

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
        data["budget_change"] = "remove_limit"
        data["preference_clears"] = list(
            dict.fromkeys([*data.get("preference_clears", []), "min_price", "max_price"])
        )

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
        reset_fields = (
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
        )
        for key in reset_fields:
            updates[key] = None
        data["dialogue_action"] = "reset"
        data["preference_clears"] = list(
            dict.fromkeys([*data.get("preference_clears", []), *reset_fields])
        )

    data["preference_updates"] = updates
    return RequestUnderstanding.model_validate(data)
