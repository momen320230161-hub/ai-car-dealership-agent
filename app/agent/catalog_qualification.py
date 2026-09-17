"""Deterministic catalog-language normalization and sales qualification."""

import re

# Common Egyptian-Arabic spellings that cannot be validated by a literal
# substring check against the English canonical values stored in the catalog.
# Keep these intentionally explicit/auditable instead of fuzzy matching.
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
    "Chevrolet": ("شيفروليه",),
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

_MODEL_ALIASES: dict[str, tuple[str, ...]] = {
    "X6": ("اكس 6", "إكس 6", "اكس٦", "إكس٦"),
    "X5": ("اكس 5", "إكس 5", "اكس٥", "إكس٥"),
    "X3": ("اكس 3", "إكس 3", "اكس٣", "إكس٣"),
    "X2": ("اكس 2", "إكس 2", "اكس٢", "إكس٢"),
    "X1": ("اكس 1", "إكس 1", "اكس١", "إكس١"),
    "Tiggo 4": ("تيجو 4", "تيجو ٤", "تيجو4"),
    "Tiggo 7": ("تيجو 7", "تيجو ٧", "تيجو7"),
    "Tiggo 8": ("تيجو 8", "تيجو ٨", "تيجو8"),
    "S07": ("اس 07", "إس 07", "اس07", "اس ٠٧"),
    "H6": ("اتش 6", "إتش 6", "اتش6", "اتش ٦"),
    "Tucson": ("توسان", "توسون"),
    "Sportage": ("سبورتاج",),
    "Qashqai": ("قشقاي", "كاشكاي"),
    "C-Class": ("سي كلاس", "سي-كلاس"),
    "E-Class": ("اي كلاس", "إي كلاس", "اي-كلاس"),
    "S-Class": ("اس كلاس", "إس كلاس", "اس-كلاس"),
}

_BODY_TYPE_ALIASES: dict[str, tuple[str, ...]] = {
    "SUV": ("اس يو في", "إس يو في", "اس يو فى", "إس يو فى"),
    "Sedan": ("سيدان",),
    "Hatchback": ("هاتشباك", "هاتش باك"),
    "Coupe": ("كوبيه",),
    "Crossover": ("كروس اوفر", "كروس أوفر"),
    "Convertible": ("كابورليه", "مكشوفة"),
    "Pickup": ("بيك اب", "بيك أب"),
    "Van": ("فان",),
    "Wagon": ("واجن",),
    "MPV": ("ام بي في", "إم بي في"),
    "4X4": ("دفع رباعي", "4x4"),
}

_FUEL_TYPE_ALIASES: dict[str, tuple[str, ...]] = {
    "Gasoline": ("بنزين", "petrol"),
    "Diesel": ("ديزل",),
    "Electric": ("كهربا", "كهرباء", "كهربائية"),
    "Hybrid": ("هايبرد", "هجين"),
    "Natural Gas": ("غاز طبيعي",),
    "Gasoline/CNG": ("بنزين وغاز", "بنزين غاز"),
}

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


def _normalized(message: str) -> str:
    text = message.casefold().replace("ـ", "")
    text = re.sub(r"[^\w\u0600-\u06ff]+", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def _explicit_alias(
    message: str,
    aliases_by_canonical: dict[str, tuple[str, ...]],
) -> str | None:
    normalized = _normalized(message)
    for canonical, aliases in aliases_by_canonical.items():
        for alias in (canonical, *aliases):
            alias_normalized = _normalized(alias)
            optional_article = (
                r"(?:ال)?" if re.search(r"[\u0600-\u06ff]", alias_normalized) else ""
            )
            if re.search(
                rf"(?<!\w){optional_article}{re.escape(alias_normalized)}(?!\w)",
                normalized,
            ):
                return canonical
    return None


def explicit_brand_from_message(message: str) -> str | None:
    """Resolve only explicit, allowlisted Arabic brand aliases to catalog names."""
    return _explicit_alias(message, _BRAND_ALIASES)


def explicit_model_from_message(message: str) -> str | None:
    """Resolve explicit Arabic model wording to canonical catalog values."""
    return _explicit_alias(message, _MODEL_ALIASES)


def explicit_body_type_from_message(message: str) -> str | None:
    """Resolve common Arabic body-type wording to canonical catalog values."""
    return _explicit_alias(message, _BODY_TYPE_ALIASES)


def explicit_fuel_type_from_message(message: str) -> str | None:
    """Resolve common Arabic fuel wording to canonical catalog values."""
    return _explicit_alias(message, _FUEL_TYPE_ALIASES)


def explicitly_requests_recommendation(message: str) -> bool:
    normalized = _normalized(message)
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
            cond_str = f" {_condition_text(condition)}" if condition else ""
            verb = "سجلت" if condition else "فهمت"
            return CatalogQualification(
                False,
                f"تمام، {verb} إنك بتدور على {brand}{cond_str}. في موديل معين في دماغك "
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

    if condition and not body_type and set(prefs) == {"condition"}:
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
