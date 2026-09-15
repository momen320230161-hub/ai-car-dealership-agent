"""Deterministic customer-safe rendering from verified structured facts."""

from __future__ import annotations

from typing import Any


def render_catalog(result: dict[str, Any] | None) -> str:
    if not result or result.get("type") == "no_results":
        return "ملقتش عربيات مطابقة حسب البيانات المتاحة عندي في الكتالوج المسجل."
    kind = result.get("type")
    if kind == "clarification":
        message = str(result.get("message") or "").strip()
        return message or "محتاج أعرف شوية تفضيلات أكتر قبل ما أرشحلك عربيات."
    if kind == "fallback_condition":
        car_name = str(result.get("car_name") or "").strip()
        cond_text = str(result.get("available_condition_text") or "").strip()
        return (
            f"لقيت {car_name} حسب الكتالوج المسجل، لكنها متاحة كسيارة {cond_text}. "
            "هل تحب أعرض التفاصيل؟"
        )
    if kind == "relaxed_suggestion":
        original_price = result.get("original_max_price")
        cheapest_price = result.get("cheapest_price")
        cars = result.get("cars", [])
        lines = [
            f"ملقتش عربيات مطابقة تماماً تحت {_money(original_price)} جنيه، "
            f"لكن لقيت أقرب خيارات متاحة بتبدأ من {_money(cheapest_price)} جنيه:"
        ]
        for idx, item in enumerate(cars, start=1):
            car = item.get("car", item) if isinstance(item, dict) else item
            facts = [
                f"{idx}. {_name(car)}",
                str(car.get("year")) if car.get("year") is not None else "سنة غير معروفة",
            ]
            condition = _condition_label(car.get("condition"))
            if condition is not None:
                facts.append(condition)
            facts.append(f"{_money(car.get('price_egp'))} جنيه")
            lines.append(" — ".join(facts))
        lines.append("تحب أعرضلك تفاصيل واحدة منهم ولا نغير الشروط؟")
        return "\n".join(lines)
    if kind == "recommendations":
        lines = ["حسب البيانات المتاحة عندي في الكتالوج المسجل:"]
        for item in result.get("cars", []):
            car = item["car"]
            facts = [
                f"{item['position']}. {_name(car)}",
                str(car.get("year")) if car.get("year") is not None else "سنة غير معروفة",
            ]
            condition = _condition_label(car.get("condition"))
            if condition is not None:
                facts.append(condition)
            mileage = _mileage(car.get("mileage_km"))
            if mileage is not None:
                facts.append(mileage)
            facts.append(f"{_money(car.get('price_egp'))} جنيه")
            lines.append(" — ".join(facts))
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
        return _render_comparison(result)
    return "معلش، مقدرتش أعرض بيانات العربية المطلوبة بشكل آمن."


def render_knowledge(supported: bool, result: dict[str, Any] | None) -> str:
    if not supported or not result:
        return "المعلومة دي مش متوفرة حاليًا ضمن المعلومات المعتمدة في قاعدة المعرفة."
    return str(result["content"]).strip()


def render_error(code: str | None) -> str:
    messages = {
        "blank_input": "اكتب سؤالك أو طلبك، وأنا هساعدك.",
        "unsupported_input": "الرسالة لازم تكون نص.",
        "message_too_long": "الرسالة طويلة زيادة. اختصرها شوية وحاول تاني.",
        "sensitive_request": (
            "مقدرش أعرض تعليمات داخلية أو أسرار، لكن أقدر أساعدك في العربيات والخدمات المتاحة."
        ),
        "understanding_failed": "معلش، مقدرتش أفهم الطلب بشكل آمن. حاول تصيغه بطريقة أبسط.",
        "context_failed": "حصلت مشكلة مؤقتة في تحميل المحادثة. حاول مرة تانية.",
        "state_update_failed": "مقدرتش أحفظ تفضيلاتك حاليًا. حاول مرة تانية.",
        "catalog_unavailable": (
            "القائمة أو العربية المطلوبة مش متاحة في السياق الحالي. اطلب قائمة عربيات الأول."
        ),
        "rag_failed": "مقدرتش أراجع قاعدة المعرفة حاليًا. حاول مرة تانية.",
        "business_action_failed": "مقدرتش أنفذ الطلب حاليًا. حاول مرة تانية.",
    }
    return messages.get(code, "حصلت مشكلة مؤقتة. حاول مرة تانية.")


