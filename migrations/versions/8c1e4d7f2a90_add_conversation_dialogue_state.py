"""add_conversation_dialogue_state

Revision ID: 8c1e4d7f2a90
Revises: 5e8b9f1a2c3d
Create Date: 2026-09-17
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "8c1e4d7f2a90"
down_revision = "5e8b9f1a2c3d"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "conversation_sessions",
        sa.Column(
            "dialogue_state",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )


def downgrade():
    op.drop_column("conversation_sessions", "dialogue_state")
