import pytest

from app import create_app
from app.config import TestingConfig
from app.extensions import db, migrate


def test_application_can_be_created(app):
    assert app is not None
    assert app.name == "app"
    assert "sqlalchemy" in app.extensions
    assert migrate is not None


def test_testing_configuration_loads(app):
    assert app.config["TESTING"] is True
    assert app.config["SECRET_KEY"] == "test-secret-key"
    assert app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite")


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_embedding_dimension_contract_is_enforced(monkeypatch):
    monkeypatch.setattr(TestingConfig, "EMBEDDING_DIMENSIONS", 1536)
    with pytest.raises(RuntimeError, match="must be 768"):
        create_app("testing")