def _render_comparison(result: dict[str, Any]) -> str:
    positions = list(result.get("positions", []))
    cars = list(result.get("cars", []))
    if len(positions) != len(cars) or len(cars) < 2:
        return "معلش، مقدرتش أعرض المقارنة المطلوبة بشكل آمن."

    lines = ["المقارنة حسب البيانات المتاحة في الكتالوج المسجل:"]
    for position, car in zip(positions, cars, strict=True):
        year = car.get("year")
        year_text = f"موديل {year}" if year is not None else "سنة الموديل غير مسجلة"
        lines.extend(["", f"{position}. {_name(car)} — {year_text}"])
        for fact in _comparison_facts(car):
            lines.append(f"- {fact}")

    differences = _comparison_differences(positions, cars)
    if differences:
        lines.extend(["", "أبرز الفروق:"])
        lines.extend(f"- {difference}" for difference in differences)

    lines.extend(
        [
            "",
            "لو عايز، قولي إيه الأهم بالنسبالك — السعر، سنة الموديل، الممشى "
            "أو مواصفة معينة — وأساعدك تختار بينهم حسب البيانات المسجلة.",
        ]
    )
    return "\n".join(lines)


def _comparison_facts(car: dict[str, Any]) -> list[str]:
    facts: list[str] = []
    condition = _condition_label(car.get("condition"))
    if condition is not None:
        facts.append(f"الحالة: {condition}")
    if car.get("price_egp") is not None:
        facts.append(f"السعر: {_money(car.get('price_egp'))} جنيه")
    mileage = _mileage(car.get("mileage_km"))
    if mileage is not None:
        facts.append(f"الممشى: {mileage}")

    for label, field in (
        ("نوع الهيكل", "body_type"),
        ("ناقل الحركة", "transmission"),
        ("الوقود", "fuel_type"),
    ):
        value = _text(car.get(field))
        if value is not None:
            facts.append(f"{label}: {value}")

    engine = _number(car.get("engine_capacity_cc"))
    if engine is not None:
        facts.append(f"سعة المحرك: {engine} cc")
    horsepower = _number(car.get("horsepower"))
    if horsepower is not None:
        facts.append(f"القوة: {horsepower} حصان")

    for label, field in (("نظام الدفع", "powertrain_type"), ("الفئة", "trim")):
        value = _text(car.get(field))
        if value is not None:
            facts.append(f"{label}: {value}")
    return facts


def _comparison_differences(
    positions: list[Any],
    cars: list[dict[str, Any]],
) -> list[str]:
    if len(cars) != 2:
        return []

    left, right = cars
    left_label = _comparison_label(positions[0], left)
    right_label = _comparison_label(positions[1], right)
    differences: list[str] = []

    left_year = _numeric(left.get("year"))
    right_year = _numeric(right.get("year"))
    if left_year is not None and right_year is not None and left_year != right_year:
        newer_label = left_label if left_year > right_year else right_label
        year_difference = int(abs(left_year - right_year))
        differences.append(f"{newer_label} أحدث {_year_difference_text(year_difference)}.")

    left_mileage = _numeric(left.get("mileage_km"))
    right_mileage = _numeric(right.get("mileage_km"))
    if left_mileage is not None and right_mileage is not None and left_mileage != right_mileage:
        lower_mileage_label = left_label if left_mileage < right_mileage else right_label
        mileage_difference = abs(left_mileage - right_mileage)
        differences.append(f"{lower_mileage_label} ممشاها أقل بـ {_number(mileage_difference)} كم.")

    left_price = _numeric(left.get("price_egp"))
    right_price = _numeric(right.get("price_egp"))
    if left_price is not None and right_price is not None and left_price != right_price:
        cheaper_label = left_label if left_price < right_price else right_label
        price_difference = abs(left_price - right_price)
        differences.append(f"{cheaper_label} أرخص بـ {_money(price_difference)} جنيه.")

    left_engine = _numeric(left.get("engine_capacity_cc"))
    right_engine = _numeric(right.get("engine_capacity_cc"))
    if left_engine is not None and right_engine is not None and left_engine != right_engine:
        larger_engine_label = left_label if left_engine > right_engine else right_label
        engine_difference = abs(left_engine - right_engine)
        differences.append(
            f"سعة المحرك المسجلة في {larger_engine_label} أكبر بـ {_number(engine_difference)} cc."
        )

    return differences


def _comparison_label(position: Any, car: dict[str, Any]) -> str:
    year = f" {car['year']}" if car.get("year") is not None else ""
    return f"#{position} {_name(car)}{year}"


def _year_difference_text(value: int) -> str:
    if value == 1:
        return "بسنة واحدة"
    if value == 2:
        return "بسنتين"
    return f"بـ {value} سنوات"


def _name(car: dict[str, Any]) -> str:
    return " ".join(str(value) for value in (car.get("brand"), car.get("model")) if value)


def _condition_label(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().casefold()
    if normalized == "used":
        return "مستعملة"
    if normalized == "new":
        return "جديدة"
    return str(value).strip() or None


def _mileage(value: Any) -> str | None:
    number = _numeric(value)
    if number is not None:
        return f"{number:,.0f} كم"
    text = _text(value)
    return f"{text} كم" if text is not None else None


def _money(value: Any) -> str:
    number = _numeric(value)
    if number is not None:
        return f"{number:,.0f}"
    return _text(value) or "غير معروف"


def _number(value: Any) -> str | None:
    number = _numeric(value)
    if number is not None:
        return f"{number:,.0f}"
    return _text(value)


def _numeric(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
