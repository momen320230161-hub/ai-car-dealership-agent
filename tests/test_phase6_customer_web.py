"""Phase 6 customer Flask website, browser-session, and graph integration tests."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

from app.agent.llm import AgentLLMError
from app.models.car import Car
from app.models.conversation import ConversationSession
from app.models.message import ChatMessage
from app.models.test_drive import TestDriveRequest


def _configure_deterministic_runtime(app) -> None:
    app.config.update(
        AGENT_LLM_PROVIDER="deterministic",
        EMBEDDING_PROVIDER="deterministic",
        EMBEDDING_MODEL="deterministic-test-v1",
        EMBEDDING_DIMENSION=768,
    )


def _car(
    source_id: str,
    *,
    brand: str,
    model: str,
    price: int,
    condition: str = "used",
    body_type: str = "SUV",
    year: int = 2026,
    mileage_km: int | None = 1_000,
) -> Car:
    return Car(
        brand=brand,
        model=model,
        year=year,
        condition=condition,
        price_egp=Decimal(price),
        body_type=body_type,
        transmission="Automatic",
        fuel_type="Gasoline",
        mileage_km=mileage_km,
        source="phase6-test",
        source_id=source_id,
        active=True,
    )


def _seed_catalog(db_session) -> list[Car]:
    cars = [
        _car("p6-1", brand="Chery", model="Tiggo 4", price=930_000, mileage_km=7_500),
        _car("p6-2", brand="Soueast", model="S07", price=1_350_000, mileage_km=4_300),
        _car("p6-3", brand="Haval", model="H6", price=1_490_000, mileage_km=1_000),
        _car(
            "p6-4",
            brand="Toyota",
            model="Corolla",
            price=1_650_000,
            condition="new",
            body_type="Sedan",
            mileage_km=0,
        ),
    ]
    db_session.add_all(cars)
    db_session.commit()
    return cars


def test_home_catalog_and_detail_render_recorded_data(app, client, db_session) -> None:
    cars = _seed_catalog(db_session)
    home = client.get("/")
    assert home.status_code == 200
    assert "AutoDrive Egypt" in home.get_data(as_text=True)
    catalog = client.get("/cars?condition=used&body_type=SUV&max_price=1000000")
    body = catalog.get_data(as_text=True)
    assert catalog.status_code == 200
    assert "Chery" in body and "Tiggo 4" in body
    assert f'href="/cars/{cars[0].id}"' in body
    assert f'href="/cars/{cars[1].id}"' not in body
    detail = client.get(f"/cars/{cars[0].id}")
    detail_body = detail.get_data(as_text=True)
    assert detail.status_code == 200
    assert "Chery" in detail_body and "930,000" in detail_body
    assert "صورة توضيحية" in detail_body
    assert client.get("/cars/999999").status_code == 404


def test_chat_page_creates_and_reuses_one_browser_session(app, client, db_session) -> None:
    _configure_deterministic_runtime(app)
    assert client.get("/chat").status_code == 200
    assert db_session.query(ConversationSession).count() == 1
    first_id = db_session.query(ConversationSession).one().id
    assert client.get("/chat").status_code == 200
    assert db_session.query(ConversationSession).count() == 1
    assert db_session.query(ConversationSession).one().id == first_id


def test_chat_post_invokes_graph_and_persists_turn_exactly_once(app, client, db_session) -> None:
    _configure_deterministic_runtime(app)
    _seed_catalog(db_session)
    assert client.get("/chat").status_code == 200
    response = client.post("/api/chat/messages", json={"message": "عايز SUV مستعملة"})
    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True and payload["route"] == "catalog"
    assert len(payload["visible_recommendations"]) == 3
    assert [item["position"] for item in payload["visible_recommendations"]] == [1, 2, 3]
    conversation = db_session.query(ConversationSession).one()
    messages = (
        db_session.query(ChatMessage)
        .filter(ChatMessage.session_id == conversation.id)
        .order_by(ChatMessage.id)
        .all()
    )
    assert [message.role for message in messages] == ["user", "assistant"]
    assert messages[0].content == "عايز SUV مستعملة"
    refreshed = client.get("/chat")
    assert refreshed.status_code == 200
    assert "عايز SUV مستعملة" in refreshed.get_data(as_text=True)
    assert db_session.query(ChatMessage).count() == 2


def test_detail_booking_cta_resolves_explicit_catalog_car(app, client, db_session) -> None:
    _configure_deterministic_runtime(app)
    cars = _seed_catalog(db_session)
    assert client.get("/chat").status_code == 200

    response = client.post(
        "/api/chat/messages",
        json={"message": f"عايز احجز تجربة قيادة للعربية ID {cars[0].id}"},
    )
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["ok"] is True and payload["route"] == "business_gate"
    conversation = db_session.query(ConversationSession).one()
    pending = dict(conversation.pending_action or {})
    assert pending["type"] == "test_drive"
    assert pending["fields"]["car_id"] == cars[0].id
    assert db_session.query(TestDriveRequest).count() == 0


def test_new_chat_and_separate_clients_are_session_isolated(app, db_session) -> None:
    _configure_deterministic_runtime(app)
    first_client = app.test_client()
    second_client = app.test_client()
    assert first_client.get("/chat").status_code == 200
    assert second_client.get("/chat").status_code == 200
    assert db_session.query(ConversationSession).count() == 2
    before_ids = {row.id for row in db_session.query(ConversationSession).all()}
    reset = first_client.post("/api/chat/session")
    assert reset.status_code == 200 and reset.get_json()["ok"] is True
    after_ids = {row.id for row in db_session.query(ConversationSession).all()}
    assert len(after_ids) == 3 and before_ids < after_ids


def test_blank_chat_input_is_rejected_without_persistence(app, client, db_session) -> None:
    _configure_deterministic_runtime(app)
    assert client.get("/chat").status_code == 200
    response = client.post("/api/chat/messages", json={"message": "   "})
    assert response.status_code == 400 and response.get_json()["ok"] is False
    assert db_session.query(ChatMessage).count() == 0


def test_chat_dependency_failure_returns_safe_error(app, client, db_session) -> None:
    _configure_deterministic_runtime(app)
    assert client.get("/chat").status_code == 200
    with patch(
        "app.blueprints.chat.routes.build_sales_orchestrator",
        side_effect=AgentLLMError("super-secret-provider-detail"),
    ):
        response = client.post("/api/chat/messages", json={"message": "عايز عربية"})
    body = response.get_data(as_text=True)
    assert response.status_code == 503 and response.get_json()["ok"] is False
    assert "super-secret-provider-detail" not in body and "Traceback" not in body
    assert db_session.query(ChatMessage).count() == 0
