"""Small browser-security helpers shared by customer-facing Flask routes."""

from __future__ import annotations

import hmac
import re
import secrets
import uuid

from flask import Flask, abort, g, request, session

_BROWSER_CSRF_SESSION_KEY = "_browser_csrf_token"
_SAFE_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def browser_csrf_token() -> str:
    """Return a stable per-browser-session CSRF token, creating it when absent."""
    token = session.get(_BROWSER_CSRF_SESSION_KEY)
    if not isinstance(token, str) or not token:
        token = secrets.token_urlsafe(32)
        session[_BROWSER_CSRF_SESSION_KEY] = token
    return token


def require_browser_csrf() -> None:
    """Reject an unsafe browser request unless its CSRF token matches the session."""
    expected = str(session.get(_BROWSER_CSRF_SESSION_KEY) or "")
    supplied = str(
        request.headers.get("X-CSRF-Token")
        or request.form.get("csrf_token")
        or ""
    )
    if not expected or not supplied or not hmac.compare_digest(expected, supplied):
        abort(400)


def init_security(app: Flask) -> None:
    """Install request correlation, browser CSRF context, and safe response headers."""

    @app.before_request
    def assign_request_id() -> None:
        supplied = request.headers.get("X-Request-ID", "").strip()
        g.request_id = supplied if _SAFE_REQUEST_ID_RE.fullmatch(supplied) else uuid.uuid4().hex

    @app.context_processor
    def inject_browser_security_context() -> dict[str, str]:
        return {"browser_csrf_token": browser_csrf_token()}

    @app.after_request
    def add_security_headers(response):
        response.headers.setdefault("X-Request-ID", str(getattr(g, "request_id", uuid.uuid4().hex)))
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=()",
        )
        return response
