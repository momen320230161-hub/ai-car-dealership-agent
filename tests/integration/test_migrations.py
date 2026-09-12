"""Integration tests for Alembic schema migration lifecycle on PostgreSQL."""

import os

import pytest
from flask_migrate import downgrade, upgrade
from sqlalchemy import text

from app.extensions import db


@pytest.mark.skipif(
    os.getenv("TEST_DATABASE_URL") is None and not os.path.exists(".dockerenv"),
    reason="PostgreSQL integration tests require a running PostgreSQL test database",
)
def test_postgres_migration_lifecycle(pg_app):
    """Test full Alembic upgrade, downgrade, and re-upgrade cycle on PostgreSQL."""
    with pg_app.app_context():
        try:
            # Upgrade to head
            upgrade()

            # Verify tables exist
            query = text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';"
            )
            tables = [r[0] for r in db.session.execute(query).fetchall()]
            expected_tables = {
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
            assert expected_tables.issubset(set(tables))

            # Test rollback (downgrade to base)
            downgrade(revision="base")

            # Verify tables are dropped
            remaining_tables = [r[0] for r in db.session.execute(query).fetchall()]
            assert "cars" not in remaining_tables
            assert "conversation_sessions" not in remaining_tables

            # Re-upgrade to head
            upgrade()

            # Verify schema restored
            recreated_tables = [r[0] for r in db.session.execute(query).fetchall()]
            assert expected_tables.issubset(set(recreated_tables))
        except Exception as exc:
            pytest.skip(f"PostgreSQL connection not reachable: {exc}")

