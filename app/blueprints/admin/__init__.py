"""Authenticated administration dashboard blueprint."""

from __future__ import annotations

import hmac
import secrets

from flask import Blueprint, abort, redirect, request, session, url_for
from flask_login import current_user

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.before_request
def require_admin_access():
    """Require an active authenticated admin and protect unsafe form submissions."""
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login_page"))
    if not getattr(current_user, "is_admin", False):
        abort(403)

    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        expected = str(session.get("_admin_csrf_token") or "")
        supplied = str(request.form.get("csrf_token") or request.headers.get("X-CSRF-Token") or "")
        if not expected or not supplied or not hmac.compare_digest(expected, supplied):
            abort(400)
    return None


@bp.context_processor
def inject_admin_csrf_token():
    token = session.get("_admin_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_admin_csrf_token"] = token
    return {"admin_csrf_token": token}


from app.blueprints.admin import routes  # noqa: E402, F401
