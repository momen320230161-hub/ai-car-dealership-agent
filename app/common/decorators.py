"""Reusable authorization decorators."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any

from flask import abort, jsonify, redirect, request, url_for
from flask_login import current_user


def admin_required(f: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator enforcing that current_user is authenticated and has role == 'admin'."""

    @wraps(f)
    def decorated_function(*args: Any, **kwargs: Any) -> Any:
        if not current_user.is_authenticated:
            if request.is_json or request.path.startswith("/api/"):
                return jsonify(
                    {"ok": False, "message": "غير مصرح بالحصول على البيانات. يرجى تسجيل الدخول."}
                ), 401
            return redirect(url_for("auth.login_page", next=request.url))

        if getattr(current_user, "role", None) != "admin":
            if request.is_json or request.path.startswith("/api/"):
                return jsonify(
                    {"ok": False, "message": "ليس لديك صلاحية الوصول إلى هذه الصفحة."}
                ), 403
            abort(403)

        return f(*args, **kwargs)

    return decorated_function
