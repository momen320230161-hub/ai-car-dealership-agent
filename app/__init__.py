from flask import Flask, jsonify

from app.common.exceptions import ApplicationError
from app.common.logging import configure_logging
from app.config import ProductionConfig, get_config_class
from app.extensions import init_extensions


def create_app(config_name=None):
    app = Flask(__name__)
    config_class = get_config_class(config_name)
    app.config.from_object(config_class)

    if not app.config["TESTING"] and not app.config.get("SQLALCHEMY_DATABASE_URI"):
        raise RuntimeError("DATABASE_URL must be set before starting the application")
    if app.config["EMBEDDING_DIMENSIONS"] != 768:
        raise RuntimeError(
            "EMBEDDING_DIMENSIONS must be 768; changing it requires a schema migration and re-embedding"
        )
    if not 0 <= app.config["RAG_CHUNK_OVERLAP"] < app.config["RAG_CHUNK_SIZE"]:
        raise RuntimeError("RAG_CHUNK_OVERLAP must be non-negative and smaller than RAG_CHUNK_SIZE")
    if not 1 <= app.config["RAG_DEFAULT_TOP_K"] <= app.config["RAG_MAX_TOP_K"]:
        raise RuntimeError("RAG_DEFAULT_TOP_K must be between 1 and RAG_MAX_TOP_K")

    if config_class is ProductionConfig and app.config.get("SECRET_KEY") in (
        None,
        "",
        "dev-secret-key-change-me",
    ):
        raise RuntimeError("SECRET_KEY must be set to a strong value in production")

    init_extensions(app)
    from app import models  # noqa: F401 -- registers SQLAlchemy metadata
    from app.cli import register_commands

    register_commands(app)
    configure_logging(app)
    _register_error_handlers(app)
    _register_health_route(app)

    return app


def _register_health_route(app):
    @app.get("/health")
    def health():
        return jsonify({"status": "ok"})


def _register_error_handlers(app):
    @app.errorhandler(ApplicationError)
    def handle_application_error(error):
        return (
            jsonify(
                {
                    "error": error.message,
                    "type": error.__class__.__name__,
                }
            ),
            error.status_code,
        )

    @app.errorhandler(404)
    def handle_not_found(_error):
        return jsonify({"error": "Not found"}), 404

    @app.errorhandler(500)
    def handle_internal_error(_error):
        return jsonify({"error": "Internal server error"}), 500
