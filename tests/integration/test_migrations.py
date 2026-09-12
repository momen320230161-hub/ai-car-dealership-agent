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
        assert revision == "cd73103ae9e0"

        rls_rows = db.session.execute(
            text(
                """
                SELECT c.relname, c.relrowsecurity
                FROM pg_class AS c
                JOIN pg_namespace AS n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public'
                  AND c.relname = ANY(:tables)
                """
            ),
            {"tables": list(EXPECTED_TABLES)},
        ).fetchall()
        assert {name for name, enabled in rls_rows if enabled} == EXPECTED_TABLES

        downgrade(revision="base")
        remaining = _public_tables()
        assert "cars" not in remaining
        assert "conversation_sessions" not in remaining

        upgrade()
        assert EXPECTED_TABLES.issubset(_public_tables())
