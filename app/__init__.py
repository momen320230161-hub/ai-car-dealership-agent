"""AutoDrive Egypt Flask application factory."""

from __future__ import annotations

from typing import Any

from flask import Flask

from app.config import Config
from app.extensions import db, migrate


def create_app(config_overrides: dict[str, Any] | None = None) -> Flask:
    """Create and configure the Flask application."""
    app = Flask(__name__)
    app.config.from_object(Config)

    if config_overrides:
        app.config.update(config_overrides)

    _validate_required_config(app)

    db.init_app(app)
    migrate.init_app(app, db, compare_type=True)

    from app.blueprints.health import bp as health_bp

    app.register_blueprint(health_bp)
    return app


def _validate_required_config(app: Flask) -> None:
    missing: list[str] = []

    if not app.config.get("SECRET_KEY"):
        missing.append("SECRET_KEY")
    if not app.config.get("SQLALCHEMY_DATABASE_URI"):
        missing.append("DATABASE_URL")

    if missing:
        joined = ", ".join(missing)
        raise RuntimeError(f"Missing required environment configuration: {joined}")
