"""Deterministic catalog-language normalization and sales qualification."""

from app.domain.catalog_language import (
    explicit_body_type_from_message,
    explicit_brand_from_message,
    explicit_fuel_type_from_message,
    explicit_model_from_message,
    normalize_catalog_text,
)

_RECOMMENDATION_MARKERS = (
    "رشح",
    "اقترح",
    "اختارلي",
    "اختار لي",
    "وريني",
    "ورّيني",
    "اعرضلي",
    "اعرض لي",
    "اعرض",
    "الموجود",
    "اللي عندك",
    "ال عندك",
    "غيرهم",
    "غير دول",
    "تاني",
    "تانيه",
    "ثانية",
    "مزيد",
    "recommend",
    "suggest",
    "show me",
    "options",
)


class CatalogQualification:
    """Whether a broad catalog request is ready to create a visible shortlist."""

    __slots__ = ("ready", "message", "missing")

    def __init__(
        self,
        ready: bool,
        message: str | None = None,
        missing: tuple[str, ...] = (),
    ) -> None:
        self.ready = ready
        self.message = message
        self.missing = missing


def explicitly_requests_recommendation(message: str) -> bool:
    normalized = normalize_catalog_text(message)
    return any(marker in normalized for marker in _RECOMMENDATION_MARKERS)


def _condition_text(condition: str) -> str:
    normalized = condition.strip().casefold()
    if normalized == "used":
        return "مستعملة"
    if normalized == "new":
        return "جديدة"
    return condition


def qualify_catalog_search(
    preferences: dict[str, object] | None,
    message: str,
) -> CatalogQualification:
    """Ask for high-value missing preferences before creating a broad shortlist.

    The production conversational layer may explicitly bypass this conservative
    baseline when the current turn clearly asks for a useful flexible search.
    """
    prefs = {key: value for key, value in (preferences or {}).items() if value is not None}
    brand = str(prefs.get("brand") or "").strip()
    model = str(prefs.get("model") or "").strip()
    condition = str(prefs.get("condition") or "").strip()
    body_type = str(prefs.get("body_type") or "").strip()
    wants_recommendation = explicitly_requests_recommendation(message)

    if not prefs:
        return CatalogQualification(
            False,
            "تمام، أقدر أرشحلك. ميزانيتك تقريبًا كام؟",
            ("budget",),
        )

    if model:
        return CatalogQualification(True)

    if brand:
        if not wants_recommendation:
            suffix = ""
            missing: list[str] = ["model_or_recommendation"]
            if not condition:
                suffix = " ولو تحب أرشحلك، تحبها جديدة ولا مستعملة؟"
                missing.append("condition")
            cond_str = f" {_condition_text(condition)}" if condition else ""
            verb = "سجلت" if condition else "فهمت"
            return CatalogQualification(
                False,
                f"تمام، {verb} إنك بتدور على {brand}{cond_str}. في موديل معين في دماغك "
                f"ولا تحب أرشحلك من الموجود في الكتالوج؟{suffix}",
                tuple(missing),
            )
        if condition or prefs.get("max_price") is not None or body_type:
            return CatalogQualification(True)
        return CatalogQualification(
            False,
            f"تمام، أرشحلك من {brand}. تحبها جديدة ولا مستعملة؟",
            ("condition",),
        )

    if condition and not body_type and set(prefs) == {"condition"}:
        return CatalogQualification(True)

    # Prototype behavior: budget plus one useful preference is enough for an
    # initial search. Do not turn the conversation into a form when the catalog
    # can safely search across new + used and let the customer refine afterward.
    if prefs.get("max_price") is not None and any(
        prefs.get(field) is not None
        for field in ("body_type", "condition", "fuel_type", "transmission", "brand")
    ):
        return CatalogQualification(True)

    if condition and body_type:
        return CatalogQualification(True)

    missing: list[str] = []
    if not condition:
        missing.append("condition")
    if not body_type:
        missing.append("body_type")
    if not missing:
        return CatalogQualification(True)

    if missing == ["condition", "body_type"]:
        prompt = "أهم حاجة الأول: تحب العربية جديدة ولا مستعملة؟"
    elif missing == ["condition"]:
        prompt = "تمام. تحب العربية جديدة ولا مستعملة؟"
    else:
        prompt = "تمام. تفضل نوع العربية SUV ولا Sedan ولا نوع تاني؟"
    return CatalogQualification(False, prompt, tuple(missing))
