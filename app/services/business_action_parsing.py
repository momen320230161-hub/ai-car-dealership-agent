"""Deterministic extraction for customer-supplied business-action fields."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
_CAIRO = ZoneInfo("Africa/Cairo")
_PHONE_RE = re.compile(r"(?<!\d)(?:(?:\+?20)|0)?1[0125](?:[\s-]?\d){8}(?!\d)")
_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_REQUEST_ID_RE = re.compile(
    r"(?:طلب|الحجز|حجز|booking|request)\s*(?:رقم|number|#)?\s*[:#-]?\s*([1-9][0-9]*)",
    re.IGNORECASE,
)
_WEEKDAYS = {
    "الاثنين": 0,
    "الاتنين": 0,
    "monday": 0,
    "الثلاثاء": 1,
    "tuesday": 1,
    "الاربعاء": 2,
    "الأربعاء": 2,
    "wednesday": 2,
    "الخميس": 3,
    "thursday": 3,
    "الجمعة": 4,
    "الجمعه": 4,
    "friday": 4,
    "السبت": 5,
    "saturday": 5,
    "الاحد": 6,
    "الأحد": 6,
    "sunday": 6,
}
_DATE_WORDS = tuple(_WEEKDAYS) + (
    "النهاردة",
    "النهارده",
    "اليوم",
    "today",
    "بكرة",
    "بكره",
    "غدا",
    "غداً",
    "tomorrow",
    "بعد بكرة",
    "بعد بكره",
)
_CLOCK_PREFIX = r"(?:(?:الساعة|الساعه|ساعة|ساعه)\s*|at\s+)"


@dataclass(frozen=True, slots=True)
class ParsedBusinessFields:
    customer_name: str | None = None
    phone: str | None = None
    preferred_date: date | None = None
    preferred_time: time | None = None
    email: str | None = None
    request_id: int | None = None

    def as_json_fields(self) -> dict[str, object]:
        result: dict[str, object] = {}
        if self.customer_name is not None:
            result["customer_name"] = self.customer_name
        if self.phone is not None:
            result["phone"] = self.phone
        if self.preferred_date is not None:
            result["preferred_date"] = self.preferred_date.isoformat()
        if self.preferred_time is not None:
            result["preferred_time"] = self.preferred_time.isoformat(timespec="minutes")
        if self.email is not None:
            result["email"] = self.email
        if self.request_id is not None:
            result["request_id"] = self.request_id
        return result


def cairo_today() -> date:
    """Return the dealership-local calendar date for relative customer dates."""
    return datetime.now(_CAIRO).date()


def parse_business_fields(
    message: str,
    *,
    allow_bare_name: bool = False,
    today: date | None = None,
) -> ParsedBusinessFields:
    """Extract only fields explicitly present in the current customer message."""
    if not isinstance(message, str):
        raise TypeError("message must be text")
    normalized = message.translate(_ARABIC_DIGITS)
    resolved_today = today or cairo_today()
    phone = explicit_phone(normalized)
    email = explicit_email(normalized)
    preferred_date = explicit_date(normalized, today=resolved_today)
    preferred_time = explicit_time(normalized)
    request_id = explicit_request_id(normalized)
    customer_name = explicit_customer_name(
        normalized,
        allow_bare=allow_bare_name,
        phone=phone,
        email=email,
    )
    return ParsedBusinessFields(
        customer_name=customer_name,
        phone=phone,
        preferred_date=preferred_date,
        preferred_time=preferred_time,
        email=email,
        request_id=request_id,
    )


def explicit_phone(message: str) -> str | None:
    """Return an explicitly written Egyptian mobile number in canonical compact form."""
    normalized = message.translate(_ARABIC_DIGITS)
    match = _PHONE_RE.search(normalized)
    if match is None:
        return None
    compact = re.sub(r"[\s-]", "", match.group(0))
    if compact.startswith("+20"):
        return compact
    if compact.startswith("20"):
        return f"+{compact}"
    return compact


def explicit_email(message: str) -> str | None:
    match = _EMAIL_RE.search(message)
    return match.group(0).strip() if match else None


def explicit_request_id(message: str) -> int | None:
    normalized = message.translate(_ARABIC_DIGITS)
    match = _REQUEST_ID_RE.search(normalized)
    return int(match.group(1)) if match else None


def explicit_date(message: str, *, today: date) -> date | None:
    normalized = message.translate(_ARABIC_DIGITS).casefold()

    iso = re.search(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b", normalized)
    if iso:
        return _safe_date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))

    dmy = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](20\d{2})\b", normalized)
    if dmy:
        return _safe_date(int(dmy.group(3)), int(dmy.group(2)), int(dmy.group(1)))

    if any(term in normalized for term in ("بعد بكرة", "بعد بكره")):
        return today + timedelta(days=2)
    if any(term in normalized for term in ("بكرة", "بكره", "غدا", "غداً", "tomorrow")):
        return today + timedelta(days=1)
    if any(term in normalized for term in ("النهاردة", "النهارده", "اليوم", "today")):
        return today

    for label, weekday in _WEEKDAYS.items():
        if label in normalized:
            delta = (weekday - today.weekday()) % 7
            return today + timedelta(days=delta)
    return None


def explicit_time(message: str) -> time | None:
    normalized = message.translate(_ARABIC_DIGITS).casefold()
    pattern = re.compile(
        rf"(?:{_CLOCK_PREFIX})?"
        r"(?<!\d)([01]?\d|2[0-3])(?::([0-5]\d))?\s*"
        r"(صباح(?:ا|اً)?|مساء(?:ا|ً)?|am|pm)?",
        re.IGNORECASE,
    )
    for match in pattern.finditer(normalized):
        # Bare one/two-digit numbers are times only with an explicit clock marker or daypart.
        token = match.group(0).strip()
        clock_markers = ("الساعة", "الساعه", "ساعة", "ساعه", "at")
        has_clock_marker = any(marker in token for marker in clock_markers)
        daypart = match.group(3)
        has_colon = ":" in token
        if not (has_clock_marker or daypart or has_colon):
            continue
        hour = int(match.group(1))
        minute = int(match.group(2) or 0)
        if daypart:
            folded = daypart.casefold()
            if folded.startswith("مساء") or folded == "pm":
                if hour < 12:
                    hour += 12
            elif (folded.startswith("صباح") or folded == "am") and hour == 12:
                hour = 0
        if 0 <= hour <= 23:
            return time(hour=hour, minute=minute)
    return None


def explicit_customer_name(
    message: str,
    *,
    allow_bare: bool,
    phone: str | None,
    email: str | None,
) -> str | None:
    """Extract a marked name, or a bare multi-token name only in a pending workflow."""
    marked = re.search(
        r"(?:اسمي|الاسم(?:\s+هو)?|my\s+name\s+is|name\s+is)\s*[:=-]?\s*"
        r"([A-Za-z\u0600-\u06ff]{2,}(?:\s+[A-Za-z\u0600-\u06ff]{2,}){0,3})",
        message,
        flags=re.IGNORECASE,
    )
    if marked:
        raw_match = marked.group(1)
        stop_markers = (
            r"\b(?:و?رقمي|و?رقم|و?موبايلي|و?الموبايل|و?ايميلي|و?إيميلي|"
            r"و?يوم|الساعة|الساعه|ساعة|ساعه|phone|email)\b"
        )
        raw_match = re.split(stop_markers, raw_match, flags=re.IGNORECASE)[0]
        candidate = _clean_name(raw_match)
        return candidate or None
    if not allow_bare:
        return None

    remainder = message
    remainder = _PHONE_RE.sub(" ", remainder)
    remainder = _EMAIL_RE.sub(" ", remainder)
    remainder = re.sub(r"\b20\d{2}[-/]\d{1,2}[-/]\d{1,2}\b", " ", remainder)
    remainder = re.sub(r"\b\d{1,2}[/-]\d{1,2}[/-]20\d{2}\b", " ", remainder)
    time_pattern = (
        rf"(?:{_CLOCK_PREFIX})?(?:[01]?\d|2[0-3])(?::[0-5]\d)?\s*"
        r"(?:صباح(?:ا|اً)?|مساء(?:ا|اً)?|am|pm)?"
    )
    remainder = re.sub(time_pattern, " ", remainder, flags=re.IGNORECASE)
    for term in sorted(_DATE_WORDS, key=len, reverse=True):
        remainder = re.sub(re.escape(term), " ", remainder, flags=re.IGNORECASE)
    contact_markers = r"\b(?:رقمي|موبايلي|الموبايل|phone|email|ايميلي|إيميلي)\b"
    remainder = re.sub(contact_markers, " ", remainder, flags=re.IGNORECASE)
    non_name_markers = (
        r"\b(?:عربية|سيارة|الأولى|الاولى|الأول|الاول|أول|اول|تاني|تانية|التانية|"
        r"الثاني|الثانية|تالت|تالتة|التالتة|الثالث|الثالثة|على|في|فى|رقم|طلب|حجز|"
        r"تست|درايف|مبيعات|تواصل)\b"
    )
    remainder = re.sub(non_name_markers, " ", remainder, flags=re.IGNORECASE)
    remainder = re.sub(r"[^A-Za-z\u0600-\u06ff\s]", " ", remainder)
    candidate = _clean_name(remainder)
    tokens = candidate.split() if candidate else []
    if 2 <= len(tokens) <= 4 and all(len(token) >= 2 for token in tokens):
        return candidate
    return None


def _clean_name(value: str) -> str:
    return " ".join(value.strip().split())


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None
