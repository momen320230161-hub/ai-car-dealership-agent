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
