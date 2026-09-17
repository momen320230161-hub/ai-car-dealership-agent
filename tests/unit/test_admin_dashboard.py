"""HTTP and service regressions for the required admin dashboard."""

from __future__ import annotations

import uuid
from datetime import date, time
from decimal import Decimal

from sqlalchemy import func, select

from app.models.car import Car
from app.models.conversation import ConversationSession
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.models.lead import SalesLead
from app.models.test_drive import TestDriveRequest
from app.models.user import UserProfile


def _login_admin(app, db_session):
    user = UserProfile(
        id=uuid.uuid4(),
        email="admin@example.com",
        display_name="Admin User",
        role="admin",
        active=True,
    )
    db_session.add(user)
    db_session.commit()
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True
    return client


def _csrf(client) -> str:
    with client.session_transaction() as sess:
        return str(sess["_admin_csrf_token"])


def _seed_action_rows(db_session):
    conversation = ConversationSession(id=uuid.uuid4())
    car = Car(
        brand="BMW",
        model="X6",
        year=2022,
        condition="used",
        price_egp=Decimal("3200000"),
        source="admin-test",
        source_id="admin-action-car",
        active=True,
    )
    db_session.add_all([conversation, car])
    db_session.flush()
    drive = TestDriveRequest(
        session_id=conversation.id,
        car_id=car.id,
        customer_name="Admin Test",
        phone="01012345678",
        preferred_date=date(2026, 9, 20),
        preferred_time=time(17, 0),
        idempotency_key="admin-drive-1",
    )
    lead = SalesLead(
        session_id=conversation.id,
        car_id=car.id,
        customer_name="Admin Test",
        phone="01012345678",
        idempotency_key="admin-lead-1",
    )
    db_session.add_all([drive, lead])
    db_session.commit()
    return car, drive, lead


def test_admin_dashboard_requires_authentication(unauthed_client) -> None:
    response = unauthed_client.get("/admin/")

    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


def test_customer_cannot_access_admin_dashboard(client) -> None:
    response = client.get("/admin/")

    assert response.status_code == 403


def test_admin_can_open_required_dashboard_sections(app, db_session) -> None:
    client = _login_admin(app, db_session)

    assert client.get("/admin/").status_code == 200
    assert client.get("/admin/cars").status_code == 200
    assert client.get("/admin/test-drives").status_code == 200
    assert client.get("/admin/leads").status_code == 200
    assert client.get("/admin/knowledge").status_code == 200


def test_admin_car_create_edit_filter_and_deactivate(app, db_session) -> None:
    client = _login_admin(app, db_session)
    form = client.get("/admin/cars/new")
    assert form.status_code == 200
    token = _csrf(client)

    created = client.post(
        "/admin/cars/new",
        data={
            "csrf_token": token,
            "brand": "Toyota",
            "model": "Corolla",
            "year": "2026",
            "condition": "new",
            "price_egp": "1750000",
            "body_type": "Sedan",
            "transmission": "Automatic",
            "fuel_type": "Gasoline",
            "active": "on",
        },
        follow_redirects=False,
    )
    assert created.status_code == 302

    car = db_session.scalar(select(Car).where(Car.brand == "Toyota", Car.model == "Corolla"))
    assert car is not None
    assert car.source == "admin_dashboard"
    assert car.active is True
    assert car.price_egp == Decimal("1750000")

    filtered = client.get("/admin/cars?q=Corolla&condition=new&active=active")
    assert filtered.status_code == 200
    assert "Corolla" in filtered.get_data(as_text=True)

    updated = client.post(
        f"/admin/cars/{car.id}/edit",
        data={
            "csrf_token": token,
            "brand": "Toyota",
            "model": "Corolla",
            "year": "2026",
            "condition": "new",
            "price_egp": "1800000",
            "body_type": "Sedan",
            "transmission": "Automatic",
            "fuel_type": "Gasoline",
            "trim": "Highline",
            "active": "on",
        },
        follow_redirects=False,
    )
    assert updated.status_code == 302
    db_session.refresh(car)
    assert car.price_egp == Decimal("1800000")
    assert car.trim == "Highline"

    deactivated = client.post(
        f"/admin/cars/{car.id}/deactivate",
        data={"csrf_token": token},
        follow_redirects=False,
    )
    assert deactivated.status_code == 302
    db_session.refresh(car)
    assert car.active is False

    inactive = client.get("/admin/cars?q=Corolla&active=inactive")
    assert inactive.status_code == 200
    assert "Corolla" in inactive.get_data(as_text=True)


