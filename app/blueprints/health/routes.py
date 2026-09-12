"""Application and database health endpoints."""

from flask import current_app
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.blueprints.health import bp
from app.extensions import db


@bp.get("/health")
def health() -> tuple[dict[str, str], int]:
    """Return process-level health without touching external services."""
    return {"status": "ok", "service": "autodrive-egypt"}, 200


@bp.get("/health/db")
def database_health() -> tuple[dict[str, str], int]:
    """Verify that SQLAlchemy can execute a simple database query."""
    try:
        db.session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        # Keep client and production logs free of raw database exception details.
        current_app.logger.warning("Database health check failed")
        return {"status": "error", "database": "unreachable"}, 503

    return {"status": "ok", "database": "reachable"}, 200
