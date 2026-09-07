from flask import Flask, jsonify

from app.common.exceptions import ApplicationError
from app.common.logging import configure_logging
from app.config import ProductionConfig, get_config_class
from app.extensions import init_extensions


def create_app(config_name=None):
    app = Flask(__name__)
    config_class = get_config_class(config_name)
    app.config.from_object(config_class)

    if config_class is ProductionConfig and app.config.get("SECRET_KEY") in (
        None,
        "",
        "dev-secret-key-change-me",
    ):
        raise RuntimeError("SECRET_KEY must be set to a strong value in production")

    init_extensions(app)
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