def test_admin_car_write_requires_valid_required_fields(app, db_session) -> None:
    client = _login_admin(app, db_session)
    client.get("/admin/cars/new")
    token = _csrf(client)

    response = client.post(
        "/admin/cars/new",
        data={
            "csrf_token": token,
            "brand": "",
            "model": "Missing Brand",
            "year": "2026",
            "condition": "new",
            "price_egp": "1000000",
            "active": "on",
        },
    )

    assert response.status_code == 400
    assert db_session.scalar(select(func.count(Car.id))) == 0


def test_admin_business_status_transitions_are_persisted_and_controlled(app, db_session) -> None:
    _, drive, lead = _seed_action_rows(db_session)
    client = _login_admin(app, db_session)
    client.get("/admin/test-drives")
    token = _csrf(client)

    drive_update = client.post(
        f"/admin/test-drives/{drive.id}/status",
        data={"csrf_token": token, "status": "CONFIRMED"},
        follow_redirects=False,
    )
    lead_update = client.post(
        f"/admin/leads/{lead.id}/status",
        data={"csrf_token": token, "status": "CONTACTED"},
        follow_redirects=False,
    )
    assert drive_update.status_code == 302
    assert lead_update.status_code == 302
    db_session.refresh(drive)
    db_session.refresh(lead)
    assert drive.status == "CONFIRMED"
    assert lead.status == "CONTACTED"

    invalid_drive = client.post(
        f"/admin/test-drives/{drive.id}/status",
        data={"csrf_token": token, "status": "NEW"},
        follow_redirects=False,
    )
    invalid_lead = client.post(
        f"/admin/leads/{lead.id}/status",
        data={"csrf_token": token, "status": "NEW"},
        follow_redirects=False,
    )
    assert invalid_drive.status_code == 302
    assert invalid_lead.status_code == 302
    db_session.refresh(drive)
    db_session.refresh(lead)
    assert drive.status == "CONFIRMED"
    assert lead.status == "CONTACTED"


def test_admin_knowledge_write_requires_csrf(app, db_session) -> None:
    app.config.update(
        EMBEDDING_PROVIDER="deterministic",
        EMBEDDING_MODEL="deterministic-test-v1",
    )
    client = _login_admin(app, db_session)

    response = client.post(
        "/admin/knowledge/new",
        data={"title": "Warranty", "category": "warranty", "content": "Coverage text."},
    )

    assert response.status_code == 400
    assert db_session.scalar(select(func.count(KnowledgeDocument.id))) == 0


def test_admin_rag_crud_reindexes_updated_content(app, db_session) -> None:
    app.config.update(
        EMBEDDING_PROVIDER="deterministic",
        EMBEDDING_MODEL="deterministic-test-v1",
    )
    client = _login_admin(app, db_session)

    form = client.get("/admin/knowledge/new")
    assert form.status_code == 200
    token = _csrf(client)

    created = client.post(
        "/admin/knowledge/new",
        data={
            "csrf_token": token,
            "title": "Test Drive Policy",
            "category": "test drive policy",
            "content": "Bring a valid driving licence for the requested test drive.",
            "active": "on",
        },
        follow_redirects=False,
    )
    assert created.status_code == 302

    document = db_session.scalar(select(KnowledgeDocument))
    assert document is not None
    assert document.index_status == "indexed"
    assert document.content_version == 1
    assert document.indexed_version == 1
    first_chunk_count = int(
        db_session.scalar(
            select(func.count(KnowledgeChunk.id)).where(KnowledgeChunk.document_id == document.id)
        )
        or 0
    )
    assert first_chunk_count >= 1

    updated = client.post(
        f"/admin/knowledge/{document.id}/edit",
        data={
            "csrf_token": token,
            "title": "Test Drive Policy",
            "category": "test drive policy",
            "content": "Bring a valid driving licence and arrive ten minutes before the request.",
            "active": "on",
        },
        follow_redirects=False,
    )
    assert updated.status_code == 302
    db_session.refresh(document)
    assert document.content_version == 2
    assert document.indexed_version == 2
    assert document.index_status == "indexed"

    reindexed = client.post(
        f"/admin/knowledge/{document.id}/reindex",
        data={"csrf_token": token},
        follow_redirects=False,
    )
    assert reindexed.status_code == 302
    db_session.refresh(document)
    assert document.index_status == "indexed"
    assert document.indexed_version == 2

    deleted = client.post(
        f"/admin/knowledge/{document.id}/delete",
        data={"csrf_token": token},
        follow_redirects=False,
    )
    assert deleted.status_code == 302
    assert db_session.get(KnowledgeDocument, document.id) is None
    assert db_session.scalar(select(func.count(KnowledgeChunk.id))) == 0
