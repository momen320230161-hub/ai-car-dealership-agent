"""Deterministic customer-safe rendering from verified structured facts."""

from __future__ import annotations

from typing import Any


def render_catalog(result: dict[str, Any] | None) -> str:
    if not result or result.get("type") == "no_results":
        return "ملقتش عربيات مطابقة حسب البيانات المتاحة عندي في الكتالوج المسجل."
    kind = result.get("type")
    if kind == "recommendations":
        lines = ["حسب البيانات المتاحة عندي في الكتالوج المسجل:"]
        for item in result.get("cars", []):
            car = item["car"]
            lines.append(
                f"{item['position']}. {_name(car)} — {car.get('year')} — "
                f"{_money(car.get('price_egp'))} جنيه"
            )
        return "\n".join(lines)
    if kind in {"car_details", "selection"}:
        car = result["car"]
        prefix = "تم اختيار" if kind == "selection" else "حسب الكتالوج المسجل"
        details = [
            f"{prefix}: {_name(car)}، موديل {car.get('year')}، "
            f"السعر المسجل {_money(car.get('price_egp'))} جنيه."
        ]
        for label, field in (
            ("الحالة", "condition"),
            ("نوع الهيكل", "body_type"),
            ("ناقل الحركة", "transmission"),
            ("الوقود", "fuel_type"),
            ("المسافة", "mileage_km"),
        ):
            value = car.get(field)
            if value is not None:
                suffix = " كم" if field == "mileage_km" else ""
                details.append(f"{label}: {value}{suffix}")
        return "\n".join(details)
    if kind == "comparison":
        lines = ["المقارنة حسب البيانات المتاحة في الكتالوج المسجل:"]
        for position, car in zip(
            result.get("positions", []), result.get("cars", []), strict=True
        ):
            lines.append(
                f"{position}. {_name(car)} — {car.get('year')} — "
                f"{_money(car.get('price_egp'))} جنيه — {car.get('condition')}"
            )
        return "\n".join(lines)
    return "معلش، مقدرتش أعرض بيانات العربية المطلوبة بشكل آمن."


def render_knowledge(supported: bool, result: dict[str, Any] | None) -> str:
    if not supported or not result:
        return "المعلومة دي مش متوفرة حاليًا ضمن المعلومات المعتمدة في قاعدة المعرفة."
    return str(result["content"]).strip()


def render_business_action(intent: str) -> str:
    labels = {
        "test_drive": "حجز تجربة قيادة",
        "cancel_test_drive": "إلغاء تجربة قيادة",
        "sales_lead": "طلب تواصل مع فريق المبيعات",
    }
    label = labels.get(intent, "الطلب")
    return (
        f"فهمت إنك محتاج {label}. تنفيذ الإجراء نفسه لسه غير متاح في المرحلة الحالية، "
        "ومفيش أي طلب اتسجل أو اتأكد."
    )


def render_error(code: str | None) -> str:
    messages = {
        "blank_input": "اكتب سؤالك أو طلبك، وأنا هساعدك.",
        "unsupported_input": "الرسالة لازم تكون نص.",
        "message_too_long": "الرسالة طويلة زيادة. اختصرها شوية وحاول تاني.",
        "sensitive_request": (
            "مقدرش أعرض تعليمات داخلية أو أسرار، لكن أقدر أساعدك "
            "في العربيات والخدمات المتاحة."
        ),
        "understanding_failed": "معلش، مقدرتش أفهم الطلب بشكل آمن. حاول تصيغه بطريقة أبسط.",
        "context_failed": "حصلت مشكلة مؤقتة في تحميل المحادثة. حاول مرة تانية.",
        "state_update_failed": "مقدرتش أحفظ تفضيلاتك حاليًا. حاول مرة تانية.",
        "catalog_unavailable": (
            "القائمة أو العربية المطلوبة مش متاحة في السياق الحالي. "
            "اطلب قائمة عربيات الأول."
        ),
        "rag_failed": "مقدرتش أراجع قاعدة المعرفة حاليًا. حاول مرة تانية.",
    }
    return messages.get(code, "حصلت مشكلة مؤقتة. حاول مرة تانية.")


def _name(car: dict[str, Any]) -> str:
    return " ".join(str(value) for value in (car.get("brand"), car.get("model")) if value)


def _money(value: Any) -> str:
    if value is None:
        return "غير معروف"
    try:
        return f"{float(value):,.0f}"
    except (TypeError, ValueError):
        return str(value)
