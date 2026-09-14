"""Phase 0 health endpoint and configuration tests."""

from unittest.mock import patch

import pytest
from sqlalchemy.exc import OperationalError

from app import create_app
from app.config import normalize_database_url


def test_health(client):
    """Test process-level health check endpoint."""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.get_json() == {"service": "autodrive-egypt", "status": "ok"}


def test_database_health(client):
    """Test database health check when database is reachable."""
    response = client.get("/health/db")

    assert response.status_code == 200
    assert response.get_json() == {"database": "reachable", "status": "ok"}


def test_database_health_failure(client):
    """Test database health check returns 503 when query fails."""
    with patch("app.blueprints.health.routes.db.session.execute") as mock_execute:
        mock_execute.side_effect = OperationalError(
            "connection refused", params={}, orig=Exception("DB Down")
        )
        response = client.get("/health/db")

        assert response.status_code == 503
        assert response.get_json() == {"database": "unreachable", "status": "error"}


def test_create_app_missing_config():
    """Test application factory rejects missing required configuration."""
    with pytest.raises(RuntimeError, match="Missing required environment configuration"):
        create_app(
            {
                "SECRET_KEY": None,
                "SQLALCHEMY_DATABASE_URI": None,
            }
        )


def test_normalize_database_url():
    """Test PostgreSQL database URL normalization to psycopg3 driver."""
    assert normalize_database_url(None) is None
    assert normalize_database_url("") is None
    assert normalize_database_url("   ") is None
    assert (
        normalize_database_url("postgres://user:pass@host:5432/db")
        == "postgresql+psycopg://user:pass@host:5432/db"
    )
    assert (
        normalize_database_url("postgresql://user:pass@host:5432/db")
        == "postgresql+psycopg://user:pass@host:5432/db"
    )
    assert (
        normalize_database_url("postgresql+psycopg://user:pass@host:5432/db")
        == "postgresql+psycopg://user:pass@host:5432/db"
    )
    assert normalize_database_url("sqlite+pysqlite:///:memory:") == "sqlite+pysqlite:///:memory:"
