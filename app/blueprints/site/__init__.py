"""Customer-facing website blueprint."""

from flask import Blueprint

from app.common.security import register_security_hooks

bp = Blueprint("site", __name__)
register_security_hooks(bp)

from app.blueprints.admin import bp as admin_bp  # noqa: E402
from app.blueprints.site import routes  # noqa: E402, F401

bp.register_blueprint(admin_bp)
