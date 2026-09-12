"""AutoDrive Egypt Flask application factory."""

from __future__ import annotations

from typing import Any

import click
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

    # Import models so that SQLAlchemy and Flask-Migrate discover metadata
    from app import models  # noqa: F401

    db.init_app(app)
    migrate.init_app(app, db, compare_type=True)

    from app.blueprints.health import bp as health_bp

    app.register_blueprint(health_bp)
    _register_cli(app)
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


def _register_cli(app: Flask) -> None:
    @app.cli.command("import-catalog")
    @click.option(
        "--path",
        default="data/egypt_cars_final_import_ready.csv",
        type=click.Path(path_type=str, dir_okay=False),
        show_default=True,
    )
    def import_catalog(path: str) -> None:
        """Import or synchronize the authoritative structured car catalog."""
        from app.services.catalog_import_service import CatalogImportService

        report = CatalogImportService(db.session).import_file(path)
        click.echo(f"file rows: {report.file_rows}")
        click.echo(f"inserted: {report.inserted}")
        click.echo(f"updated: {report.updated}")
        click.echo(f"unchanged: {report.unchanged}")
        click.echo(f"rejected: {report.rejected}")
        for error in report.errors:
            click.echo(f"error: {error}", err=True)
