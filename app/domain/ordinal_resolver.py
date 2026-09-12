"""Controlled, deterministic visible-list ordinal parsing."""

from __future__ import annotations

import re


class InvalidOrdinalError(ValueError):
    """Raised when a reference is not in the controlled ordinal vocabulary."""


_ORDINALS = {
    "first": 1,
    "first one": 1,
    "second": 2,
    "third": 3,
    "الأول": 1,
    "الاول": 1,
    "اول": 1,
    "أول": 1,
    "اول واحد": 1,
    "أول واحد": 1,
    "الأول واحد": 1,
    "الاول واحد": 1,
    "التاني": 2,
    "الثاني": 2,
    "الثالث": 3,
    "التالت": 3,
}


def parse_ordinal(reference: int | str) -> int:
    """Resolve a positive numeric or explicitly supported ordinal reference."""
    if isinstance(reference, bool):
        raise InvalidOrdinalError("Boolean values are not valid visible positions")
    if isinstance(reference, int):
        if reference > 0:
            return reference
        raise InvalidOrdinalError("Visible position must be positive")

    normalized = " ".join(str(reference).strip().split())
    numeric = re.fullmatch(r"#?([1-9][0-9]*)", normalized)
    if numeric:
        return int(numeric.group(1))
    if normalized.lower() in _ORDINALS:
        return _ORDINALS[normalized.lower()]
    if normalized in _ORDINALS:
        return _ORDINALS[normalized]
    raise InvalidOrdinalError(f"Unsupported visible-list ordinal: {reference!r}")
