"""Central Flask extension registry."""

from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()
migrate = Migrate()


def init_extensions(app):
    """Bind registered extensions to the application instance."""
    db.init_app(app)
    migrate.init_app(app, db)
    return app
