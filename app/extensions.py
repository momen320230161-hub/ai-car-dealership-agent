"""Central Flask extension registry.

Declare extension objects here and bind them in init_extensions().
Later phases can add SQLAlchemy, CORS, and similar libraries without
changing the application factory's overall shape:

    from flask_sqlalchemy import SQLAlchemy

    db = SQLAlchemy()

    def init_extensions(app):
        db.init_app(app)
"""


def init_extensions(app):
    """Bind registered extensions to the application instance."""
    # No extensions in Phase 1. Call site stays in create_app().
    return app
