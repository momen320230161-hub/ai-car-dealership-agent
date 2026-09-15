"""HTTP adapter for the customer-facing Sales Orchestrator with User Ownership."""

from __future__ import annotations

import uuid
from typing import Any

from flask import current_app, jsonify, render_template, request
from flask import session as browser_session
from flask_login import current_user, login_required
from sqlalchemy.exc import SQLAlchemyError

from app.agent.factory import build_sales_orchestrator
from app.agent.llm import AgentLLMError
from app.blueprints.chat import bp
from app.extensions import db
from app.rag.embeddings import EmbeddingError
from app.services.conversation_context_service import ConversationContextError
from app.services.customer_web_service import CustomerChatState, CustomerWebService

_BROWSER_SESSION_KEY = "autodrive_conversation_id"
_CRITICAL_AGENT_ERRORS = {"orchestrator_failed", "context_failed", "persistence_failed"}


def _service() -> CustomerWebService:
    return CustomerWebService(
        db.session,
        recent_message_limit=current_app.config["AGENT_RECENT_MESSAGE_LIMIT"],
    )


def _user_id() -> uuid.UUID | None:
    return current_user.id if current_user.is_authenticated else None


def _ensure_browser_conversation(service: CustomerWebService):
    browser_session.permanent = True
    stored_session_id = browser_session.get(_BROWSER_SESSION_KEY)
    user_id = _user_id()
    try:
        context = service.ensure_conversation(stored_session_id, user_id=user_id)
    except (ConversationContextError, ValueError):
        browser_session.pop(_BROWSER_SESSION_KEY, None)
        context = service.ensure_conversation(None, user_id=user_id)
    browser_session[_BROWSER_SESSION_KEY] = str(context.session_id)
    return context


def _state_payload(state: CustomerChatState) -> dict[str, Any]:
    selected_car = state.selected_car
    if selected_car is not None:
        selected_car = {
            "id": selected_car.get("id"),
            "brand": selected_car.get("brand"),
            "model": selected_car.get("model"),
            "year": selected_car.get("year"),
        }
    return {
        "session_id": str(state.session_id),
        "selected_car": selected_car,
        "pending_action_type": state.pending_action_type,
        "visible_recommendations": state.visible_recommendations,
    }


def _safe_service_error(status_code: int = 503):
    return (
        jsonify(
            {
                "ok": False,
                "message": "حصلت مشكلة مؤقتة. جرّب تبعت رسالتك تاني بعد لحظات.",
            }
        ),
        status_code,
    )


@bp.get("/chat")
@login_required
def chat_page():
    service = _service()
    try:
        context = _ensure_browser_conversation(service)
        state = service.chat_state(context.session_id, user_id=_user_id())
        user_history = service.user_conversations(current_user.id)
    except (ConversationContextError, SQLAlchemyError, ValueError):
        db.session.rollback()
        current_app.logger.exception("Customer chat page could not load")
        return render_template("errors/500.html"), 503
    return render_template("chat/index.html", chat_state=state, user_history=user_history)


@bp.post("/api/chat/messages")
@login_required
def send_message():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or not isinstance(payload.get("message"), str):
        return jsonify({"ok": False, "message": "الرسالة غير صالحة."}), 400

    message = payload["message"]
    normalized = message.strip()
    if not normalized:
        return jsonify({"ok": False, "message": "اكتب رسالة قبل الإرسال."}), 400
    if len(message) > int(current_app.config["AGENT_MAX_MESSAGE_LENGTH"]):
        return jsonify({"ok": False, "message": "الرسالة أطول من الحد المسموح."}), 400

    service = _service()
    try:
        context = _ensure_browser_conversation(service)
        orchestrator = build_sales_orchestrator(db.session, current_app.config)
        result = orchestrator.handle_message(context.session_id, message)
        state = service.chat_state(result.session_id or context.session_id, user_id=_user_id())
    except (AgentLLMError, EmbeddingError, ConversationContextError, SQLAlchemyError, ValueError):
        db.session.rollback()
        current_app.logger.exception("Customer chat request failed before a safe agent response")
        return _safe_service_error()

    errors = list(result.errors)
    status_code = 503 if _CRITICAL_AGENT_ERRORS.intersection(errors) else 200
    response_payload = {
        "ok": status_code == 200,
        "response": result.response,
        "intent": result.intent,
        "route": result.route,
        "errors": errors,
        "recommendation_snapshot_id": result.recommendation_snapshot_id,
        "visible_recommendations": result.visible_recommendations,
        "state": _state_payload(state),
    }
    return jsonify(response_payload), status_code


@bp.post("/api/chat/session")
@login_required
def new_session():
    service = _service()
    browser_session.pop(_BROWSER_SESSION_KEY, None)
    try:
        context = _ensure_browser_conversation(service)
        state = service.chat_state(context.session_id, user_id=_user_id())
    except (ConversationContextError, SQLAlchemyError, ValueError):
        db.session.rollback()
        current_app.logger.exception("Customer chat session reset failed")
        return _safe_service_error()
    return jsonify({"ok": True, "state": _state_payload(state)})


@bp.get("/api/chat/history")
@login_required
def get_history():
    service = _service()
    history = service.user_conversations(current_user.id)
    return jsonify({"ok": True, "conversations": history})


@bp.post("/api/chat/switch_session/<session_id_str>")
@login_required
def switch_session(session_id_str: str):
    try:
        target_uuid = uuid.UUID(session_id_str)
    except ValueError:
        return jsonify({"ok": False, "message": "معرف المحادثة غير صحيح."}), 400

    service = _service()
    try:
        context = service.context.load(target_uuid, user_id=current_user.id)
        browser_session[_BROWSER_SESSION_KEY] = str(context.session_id)
        state = service.chat_state(context.session_id, user_id=current_user.id)
    except ConversationContextError:
        return jsonify(
            {"ok": False, "message": "لم يتم العثور على المحادثة المطلوب الانتقال إليها."}
        ), 404
    except SQLAlchemyError:
        db.session.rollback()
        return _safe_service_error()

    return jsonify({"ok": True, "state": _state_payload(state), "messages": state.messages})
