"""Phase 0 health endpoint tests."""


def test_health(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.get_json() == {"service": "autodrive-egypt", "status": "ok"}


def test_database_health(client):
    response = client.get("/health/db")

    assert response.status_code == 200
    assert response.get_json() == {"database": "reachable", "status": "ok"}
