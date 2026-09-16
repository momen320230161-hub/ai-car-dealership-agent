"""Deterministic interpretation of conversational search-control language.

This module does not decide vehicle facts. It only converts common conversational
phrasing into safe state operations so the LLM can stay flexible without making
persistent catalog filters behave like a form.
"""

import re


_NON_IDENTITY_FILTERS = (
    "condition",
    "body_type",
    "transmission",
    "fuel_type",
    "min_year",
    "max_year",
    "max_mileage",
)

_RECOMMENDATION_MARKERS = (
    "اعرض",
    "وريني",
    "ورّيني",
    "هات",
    "رشح",
    "اقترح",
    "عايز اشتري",
    "عاوز اشتري",
    "نفسي اركب",
    "show",
    "recommend",
    "suggest",
)

_GENERIC_DONT_CARE = (
    "مش فارق معايا حاجة",
    "مش فارق معايا حاجه",
    "مش فارق معايا",
    "مش فارق",
    "مش مهم",
    "أي حاجة",
    "اي حاجة",
    "أي حاجه",
    "اي حاجه",
    "whatever",
    "anything",
)

_NEW_TERMS = ("زيرو", "جديدة", "جديد", "new")
_USED_TERMS = ("مستعملة", "مستعمل", "استعمال", "used")
_FALLBACK_TERMS = (
    "لو مفيش",
    "ولو مفيش",
    "لو مافيش",
    "ولو مافيش",
    "لو ملقتش",
    "ولو ملقتش",
    "لو مش موجود",
    "otherwise",
    "if not",
)

_BROADEN_MARKERS = (
    "اعرضلي العربيات اللي عندك",
    "اعرضلي العربيات الي عندك",
    "اعرض العربيات اللي عندك",
    "وريني العربيات اللي عندك",
    "وريني العربيات الي عندك",
    "هات العربيات اللي عندك",
    "هات اللي عندك",
    "اعرضلي اللي عندك",
    "وريني الموجود",
    "اعرض الموجود",
    "show me what you have",
)

_PAGINATION_COMMANDS = (
    "هات غير دول",
    "اعرض غير دول",
    "اعرضلي غير دول",
    "وريني غير دول",
    "هات غيرهم",
    "اعرض غيرهم",
    "وريني غيرهم",
    "هات تاني",
    "اعرض تاني",
    "وريني تاني",
    "صفحة تانية",
    "more options",
)

_MORE_QUESTION_MARKERS = (
    "مفيش غير دول",
    "مافيش غير دول",
    "دول بس",
    "هو دول بس",
    "في غير دول",
    "فيه غير دول",
    "any more",
)

_BUDGET_INCREASE_MARKERS = (
    "ازود ال budget",
    "ازود budget",
    "ازود الميزانية",
    "ازود الميزانيه",
    "أزود الميزانية",
    "أزود الميزانيه",
    "ارفع الميزانية",
    "ارفع الميزانيه",
    "increase the budget",
    "raise the budget",
)


class TurnSemantics:
    """Safe control-plane meaning derived from the current customer turn."""

    __slots__ = (
        "mode",
        "clear_fields",
        "force_clear_fields",
        "soft_condition_order",
        "force_catalog_search",
        "pagination_requested",
        "more_results_question",
        "budget_change_unspecified",
    )

    def __init__(
        self,
        *,
        mode: str = "refine",
        clear_fields: tuple[str, ...] = (),
        force_clear_fields: tuple[str, ...] = (),
        soft_condition_order: tuple[str, ...] = (),
        force_catalog_search: bool = False,
        pagination_requested: bool = False,
        more_results_question: bool = False,
        budget_change_unspecified: bool = False,
    ) -> None:
        self.mode = mode
        self.clear_fields = clear_fields
        self.force_clear_fields = force_clear_fields
        self.soft_condition_order = soft_condition_order
        self.force_catalog_search = force_catalog_search
        self.pagination_requested = pagination_requested
        self.more_results_question = more_results_question
        self.budget_change_unspecified = budget_change_unspecified

    def as_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "clear_fields": list(self.clear_fields),
            "force_clear_fields": list(self.force_clear_fields),
            "soft_condition_order": list(self.soft_condition_order),
            "force_catalog_search": self.force_catalog_search,
            "pagination_requested": self.pagination_requested,
            "more_results_question": self.more_results_question,
            "budget_change_unspecified": self.budget_change_unspecified,
        }


