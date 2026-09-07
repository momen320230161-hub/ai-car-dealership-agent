import pytest

from app import create_app


@pytest.fixture
def app():
    return create_app("testing")


@pytest.fixture
def client(app):
    return app.test_client()


def test_application_can_be_created(app):
    assert app is not None
    assert app.name == "app"


def test_testing_configuration_loads(app):
    assert app.config["TESTING"] is True
    assert app.config["SECRET_KEY"] == "test-secret-key"


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}
