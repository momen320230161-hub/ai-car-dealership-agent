"""Application, database, and deployment-readiness health endpoints."""

from flask import current_app
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.blueprints.health import bp
from app.extensions import db


def _database_reachable() -> bool:
    try:
        db.session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        db.session.rollback()
        return False
    return True


def _configuration_checks() -> list[str]:
    missing: list[str] = []
    llm_provider = str(current_app.config.get("AGENT_LLM_PROVIDER") or "").lower()
    embedding_provider = str(current_app.config.get("EMBEDDING_PROVIDER") or "").lower()
    if llm_provider == "gemini" and not current_app.config.get("GEMINI_API_KEY"):
        missing.append("agent_llm")
    if embedding_provider == "gemini" and not current_app.config.get("GEMINI_API_KEY"):
        missing.append("embeddings")
    if not current_app.config.get("SUPABASE_URL"):
        missing.append("authentication")
    if not (
        current_app.config.get("SUPABASE_PUBLISHABLE_KEY")
        or current_app.config.get("SUPABASE_ANON_KEY")
    ):
        missing.append("authentication")
    return sorted(set(missing))


@bp.get("/health")
def health() -> tuple[dict[str, str], int]:
    """Return process-level health without touching external services."""
    return {"status": "ok", "service": "autodrive-egypt"}, 200


@bp.get("/health/db")
def database_health() -> tuple[dict[str, str], int]:
    """Verify that SQLAlchemy can execute a simple database query."""
    if not _database_reachable():
        current_app.logger.warning("Database health check failed")
        return {"status": "error", "database": "unreachable"}, 503

    return {"status": "ok", "database": "reachable"}, 200


@bp.get("/health/ready")
def readiness() -> tuple[dict[str, object], int]:
    """Verify DB connectivity and critical provider configuration for serving traffic."""
    database_ok = _database_reachable()
    missing = _configuration_checks()
    if not database_ok or missing:
        if not database_ok:
            current_app.logger.warning("Readiness check failed: database unreachable")
        if missing:
            current_app.logger.warning("Readiness check failed: required providers not configured")
        return {
            "status": "not_ready",
            "database": "reachable" if database_ok else "unreachable",
            "missing_checks": missing,
        }, 503

    return {
        "status": "ready",
        "database": "reachable",
        "missing_checks": [],
    }, 200
