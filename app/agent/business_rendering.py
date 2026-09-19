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
    memory_notice = _contact_memory_notice(status)

    if action_status == "missing_fields":
        missing = [str(field) for field in status.get("missing_fields", [])]
        if not missing:
            return "محتاج شوية بيانات إضافية قبل تنفيذ الطلب."
        if status.get("invalid_preferred_date") and "preferred_date" in missing:
            return (
                "التاريخ ده انتهى، وعشان كده مسجلناش الطلب بالموعد القديم. "
                "ابعت يوم أو تاريخ جديد، ومعاه الوقت المناسب."
            )
        if status.get("ambiguous_time") and "preferred_time" in missing:
            hour = status.get("ambiguous_time_hour")
            if isinstance(hour, int) and 1 <= hour <= 12:
                return (
                    f"تقصد الساعة {hour} صباحًا ولا {hour} العصر/مساءً؟ "
                    "حددها عشان ما نسجلش وقت غلط."
                )
            return "تقصد الوقت صباحًا ولا عصر/مساءً؟ حدده عشان ما نسجلش وقت غلط."
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

        prompt = f"محتاج منك بس: {joined}."
        if memory_notice:
            return f"{memory_notice} لو حابب تغيّرهم ابعت البيانات الجديدة. {prompt}"
        return prompt

    if action_status == "no_active_request":
        return "مفيش طلب تجربة قيادة نشط مرتبط بالمحادثة دي أقدر ألغيه."

    if action_status == "draft_cancelled":
        if intent == "sales_lead":
            return "تم إلغاء استكمال طلب التواصل الحالي، ومفيش بيانات اتسجلت."
        return "تم إلغاء استكمال طلب تجربة القيادة الحالي، ومفيش حجز اتسجل."

    if action_status == "invalid_car":
        car_id = status.get("attempted_car_id")
        suffix = f" رقم {car_id}" if isinstance(car_id, int) else ""
        return (
            f"ملقتش عربية نشطة في الكتالوج{suffix}، وعشان كده مسجلتش أي طلب. "
            "اختار عربية من النتائج الحالية أو ابعت رقم عربية صحيح."
        )

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
        response = (
            f"تم تسجيل طلب تجربة القيادة برقم {request_id}.{suffix} "
            "ده رقم طلب مسجل فعليًا، ومش معناه إن الموعد اتأكد نهائيًا."
        )
        if memory_notice:
            response += f" {memory_notice}"
        return response

    if intent == "sales_lead":
        lead_id = status.get("lead_id")
        if not isinstance(lead_id, int):
            return "مقدرتش أتأكد إن طلب التواصل اتسجل. حاول مرة تانية."
        response = f"تم تسجيل طلب التواصل مع فريق المبيعات برقم {lead_id}."
        if memory_notice:
            response += f" {memory_notice}"
        return response

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


def _contact_memory_notice(status: Mapping[str, Any]) -> str:
    used = [str(field) for field in status.get("memory_fields_used", [])]
    labels = [
        label
        for field, label in (
            ("customer_name", "الاسم"),
            ("phone", "رقم الموبايل"),
            ("email", "البريد الإلكتروني"),
        )
        if field in used
    ]
    if not labels:
        return ""

    scope = str(status.get("customer_memory_scope") or "")
    joined = _join_arabic(labels)
    if scope == "current_session":
        return f"هستخدم {joined} اللي سجلتهم قبل كده في المحادثة دي."
    if scope == "profile":
        return f"هستخدم {joined} المسجل على حسابك."
    if "authenticated_user_history" in scope:
        return f"هستخدم {joined} المسجلين من طلب سابق على حسابك."
    return f"هستخدم {joined} المسجلين عندنا من قبل."


def _join_arabic(values: list[str]) -> str:
    if len(values) == 1:
        return values[0]
    if len(values) == 2:
        return f"{values[0]} و{values[1]}"
    return "، ".join(values[:-1]) + f"، و{values[-1]}"
