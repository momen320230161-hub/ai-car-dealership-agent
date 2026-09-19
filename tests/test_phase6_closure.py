"""Phase 6 closure regressions across the real Flask HTTP adapter."""

from __future__ import annotations

from decimal import Decimal

from app.models.car import Car
from app.models.lead import SalesLead
from app.models.test_drive import TestDriveRequest


def _configure_deterministic_runtime(app) -> None:
    app.config.update(
        AGENT_LLM_PROVIDER="deterministic",
        EMBEDDING_PROVIDER="deterministic",
        EMBEDDING_MODEL="deterministic-test-v1",
        EMBEDDING_DIMENSION=768,
    )


def _csrf_headers(client) -> dict[str, str]:
    with client.session_transaction() as sess:
        token = str(sess.get("_browser_csrf_token") or "test-browser-csrf")
        sess["_browser_csrf_token"] = token
    return {"X-CSRF-Token": token}


def _seed_used_suv(db_session, source_id: str, brand: str, model: str, price: int) -> Car:
    car = Car(
        brand=brand,
        model=model,
        year=2026,
        condition="used",
        price_egp=Decimal(price),
        body_type="SUV",
        transmission="Automatic",
        fuel_type="Gasoline",
        mileage_km=1_000,
        source="phase6-closure",
        source_id=source_id,
        active=True,
    )
    db_session.add(car)
    db_session.commit()
    return car


def test_detail_page_ask_ai_resolves_explicit_car_id_without_llm_guessing(
    app, client, db_session
) -> None:
    _configure_deterministic_runtime(app)
    car = _seed_used_suv(db_session, "details-1", "Chery", "Tiggo 4", 930_000)
    assert client.get("/chat").status_code == 200

    response = client.post(
        "/api/chat/messages",
        json={"message": f"عايز تفاصيل العربية ID {car.id}"},
        headers=_csrf_headers(client),
    )
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["route"] == "catalog"
    assert payload["errors"] == []
    assert "Chery Tiggo 4" in payload["response"]
    assert "930,000" in payload["response"]


def test_visible_comparison_through_browser_api_uses_displayed_positions(
    app, client, db_session
) -> None:
    _configure_deterministic_runtime(app)
    _seed_used_suv(db_session, "compare-1", "Chery", "Tiggo 4", 930_000)
    _seed_used_suv(db_session, "compare-2", "Soueast", "S07", 1_350_000)
    _seed_used_suv(db_session, "compare-3", "Haval", "H6", 1_490_000)
    assert client.get("/chat").status_code == 200
    headers = _csrf_headers(client)

    search = client.post(
        "/api/chat/messages",
        json={"message": "عايز SUV مستعملة"},
        headers=headers,
    )
    search_payload = search.get_json()
    assert search.status_code == 200
    visible = search_payload["visible_recommendations"]
    assert [item["position"] for item in visible] == [1, 2, 3]

    comparison = client.post(
        "/api/chat/messages",
        json={"message": "قارن أول اتنين"},
        headers=headers,
    )
    comparison_payload = comparison.get_json()
    assert comparison.status_code == 200
    assert comparison_payload["route"] == "catalog"
    text = comparison_payload["response"]
    first = visible[0]["car"]
    second = visible[1]["car"]
    assert f"1. {first['brand']} {first['model']}" in text
    assert f"2. {second['brand']} {second['model']}" in text


def test_browser_business_flow_creates_cancels_and_reuses_contact_for_sales_lead(
    app, client, db_session
) -> None:
    _configure_deterministic_runtime(app)
    car = _seed_used_suv(db_session, "actions-1", "Soueast", "S07", 1_350_000)
    assert client.get("/chat").status_code == 200
    headers = _csrf_headers(client)

    start = client.post(
        "/api/chat/messages",
        json={"message": f"عايز احجز تجربة قيادة للعربية ID {car.id}"},
        headers=headers,
    )
    assert start.status_code == 200
    assert start.get_json()["state"]["pending_action_type"] == "test_drive"
    assert db_session.query(TestDriveRequest).count() == 0

    assert (
        client.post(
            "/api/chat/messages",
            json={"message": "اسمي محمد جمال"},
            headers=headers,
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/chat/messages",
            json={"message": "01012345678"},
            headers=headers,
        ).status_code
        == 200
    )
    completed = client.post(
        "/api/chat/messages",
        json={"message": "بكره الساعة 4 مساء"},
        headers=headers,
    )
    assert completed.status_code == 200
    booking = db_session.query(TestDriveRequest).one()
    assert booking.car_id == car.id
    assert booking.customer_name == "محمد جمال"
    assert booking.phone == "01012345678"
    assert booking.status == "NEW"
    assert completed.get_json()["state"]["pending_action_type"] is None

    cancelled = client.post(
        "/api/chat/messages",
        json={"message": "عايز الغي التست درايف"},
        headers=headers,
    )
    assert cancelled.status_code == 200
    db_session.refresh(booking)
    assert booking.status == "CANCELLED"
    assert booking.cancelled_at is not None

    # A later lead should reuse verified Test Drive contact data instead of asking again.
    lead_response = client.post(
        "/api/chat/messages",
        json={"message": "عايز حد من المبيعات يكلمني"},
        headers=headers,
    )
    assert lead_response.status_code == 200
    assert lead_response.get_json()["state"]["pending_action_type"] is None
    lead = db_session.query(SalesLead).one()
    assert lead.customer_name == "محمد جمال"
    assert lead.phone == "01012345678"
    assert lead.status == "NEW"
