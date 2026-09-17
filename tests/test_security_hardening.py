"""Phase 7 browser security and deployment-readiness regressions."""

from __future__ import annotations

from pathlib import Path


def _csrf_headers(client) -> dict[str, str]:
    with client.session_transaction() as sess:
        token = str(sess.get("_browser_csrf_token") or "test-browser-csrf")
        sess["_browser_csrf_token"] = token
    return {"X-CSRF-Token": token}


def test_security_headers_and_request_id_are_present(client) -> None:
    response = client.get("/health", headers={"X-Request-ID": "test-request-123"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "test-request-123"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert response.headers["Permissions-Policy"] == "camera=(), microphone=(), geolocation=()"
    assert "autodrive_csrf=" in response.headers.get("Set-Cookie", "")


def test_invalid_request_id_is_not_reflected(client) -> None:
    response = client.get("/health", headers={"X-Request-ID": "bad header with spaces"})

    assert response.status_code == 200
    generated = response.headers["X-Request-ID"]
    assert generated != "bad header with spaces"
    assert len(generated) == 32


def test_chat_mutations_require_matching_csrf(app, client) -> None:
    app.config.update(
        AGENT_LLM_PROVIDER="deterministic",
        EMBEDDING_PROVIDER="deterministic",
        EMBEDDING_MODEL="deterministic-test-v1",
    )
    assert client.get("/chat").status_code == 200

    missing = client.post("/api/chat/messages", json={"message": "   "})
    wrong = client.post(
        "/api/chat/messages",
        json={"message": "   "},
        headers={"X-CSRF-Token": "wrong-token"},
    )
    valid = client.post(
        "/api/chat/messages",
        json={"message": "   "},
        headers=_csrf_headers(client),
    )

    assert missing.status_code == 400
    assert wrong.status_code == 400
    assert valid.status_code == 400
    assert valid.is_json
    assert valid.get_json()["ok"] is False
    assert "اكتب رسالة" in valid.get_json()["message"]


def test_logout_is_post_only_and_csrf_protected(client) -> None:
    assert client.get("/health").status_code == 200
    assert client.get("/auth/logout").status_code == 405
    assert client.post("/auth/logout").status_code == 400

    response = client.post("/auth/logout", headers=_csrf_headers(client))

    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


def test_readiness_checks_database_and_runtime_configuration(app, client) -> None:
    app.config.update(
        AGENT_LLM_PROVIDER="deterministic",
        EMBEDDING_PROVIDER="deterministic",
        SUPABASE_URL="https://test-project.supabase.co",
        SUPABASE_PUBLISHABLE_KEY="test-key",
    )
    ready = client.get("/health/ready")
    assert ready.status_code == 200
    assert ready.get_json() == {
        "status": "ready",
        "database": "reachable",
        "missing_checks": [],
    }

    app.config.update(
        AGENT_LLM_PROVIDER="gemini",
        EMBEDDING_PROVIDER="gemini",
        GEMINI_API_KEY=None,
    )
    not_ready = client.get("/health/ready")
    payload = not_ready.get_json()
    assert not_ready.status_code == 503
    assert payload["status"] == "not_ready"
    assert set(payload["missing_checks"]) == {"agent_llm", "embeddings"}
    assert "test-key" not in not_ready.get_data(as_text=True)


def test_dynamic_selected_car_rendering_uses_text_nodes_not_inner_html() -> None:
    source = Path("app/static/js/chat.js").read_text(encoding="utf-8")

    assert "selectedContainer.replaceChildren()" in source
    assert "selectedContainer.innerHTML" not in source
    assert "title.textContent = [selected.brand, selected.model]" in source
