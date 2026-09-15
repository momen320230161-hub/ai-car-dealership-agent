import os
import uuid
from collections.abc import Generator

import pytest
from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy import event
from sqlalchemy.engine import Engine

from app import create_app
from app.extensions import db
from app.models.user import UserProfile


@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """Enable foreign-key constraints for SQLite test connections."""
    if type(dbapi_connection).__module__.startswith("sqlite3"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


@pytest.fixture()
def app() -> Flask:
    """Create a Flask application configured for isolated SQLite unit tests."""
    return create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret-key",
            "SQLALCHEMY_DATABASE_URI": "sqlite+pysqlite:///:memory:",
            "SQLALCHEMY_ENGINE_OPTIONS": {},
        }
    )
@pytest.fixture()
def unauthed_client(app: Flask) -> FlaskClient:
    """Unauthenticated test client for testing login redirects."""
    return app.test_client()


@pytest.fixture()
def client(app: Flask, db_session) -> FlaskClient:
    """Test client for HTTP endpoint verification with default authenticated user session."""
    user = db_session.get(UserProfile, uuid.UUID("00000000-0000-4000-a000-000000000000"))
    if user is None:
        user = UserProfile(
            id=uuid.UUID("00000000-0000-4000-a000-000000000000"),
            email="test_default@example.com",
            display_name="Test Default User",
            role="customer",
            active=True,
        )
        db_session.add(user)
        db_session.commit()

    test_client = app.test_client()
    with test_client.session_transaction() as sess:
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True
    return test_client


@pytest.fixture()
def db_session(app: Flask) -> Generator:
    """Provide an isolated SQLite session for model-level unit tests."""
    with app.app_context():
        db.create_all()
        yield db.session
        db.session.rollback()
        db.drop_all()


@pytest.fixture()
def pg_app() -> Generator[Flask, None, None]:
    """Provide a Flask app connected to the explicit PostgreSQL test database."""
    pg_url = os.getenv("TEST_DATABASE_URL")
    if not pg_url:
        pytest.skip("TEST_DATABASE_URL is required for PostgreSQL integration tests")

    flask_app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret-key",
            "SQLALCHEMY_DATABASE_URI": pg_url,
            "SQLALCHEMY_ENGINE_OPTIONS": {"pool_pre_ping": True},
        }
    )
    yield flask_app
