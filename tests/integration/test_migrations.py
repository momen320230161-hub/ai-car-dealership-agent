"""PostgreSQL integration tests for the Alembic migration lifecycle."""

from flask_migrate import downgrade, upgrade
from sqlalchemy import text

from app.extensions import db

EXPECTED_TABLES = {
    "alembic_version",
    "cars",
    "chat_messages",
    "conversation_sessions",
    "knowledge_documents",
    "knowledge_chunks",
    "recommendation_snapshot_items",
    "recommendation_snapshots",
    "sales_leads",
    "test_drive_requests",
}


def _public_tables() -> set[str]:
    rows = db.session.execute(
        text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public'"
        )
    ).fetchall()
    return {row[0] for row in rows}


def test_postgres_migration_lifecycle(pg_app):
    """Upgrade, downgrade to base, then re-upgrade on real PostgreSQL."""
    with pg_app.app_context():
        upgrade()
        assert EXPECTED_TABLES.issubset(_public_tables())

        revision = db.session.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
        assert revision == "4f6a8c2d91b7"

        rls_rows = db.session.execute(
            text(
                """
                SELECT c.relname::text, c.relrowsecurity
                FROM pg_class AS c
                JOIN pg_namespace AS n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public'
                  AND c.relname::text = ANY(CAST(:tables AS text[]))
                """
            ),
            {"tables": list(EXPECTED_TABLES)},
        ).fetchall()
        assert {name for name, enabled in rls_rows if enabled} == EXPECTED_TABLES

        # Release the SQLAlchemy read transaction before Alembic requests
        # AccessExclusive locks for DROP TABLE during downgrade.
        db.session.rollback()
        downgrade(revision="base")

        remaining = _public_tables()
        assert "cars" not in remaining
        assert "conversation_sessions" not in remaining

        db.session.rollback()
        upgrade()
        assert EXPECTED_TABLES.issubset(_public_tables())
        db.session.rollback()