def analyze_turn(
    message: str,
    current_preferences: dict[str, object] | None,
    extracted_preferences: dict[str, object] | None,
) -> TurnSemantics:
    """Interpret common Egyptian-Arabic search-control phrases conservatively."""
    text = _normalize(message)
    current = {k: v for k, v in (current_preferences or {}).items() if v not in (None, "")}
    extracted = {
        k: v for k, v in (extracted_preferences or {}).items() if v not in (None, "")
    }

    clear: set[str] = set()
    force_clear: set[str] = set()
    mode = "refine"
    force_search = False

    pagination_requested = any(marker in text for marker in _PAGINATION_COMMANDS)
    more_results_question = any(marker in text for marker in _MORE_QUESTION_MARKERS)
    if pagination_requested:
        mode = "paginate"
    elif more_results_question:
        mode = "availability_question"

    soft_condition_order: tuple[str, ...] = ()
    if (
        any(term in text for term in _NEW_TERMS)
        and any(term in text for term in _USED_TERMS)
        and any(term in text for term in _FALLBACK_TERMS)
    ):
        soft_condition_order = ("new", "used")
        clear.add("condition")
        force_clear.add("condition")
        force_search = True
        mode = "fallback_search"

    generic_dont_care = any(marker in text for marker in _GENERIC_DONT_CARE)
    if generic_dont_care:
        clear.update(_NON_IDENTITY_FILTERS)
        force_clear.update(_NON_IDENTITY_FILTERS)
        force_search = bool(current or extracted)
        if mode == "refine":
            mode = "flexible_search"

    condition_words = any(term in text for term in (*_NEW_TERMS, *_USED_TERMS))
    if generic_dont_care and condition_words and not soft_condition_order:
        clear.add("condition")
        force_clear.add("condition")

    body_words = any(
        term in text
        for term in (
            "suv",
            "sedan",
            "سيدان",
            "هاتشباك",
            "هاتش باك",
            "كوبيه",
            "نوع العربية",
        )
    )
    if generic_dont_care and body_words:
        clear.add("body_type")
        force_clear.add("body_type")

    broadens = any(marker in text for marker in _BROADEN_MARKERS)
    if broadens:
        if current.get("model"):
            clear.add("model")
            force_clear.add("model")
        if any(term in text for term in ("كل العربيات", "أي عربية", "اي عربية", "any car")):
            clear.update(("brand", "model"))
            force_clear.update(("brand", "model"))
        force_search = True
        mode = "broaden"

    new_brand = extracted.get("brand")
    old_brand = current.get("brand")
    if new_brand and old_brand and str(new_brand).casefold() != str(old_brand).casefold():
        clear.add("model")
        # A plain brand pivot starts a new vehicle idea. Preserve budget, but do not
        # silently drag old body/condition/mechanical constraints into the new topic.
        explicit_non_identity = set(extracted).intersection(_NON_IDENTITY_FILTERS)
        for field in _NON_IDENTITY_FILTERS:
            if field not in explicit_non_identity:
                clear.add(field)
        mode = "pivot"

    budget_change_unspecified = (
        any(marker in text for marker in _BUDGET_INCREASE_MARKERS)
        and not _contains_money_amount(text)
    )
    if budget_change_unspecified:
        mode = "budget_discussion"
        force_search = False

    if any(marker in text for marker in _RECOMMENDATION_MARKERS) and (current or extracted):
        force_search = True

    return TurnSemantics(
        mode=mode,
        clear_fields=tuple(sorted(clear)),
        force_clear_fields=tuple(sorted(force_clear)),
        soft_condition_order=soft_condition_order,
        force_catalog_search=force_search,
        pagination_requested=pagination_requested,
        more_results_question=more_results_question,
        budget_change_unspecified=budget_change_unspecified,
    )


def _normalize(value: str) -> str:
    text = str(value or "").casefold().replace("ـ", "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _contains_money_amount(text: str) -> bool:
    normalized = text.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
    if re.search(r"\d", normalized):
        return True
    return any(term in normalized for term in ("مليون", "ألف", "الف", "نص مليون"))
