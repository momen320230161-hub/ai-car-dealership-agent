"""HTTP endpoints for Supabase Google OAuth authentication and session management."""

from __future__ import annotations

from urllib.parse import urlparse

from flask import current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy.exc import SQLAlchemyError

from app.blueprints.auth import bp
from app.common.security import require_browser_csrf
from app.extensions import db
from app.services.auth_service import AuthError, AuthService, AuthUserInactiveError
from app.services.car_image_service import image_url_for_source_id
from app.services.customer_web_service import CustomerWebService

_CODE_VERIFIER_SESSION_KEY = "oauth_code_verifier"
_AUTH_NEXT_SESSION_KEY = "oauth_next"
_CONVERSATION_SESSION_KEY = "autodrive_conversation_id"
_AUTH_HERO_SOURCE_ID = "noortariq20-egypt-market:fe3b37c3f0960bdd9f223cb9"


def _auth_service() -> AuthService:
    return AuthService(
        db.session,
        supabase_url=current_app.config.get("SUPABASE_URL"),
        supabase_key=current_app.config.get("SUPABASE_PUBLISHABLE_KEY")
        or current_app.config.get("SUPABASE_ANON_KEY"),
    )


def _auth_is_configured() -> bool:
    return bool(
        current_app.config.get("SUPABASE_URL")
        and (
            current_app.config.get("SUPABASE_PUBLISHABLE_KEY")
            or current_app.config.get("SUPABASE_ANON_KEY")
        )
        and current_app.secret_key
    )


def _safe_local_path(value: str | None) -> str | None:
    """Return a local absolute path only; reject external/open redirects."""
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc or not value.startswith("/") or value.startswith("//"):
        return None
    return value


@bp.get("/auth/login")
def login_page():
    if current_user.is_authenticated:
        return redirect(url_for("chat.chat_page"))

    next_page = _safe_local_path(request.args.get("next"))
    if next_page:
        session[_AUTH_NEXT_SESSION_KEY] = next_page

    hero_car_image_url = image_url_for_source_id(
        _AUTH_HERO_SOURCE_ID,
        supabase_url=current_app.config.get("SUPABASE_URL"),
    )
    return render_template(
        "auth/login.html",
        auth_configured=_auth_is_configured(),
        hero_car_image_url=hero_car_image_url,
    )


@bp.get("/auth/google")
def google_login():
    if current_user.is_authenticated:
        return redirect(url_for("chat.chat_page"))

    if not _auth_is_configured():
        current_app.logger.error("Supabase Auth is not fully configured for Google login")
        flash(
            "إعدادات تسجيل الدخول غير مكتملة على السيرفر. راجع إعدادات Supabase Auth المحلية.",
            "error",
        )
        return redirect(url_for("auth.login_page"))

    next_page = _safe_local_path(request.args.get("next"))
    if next_page:
        session[_AUTH_NEXT_SESSION_KEY] = next_page

    service = _auth_service()
    verifier, challenge = service.generate_pkce_pair()
    session[_CODE_VERIFIER_SESSION_KEY] = verifier

    callback_url = url_for("auth.callback", _external=True)
    authorize_url = service.get_google_authorize_url(
        redirect_to=callback_url,
        code_challenge=challenge,
    )
    return redirect(authorize_url)


@bp.get("/auth/callback")
def callback():
    if current_user.is_authenticated:
        return redirect(url_for("chat.chat_page"))

    error = request.args.get("error")
    error_description = request.args.get("error_description")
    if error or error_description:
        current_app.logger.warning(
            "OAuth login cancelled or returned error: error=%r description=%r",
            error,
            error_description,
        )
        session.pop(_CODE_VERIFIER_SESSION_KEY, None)
        flash("تعذر إكمال تسجيل الدخول عبر Google. يمكنك المحاولة مرة أخرى.", "error")
        return redirect(url_for("auth.login_page"))

    code = request.args.get("code")
    access_token = request.args.get("access_token")
    if not code and not access_token:
        session.pop(_CODE_VERIFIER_SESSION_KEY, None)
        flash("كود التحقق غير متوفر. حاول تسجيل الدخول مجدداً.", "error")
        return redirect(url_for("auth.login_page"))

    code_verifier = session.pop(_CODE_VERIFIER_SESSION_KEY, None)
    next_page = _safe_local_path(session.pop(_AUTH_NEXT_SESSION_KEY, None))
    service = _auth_service()

    try:
        identity = service.exchange_code_or_token(
            code=code,
            access_token=access_token,
            code_verifier=code_verifier,
        )
        user = service.sync_user_profile(identity)
    except AuthUserInactiveError:
        current_app.logger.warning("Inactive user attempted login")
        flash("هذا الحساب معطل حالياً. تواصل مع الدعم الفني.", "error")
        return redirect(url_for("auth.login_page"))
    except (AuthError, ValueError):
        db.session.rollback()
        current_app.logger.exception("Auth callback exchange failed")
        flash("حدثت مشكلة أثناء إثبات الهوية. يرجى إعادة المحاولة.", "error")
        return redirect(url_for("auth.login_page"))
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Auth callback database synchronization failed")
        flash(
            "تم تسجيل الدخول مع Google لكن قاعدة البيانات المحلية غير محدثة. "
            "شغّل migrations ثم حاول مرة أخرى.",
            "error",
        )
        return redirect(url_for("auth.login_page"))

    session.clear()
    login_user(user, remember=True)

    # Restore the user's most recently updated owned conversation so signing out
    # and back in never manufactures an empty chat. A new conversation is still
    # created only when the user explicitly chooses "New Chat" or has no history.
    try:
        history_service = CustomerWebService(
            db.session,
            recent_message_limit=current_app.config["AGENT_RECENT_MESSAGE_LIMIT"],
        )
        recent = history_service.user_conversations(user.id, limit=1)
        if recent:
            session[_CONVERSATION_SESSION_KEY] = recent[0]["id"]
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Could not restore latest conversation after login")

    return redirect(next_page or url_for("chat.chat_page"))


@bp.post("/auth/logout")
@login_required
def logout():
    require_browser_csrf()
    # Clear application state first. ``logout_user`` must run last because it adds
    # Flask-Login's ``_remember=clear`` marker; clearing the session afterwards
    # would erase that marker and leave the remember cookie able to log the user
    # straight back in on the redirect.
    session.clear()
    logout_user()
    flash("تم تسجيل الخروج بنجاح.", "info")
    return redirect(url_for("auth.login_page"))
