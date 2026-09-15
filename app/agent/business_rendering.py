"""Customer-safe deterministic rendering for real business actions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

_FIELD_LABELS = {
    "car_id": "العربية اللي عايز تعمل لها تجربة قيادة",
    "customer_name": "اسمك",
    "phone": "رقم الموبايل",
    "preferred_date": "اليوم أو التاريخ المناسب",
    "preferred_time": "الوقت المناسب",
    "request_id": "رقم طلب تجربة القيادة المراد إلغاؤه",
}


def render_business_action(
    status: Mapping[str, Any] | None,
    *,
    user_message: str | None = None,
) -> str:
    """Render only verified action state; never imply success without a real row ID."""
    if not status:
        return "مقدرتش أحدد حالة الطلب حاليًا. حاول مرة تانية."

    action_status = str(status.get("status") or "")
    intent = str(status.get("intent") or "")

    if action_status == "missing_fields":
        missing = [str(field) for field in status.get("missing_fields", [])]
        if not missing:
            return "محتاج شوية بيانات إضافية قبل تنفيذ الطلب."
        if missing == ["request_id"]:
            candidates = _integer_ids(status.get("candidate_request_ids"))
            if candidates:
                ids = "، ".join(str(value) for value in candidates)
                return (
                    "عندك أكتر من طلب تجربة قيادة نشط مرتبط بالمحادثة دي. "
                    f"قولي رقم الطلب اللي عايز تلغيه من: {ids}."
                )
        labels = [_FIELD_LABELS.get(field, field) for field in missing]
        joined = _join_arabic(labels)

        msg_lower = (user_message or "").casefold()
        why_terms = ("ليه", "لماذا", "اشمعنى", "ازاي", "إزاي", "عشان", "why")
        if any(term in msg_lower for term in why_terms):
            if intent == "test_drive":
                return (
                    "عشان نقدر ننسق معاك موعد تجربة القيادة ومسؤول المبيعات "
                    f"يتواصل معاك لتأكيد الحجز. محتاجين منك بس: {joined}."
                )
            if intent == "sales_lead":
                return (
                    "عشان مسؤول المبيعات يقدر يتواصل معاك ويتابع معاك التفاصيل. "
                    f"محتاجين منك بس: {joined}."
                )

        return f"محتاج منك بس: {joined}."

    if action_status == "no_active_request":
        return "مفيش طلب تجربة قيادة نشط مرتبط بالمحادثة دي أقدر ألغيه."

    if action_status != "success":
        return "مقدرتش أنفذ الطلب حاليًا. حاول مرة تانية."

    if intent == "test_drive":
        request_id = status.get("request_id")
        if not isinstance(request_id, int):
            return "مقدرتش أتأكد إن طلب تجربة القيادة اتسجل. حاول مرة تانية."
        date_text = str(status.get("preferred_date") or "").strip()
        time_text = str(status.get("preferred_time") or "").strip()
        suffix = ""
        if date_text and time_text:
            suffix = f" الموعد المطلوب: {date_text} الساعة {time_text}."
        return (
            f"تم تسجيل طلب تجربة القيادة برقم {request_id}.{suffix} "
            "ده رقم طلب مسجل فعليًا، ومش معناه إن الموعد اتأكد نهائيًا."
        )

    if intent == "sales_lead":
        lead_id = status.get("lead_id")
        if not isinstance(lead_id, int):
            return "مقدرتش أتأكد إن طلب التواصل اتسجل. حاول مرة تانية."
        return f"تم تسجيل طلب التواصل مع فريق المبيعات برقم {lead_id}."

    if intent == "cancel_test_drive":
        request_id = status.get("request_id")
        if not isinstance(request_id, int):
            return "مقدرتش أتأكد إن الإلغاء تم. حاول مرة تانية."
        return f"تم إلغاء طلب تجربة القيادة رقم {request_id}."

    return "تم تنفيذ الطلب وتسجيله بنجاح."


def _integer_ids(value: Any) -> list[int]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [item for item in value if isinstance(item, int) and not isinstance(item, bool)]


def _join_arabic(values: list[str]) -> str:
    if len(values) == 1:
        return values[0]
    if len(values) == 2:
        return f"{values[0]} و{values[1]}"
    return "، ".join(values[:-1]) + f"، و{values[-1]}"
