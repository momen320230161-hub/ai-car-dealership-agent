"""Health-check blueprint."""

from flask import Blueprint

bp = Blueprint("health", __name__)

from app.blueprints.health import routes  # noqa: E402, F401
