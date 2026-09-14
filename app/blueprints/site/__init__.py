"""Customer-facing website blueprint."""

from flask import Blueprint

bp = Blueprint("site", __name__)

from app.blueprints.site import routes  # noqa: E402, F401
