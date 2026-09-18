"""Shared deterministic normalization for catalog language aliases."""

from __future__ import annotations

import re

# Common Egyptian-Arabic spellings mapped to canonical catalog values.
# These aliases normalize explicit wording only; they do not decide conversational intent.
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


def normalize_catalog_text(message: str) -> str:
    """Normalize user wording for explicit alias matching."""
    text = str(message or "").casefold().replace("ـ", "")
    text = re.sub(r"[^\w\u0600-\u06ff]+", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def _explicit_alias(
    message: str,
    aliases_by_canonical: dict[str, tuple[str, ...]],
) -> str | None:
    normalized = normalize_catalog_text(message)
    for canonical, aliases in aliases_by_canonical.items():
        for alias in (canonical, *aliases):
            alias_normalized = normalize_catalog_text(alias)
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
    """Resolve an explicit brand alias to the canonical catalog brand."""
    return _explicit_alias(message, _BRAND_ALIASES)


def explicit_model_from_message(message: str) -> str | None:
    """Resolve an explicit model alias to the canonical catalog model."""
    return _explicit_alias(message, _MODEL_ALIASES)


def explicit_body_type_from_message(message: str) -> str | None:
    """Resolve an explicit body-type alias to the canonical catalog value."""
    return _explicit_alias(message, _BODY_TYPE_ALIASES)


def explicit_fuel_type_from_message(message: str) -> str | None:
    """Resolve an explicit fuel alias to the canonical catalog value."""
    return _explicit_alias(message, _FUEL_TYPE_ALIASES)
