"""create_user_profiles_and_session_ownership

Revision ID: 5e8b9f1a2c3d
Revises: 4f6a8c2d91b7
Create Date: 2026-09-15
"""

import sqlalchemy as sa
from alembic import op

from app.models.base import GUID

revision = "5e8b9f1a2c3d"
down_revision = "4f6a8c2d91b7"
branch_labels = None
depends_on = None


def _enable_rls_and_revoke_data_api(table_name: str) -> None:
    op.execute(sa.text(f'ALTER TABLE public."{table_name}" ENABLE ROW LEVEL SECURITY'))
    for role_name in ("anon", "authenticated"):
        op.execute(
            sa.text(
                f"""
                DO $$
                BEGIN
                    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role_name}') THEN
                        EXECUTE 'REVOKE ALL ON TABLE public."{table_name}" FROM {role_name}';
                    END IF;
                END
                $$;
                """
            )
        )


def upgrade():
    op.create_table(
        "user_profiles",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("avatar_url", sa.String(length=1024), nullable=True),
        sa.Column(
            "role",
            sa.String(length=50),
            server_default="customer",
            nullable=False,
        ),
        sa.Column(
            "active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("role IN ('customer', 'admin')", name="user_profile_role_check"),
        sa.PrimaryKeyConstraint("id", name="pk_user_profiles"),
    )
    op.create_index("ix_user_profiles_email", "user_profiles", ["email"], unique=True)
    op.create_index("ix_user_profiles_role", "user_profiles", ["role"], unique=False)
    _enable_rls_and_revoke_data_api("user_profiles")

    op.add_column(
        "conversation_sessions",
        sa.Column("user_id", GUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_conversation_sessions_user_id_user_profiles",
        "conversation_sessions",
        "user_profiles",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_conversation_sessions_user_id",
        "conversation_sessions",
        ["user_id"],
        unique=False,
    )


def downgrade():
    op.drop_index("ix_conversation_sessions_user_id", table_name="conversation_sessions")
    op.drop_constraint(
        "fk_conversation_sessions_user_id_user_profiles",
        "conversation_sessions",
        type_="foreignkey",
    )
    op.drop_column("conversation_sessions", "user_id")

    op.drop_index("ix_user_profiles_role", table_name="user_profiles")
    op.drop_index("ix_user_profiles_email", table_name="user_profiles")
    op.drop_table("user_profiles")
