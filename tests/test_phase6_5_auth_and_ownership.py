"""Automated test suite for Phase 6.5 — Supabase Auth & User-Owned Conversations."""

import uuid
from decimal import Decimal
from unittest.mock import patch

import pytest
from flask import Flask
from flask.testing import FlaskClient
from flask_login import login_user

from app.common.decorators import admin_required
from app.extensions import db
from app.models.car import Car
from app.models.conversation import ConversationSession
from app.models.user import UserProfile
from app.services.auth_service import AuthService, VerifiedIdentity
from app.services.conversation_context_service import (
    ConversationContextError,
)
from app.services.customer_web_service import CustomerWebService


def _csrf_headers(client: FlaskClient) -> dict[str, str]:
    with client.session_transaction() as sess:
        token = str(sess.get("_browser_csrf_token") or "test-browser-csrf")
        sess["_browser_csrf_token"] = token
    return {"X-CSRF-Token": token}


@pytest.fixture()
def sample_user_a(db_session) -> UserProfile:
    user = UserProfile(
        id=uuid.UUID("11111111-1111-4111-a111-111111111111"),
        email="usera@example.com",
        display_name="User A",
        role="customer",
        active=True,
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture()
def sample_user_b(db_session) -> UserProfile:
    user = UserProfile(
        id=uuid.UUID("22222222-2222-4222-a222-222222222222"),
        email="userb@example.com",
        display_name="User B",
        role="customer",
        active=True,
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture()
def sample_admin(db_session) -> UserProfile:
    user = UserProfile(
        id=uuid.UUID("33333333-3333-4333-a333-333333333333"),
        email="admin@example.com",
        display_name="Admin User",
        role="admin",
        active=True,
    )
    db_session.add(user)
    db_session.commit()
    return user


class TestAuthAccessControl:
    """A. Authentication access control tests."""

    def test_unauthenticated_user_cannot_access_chat(self, unauthed_client: FlaskClient):
        res = unauthed_client.get("/chat")
        assert res.status_code == 302
        assert "/auth/login" in res.location

    def test_unauthenticated_user_cannot_post_messages(self, unauthed_client: FlaskClient):
        res = unauthed_client.post("/api/chat/messages", json={"message": "hello"})
        assert res.status_code == 302
        assert "/auth/login" in res.location

    def test_login_page_renders_google_button(self, unauthed_client: FlaskClient):
        res = unauthed_client.get("/auth/login")
        assert res.status_code == 200
        assert "المتابعة باستخدام Google" in res.get_data(as_text=True)

    def test_google_login_redirects_to_supabase_authorize(self, unauthed_client: FlaskClient):
        res = unauthed_client.get("/auth/google")
        assert res.status_code == 302
        assert "supabase.co/auth/v1/authorize" in res.location
        assert "provider=google" in res.location

    def test_successful_oauth_callback_authenticates_user(
        self, app: Flask, unauthed_client: FlaskClient, db_session
    ):
        identity = VerifiedIdentity(
            id=uuid.UUID("44444444-4444-4444-a444-444444444444"),
            email="newuser@example.com",
            display_name="New Google User",
            avatar_url="https://lh3.googleusercontent.com/avatar.jpg",
        )
        with patch.object(AuthService, "exchange_code_or_token", return_value=identity):
            res = unauthed_client.get("/auth/callback?code=mock-oauth-code")
            assert res.status_code == 302
            assert "/chat" in res.location

            user = db_session.get(UserProfile, identity.id)
            assert user is not None
            assert user.email == "newuser@example.com"
            assert user.display_name == "New Google User"
            assert user.role == "customer"

    def test_relogin_restores_latest_owned_conversation_without_creating_blank(
        self, app: Flask, unauthed_client: FlaskClient, db_session, sample_user_a
    ):
        service = CustomerWebService(db_session)
        context = service.ensure_conversation(None, user_id=sample_user_a.id)
        db_session.commit()

        identity = VerifiedIdentity(
            id=sample_user_a.id,
            email=sample_user_a.email,
            display_name=sample_user_a.display_name,
            avatar_url=None,
        )
        with patch.object(AuthService, "exchange_code_or_token", return_value=identity):
            res = unauthed_client.get("/auth/callback?code=mock-relogin-code")

        assert res.status_code == 302
        assert "/chat" in res.location

        with unauthed_client.session_transaction() as sess:
            assert sess["autodrive_conversation_id"] == str(context.session_id)

        reopened = unauthed_client.get("/chat")
        assert reopened.status_code == 200
        sessions = db_session.query(ConversationSession).all()
        assert len(sessions) == 1
        assert sessions[0].id == context.session_id

    def test_repeated_login_does_not_duplicate_user(
        self, app: Flask, unauthed_client: FlaskClient, sample_user_a
    ):
        identity = VerifiedIdentity(
            id=sample_user_a.id,
            email=sample_user_a.email,
            display_name="User A Updated",
            avatar_url=None,
        )
        with patch.object(AuthService, "exchange_code_or_token", return_value=identity):
            res = unauthed_client.get("/auth/callback?code=mock-code-2")
            assert res.status_code == 302

            user_count = db.session.query(UserProfile).filter_by(email=sample_user_a.email).count()
            assert user_count == 1
            updated = db.session.get(UserProfile, sample_user_a.id)
            assert updated.display_name == "User A Updated"

    def test_inactive_user_denied_access(self, unauthed_client: FlaskClient, db_session):
        inactive_user = UserProfile(
            id=uuid.UUID("55555555-5555-4555-a555-555555555555"),
            email="inactive@example.com",
            display_name="Disabled User",
            role="customer",
            active=False,
        )
        db_session.add(inactive_user)
        db_session.commit()

        identity = VerifiedIdentity(
            id=inactive_user.id,
            email=inactive_user.email,
            display_name="Disabled User",
            avatar_url=None,
        )
        with patch.object(AuthService, "exchange_code_or_token", return_value=identity):
            res = unauthed_client.get("/auth/callback?code=mock-code-inactive")
            assert res.status_code == 302
            assert "/auth/login" in res.location

    def test_oauth_callback_error_handling(self, unauthed_client: FlaskClient):
        res = unauthed_client.get(
            "/auth/callback?error=access_denied&error_description=User+cancelled"
        )
        assert res.status_code == 302
        assert "/auth/login" in res.location

    def test_logout_clears_auth_and_session(self, app: Flask, client: FlaskClient, sample_user_a):
        with client:
            with client.session_transaction() as sess:
                sess["autodrive_conversation_id"] = str(uuid.uuid4())

            # Login user
            client.get("/auth/login")  # initialize context
            with app.test_request_context():
                login_user(sample_user_a)

            res = client.post("/auth/logout", headers=_csrf_headers(client))
            assert res.status_code == 302
            assert "/auth/login" in res.location

    def test_logout_clears_remember_cookie_and_cannot_auto_restore_user(
        self,
        app: Flask,
        unauthed_client: FlaskClient,
        sample_user_a,
    ):
        remember_cookie = app.config.get("REMEMBER_COOKIE_NAME", "remember_token")
        with unauthed_client.session_transaction() as sess:
            sess["_user_id"] = str(sample_user_a.id)
            sess["_fresh"] = True
            sess["_remember"] = "set"

        assert unauthed_client.get("/chat").status_code == 200
        assert unauthed_client.get_cookie(remember_cookie) is not None

        response = unauthed_client.post(
            "/auth/logout",
            headers=_csrf_headers(unauthed_client),
        )

        assert response.status_code == 302
        assert unauthed_client.get_cookie(remember_cookie) is None
        protected = unauthed_client.get("/chat")
        assert protected.status_code == 302
        assert "/auth/login" in protected.location


class TestUserOwnershipAndIsolation:
    """B, C, D & Security Negative Tests."""

    def test_user_session_ownership_and_cross_user_isolation(
        self, db_session, sample_user_a, sample_user_b
    ):
        service = CustomerWebService(db_session)

        # User A creates a session
        context_a = service.ensure_conversation(None, user_id=sample_user_a.id)
        session_a_id = context_a.session_id
        db_session.commit()

        # User B creates a session
        context_b = service.ensure_conversation(None, user_id=sample_user_b.id)
        session_b_id = context_b.session_id
        db_session.commit()

        # Verify initial ownership
        sess_a = db_session.get(ConversationSession, session_a_id)
        sess_b = db_session.get(ConversationSession, session_b_id)
        assert sess_a.user_id == sample_user_a.id
        assert sess_b.user_id == sample_user_b.id

        # User A loads own session -> Succeeds
        loaded_a = service.context.load(session_a_id, user_id=sample_user_a.id)
        assert loaded_a.session_id == session_a_id

        # User B attempts to load User A's session -> Forbidden error
        with pytest.raises(ConversationContextError, match="forbidden"):
            service.context.load(session_a_id, user_id=sample_user_b.id)

        # User B attempts load_or_create on User A's session ID -> Creates new owned session for B
        fallback_b = service.ensure_conversation(session_a_id, user_id=sample_user_b.id)
        assert fallback_b.session_id != session_a_id
        assert fallback_b.session_id != session_b_id
        sess_fallback = db_session.get(ConversationSession, fallback_b.session_id)
        assert sess_fallback.user_id == sample_user_b.id

    def test_private_chat_history_isolation(self, db_session, sample_user_a, sample_user_b):
        service = CustomerWebService(db_session)

        # Create two sessions for User A
        ctx_a1 = service.ensure_conversation(None, user_id=sample_user_a.id)
        service.context.persist_turn(
            ctx_a1.session_id, "عايز بي ام دبليو", "أهلاً بيك، متوفر BMW X6"
        )

        ctx_a2 = service.ensure_conversation(None, user_id=sample_user_a.id)
        service.context.persist_turn(
            ctx_a2.session_id, "عايز تويوتا كرولا", "متوفر تويوتا كرولا 2023"
        )

        # Create one session for User B
        ctx_b1 = service.ensure_conversation(None, user_id=sample_user_b.id)
        service.context.persist_turn(ctx_b1.session_id, "عايز نيسان قشقاي", "متوفر نيسان قشقاي")

        # User A requests history -> Returns only A's conversations
        history_a = service.user_conversations(sample_user_a.id)
        history_a_ids = {item["id"] for item in history_a}
        assert len(history_a) == 2
        assert str(ctx_a1.session_id) in history_a_ids
        assert str(ctx_a2.session_id) in history_a_ids
        assert str(ctx_b1.session_id) not in history_a_ids

        # User B requests history -> Returns only B's conversations
        history_b = service.user_conversations(sample_user_b.id)
        history_b_ids = {item["id"] for item in history_b}
        assert len(history_b) == 1
        assert str(ctx_b1.session_id) in history_b_ids
        assert str(ctx_a1.session_id) not in history_b_ids

    def test_security_negative_test_cross_user_api_attempt(
        self, app: Flask, client: FlaskClient, db_session, sample_user_a, sample_user_b
    ):
        """Requirement 34: Security Negative Test.

        User B must not receive User A's messages, state, selected car, or recommendations
        when manually requesting User A's conversation. The API must return controlled 404.
        """
        service = CustomerWebService(db_session)
        ctx_a = service.ensure_conversation(None, user_id=sample_user_a.id)
        service.context.persist_turn(ctx_a.session_id, "سرية خاصة بالمستخدم A", "رد سري للمستخدم A")
        db_session.commit()
        session_a_id = str(ctx_a.session_id)

        # Login as User B
        with app.test_request_context():
            login_user(sample_user_b)

        # User B attempts to switch to User A's session_id
        res = client.post(
            f"/api/chat/switch_session/{session_a_id}",
            headers=_csrf_headers(client),
        )
        assert res.status_code == 404
        payload = res.get_json()
        assert payload["ok"] is False
        assert "لم يتم العثور" in payload["message"]

    def test_recommendation_snapshot_and_ordinal_isolation(
        self, db_session, sample_user_a, sample_user_b
    ):
        service = CustomerWebService(db_session)
        car1 = Car(
            id=101,
            brand="BMW",
            model="X5",
            year=2023,
            price_egp=Decimal(4000000),
            condition="used",
            active=True,
            source="test",
            source_id="rec-1",
        )
        car2 = Car(
            id=102,
            brand="Toyota",
            model="Corolla",
            year=2024,
            price_egp=Decimal(1500000),
            condition="new",
            active=True,
            source="test",
            source_id="rec-2",
        )
        db_session.add_all([car1, car2])
        db_session.commit()

        # User A session with snapshot containing car1 at position 1
        ctx_a = service.ensure_conversation(None, user_id=sample_user_a.id)
        service.context.recommendations.create_visible_snapshot(
            session_id=ctx_a.session_id,
            cars=[car1],
            criteria={"brand": "BMW"},
        )
        db_session.commit()

        # User B session with snapshot containing car2 at position 1
        ctx_b = service.ensure_conversation(None, user_id=sample_user_b.id)
        service.context.recommendations.create_visible_snapshot(
            session_id=ctx_b.session_id,
            cars=[car2],
            criteria={"brand": "Toyota"},
        )
        db_session.commit()

        # Active snapshot for User A must return BMW X5
        loaded_a = service.chat_state(ctx_a.session_id, user_id=sample_user_a.id)
        assert len(loaded_a.visible_recommendations) == 1
        assert loaded_a.visible_recommendations[0]["car"]["brand"] == "BMW"

        # Active snapshot for User B must return Toyota Corolla
        loaded_b = service.chat_state(ctx_b.session_id, user_id=sample_user_b.id)
        assert len(loaded_b.visible_recommendations) == 1
        assert loaded_b.visible_recommendations[0]["car"]["brand"] == "Toyota"


class TestAdminAuthorization:
    """F. Admin authorization tests."""

    def test_customer_role_denied_admin_route(self, app: Flask, sample_user_a):
        with app.test_request_context():
            login_user(sample_user_a)

            @admin_required
            def dummy_admin_view():
                return "admin panel"

            with pytest.raises(Exception) as exc_info:
                dummy_admin_view()
            # Aborts with 403 HTTP Exception for HTML request
            assert "403" in str(exc_info.value)

    def test_admin_role_permitted_admin_route(self, app: Flask, sample_admin):
        with app.test_request_context():
            login_user(sample_admin)

            @admin_required
            def dummy_admin_view():
                return "admin panel"

            result = dummy_admin_view()
            assert result == "admin panel"

    def test_cli_set_user_role(self, app: Flask, db_session, sample_user_a):
        runner = app.test_cli_runner()
        result = runner.invoke(args=["set-user-role", sample_user_a.email, "admin"])
        assert result.exit_code == 0
        assert "Successfully set role 'admin'" in result.output

        db_session.refresh(sample_user_a)
        assert sample_user_a.role == "admin"
