"""Deterministic catalog-language normalization and sales qualification."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping


# Common Egyptian-Arabic spellings that cannot be validated by a literal
# substring check against the English canonical brand stored in the catalog.
# Keep this intentionally explicit/auditable instead of fuzzy-matching brands.
_BRAND_ALIASES: dict[str, tuple[str, ...]] = {
    "BMW": ("بي ام", "بي إم", "بى ام", "بي ام دبليو", "بي إم دبليو", "بى ام دبليو"),
    "Mercedes-Benz": ("مرسيدس", "مرسيدس بنز"),
    "Audi": ("اودي", "أودي"),
    "Toyota": ("تويوتا",),
    "Hyundai": ("هيونداي", "هيونداى"),
    "Kia": ("كيا",),
    "Nissan": ("نيسان",),
    "Renault": ("رينو",),
    "Peugeot": ("بيجو",),
    "Skoda": ("سكودا", "شكودا"),
    "Volkswagen": ("فولكس فاجن", "فولكس واجن"),
    "Chery": ("شيري", "شيرى"),
    "Chevrolet": ("شيفروليه", "شيفروليه"),
    "MG": ("ام جي", "إم جي", "ام جى", "إم جى"),
    "Opel": ("اوبل", "أوبل"),
    "Fiat": ("فيات",),
    "Mitsubishi": ("ميتسوبيشي",),
    "Citroen": ("ستروين", "سيتروين"),
    "Seat": ("سيات",),
    "Suzuki": ("سوزوكي",),
    "Honda": ("هوندا",),
    "Mazda": ("مازدا",),
    "Geely": ("جيلي", "جيلى"),
    "BYD": ("بي واي دي", "بى واى دى"),
    "Jetour": ("جيتور",),
    "Haval": ("هافال",),
    "Porsche": ("بورش",),
    "Volvo": ("فولفو",),
    "Lexus": ("لكزس", "ليكسس"),
    "Land Rover": ("لاند روفر",),
    "Jeep": ("جيب",),
}

_RECOMMENDATION_MARKERS = (
    "رشح",
    "اقترح",
    "اختارلي",
    "اختار لي",
    "وريني",
    "ورّيني",
    "recommend",
    "suggest",
    "show me",
    "options",
)


@dataclass(frozen=True, slots=True)
class CatalogQualification:
    """Whether a broad catalog request is ready to create a visible shortlist."""

    ready: bool
    message: str | None = None
    missing: tuple[str, ...] = ()


def _normalized(message: str) -> str:
    text = message.casefold().replace("ـ", "")
    text = re.sub(r"[^\w\u0600-\u06ff]+", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def explicit_brand_from_message(message: str) -> str | None:
    """Resolve only explicit, allowlisted Arabic brand aliases to catalog names."""
    normalized = _normalized(message)
    for canonical, aliases in _BRAND_ALIASES.items():
        for alias in aliases:
            alias_normalized = _normalized(alias)
            if re.search(rf"(?<!\w){re.escape(alias_normalized)}(?!\w)", normalized):
                return canonical
    return None


def explicitly_requests_recommendation(message: str) -> bool:
    normalized = _normalized(message)
    return any(marker in normalized for marker in _RECOMMENDATION_MARKERS)


def qualify_catalog_search(
    preferences: Mapping[str, Any] | None,
    message: str,
) -> CatalogQualification:
    """Ask for high-value missing preferences before creating a broad shortlist.

    The function deliberately avoids requiring every possible filter. It only
    prevents low-signal recommendations such as "I have 2M" immediately
    becoming an arbitrary top-three list.
    """
    prefs = {key: value for key, value in (preferences or {}).items() if value is not None}
    brand = str(prefs.get("brand") or "").strip()
    model = str(prefs.get("model") or "").strip()
    condition = str(prefs.get("condition") or "").strip()
    body_type = str(prefs.get("body_type") or "").strip()
    wants_recommendation = explicitly_requests_recommendation(message)

    if model:
        if not condition:
            return CatalogQualification(
                False,
                f"تمام، فهمت إنك بتدور على {brand + ' ' if brand else ''}{model}. "
                "تحبها جديدة ولا مستعملة؟",
                ("condition",),
            )
        return CatalogQualification(True)

    if brand:
        if not wants_recommendation:
            suffix = ""
            missing: list[str] = ["model_or_recommendation"]
            if not condition:
                suffix = " ولو تحب أرشحلك، تحبها جديدة ولا مستعملة؟"
                missing.append("condition")
            return CatalogQualification(
                False,
                f"تمام، فهمت إنك بتدور على {brand}. في موديل معين في دماغك، "
                f"ولا تحب أرشحلك من الموجود في الكتالوج؟{suffix}",
                tuple(missing),
            )
        if not condition:
            return CatalogQualification(
                False,
                f"تمام، أرشحلك من {brand}. تحبها جديدة ولا مستعملة؟",
                ("condition",),
            )
        return CatalogQualification(True)

    missing: list[str] = []
    if not condition:
        missing.append("condition")
    if not body_type:
        missing.append("body_type")
    if not missing:
        return CatalogQualification(True)

    if missing == ["condition", "body_type"]:
        prompt = (
            "تمام. قبل ما أرشحلك عربيات مناسبة: تحبها جديدة ولا مستعملة؟ "
            "ونوع العربية يفضل يكون SUV ولا Sedan ولا نوع تاني؟ "
            "ولو في ماركة أو موديل في دماغك قولي."
        )
    elif missing == ["condition"]:
        prompt = "تمام. تحب العربية جديدة ولا مستعملة؟"
    else:
        prompt = "تمام. تفضل نوع العربية SUV ولا Sedan ولا نوع تاني؟"
    return CatalogQualification(False, prompt, tuple(missing))
