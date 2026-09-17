"""Customer-facing website blueprint."""

from flask import Blueprint

bp = Blueprint("site", __name__)

from app.blueprints.site import routes  # noqa: E402, F401
from app.blueprints.admin import bp as admin_bp  # noqa: E402

bp.register_blueprint(admin_bp)
