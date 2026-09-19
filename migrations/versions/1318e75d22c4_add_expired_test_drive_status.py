"""add expired test drive status

Revision ID: 1318e75d22c4
Revises: 8c1e4d7f2a90
Create Date: 2026-09-19 20:35:02.729704

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "1318e75d22c4"
down_revision = "8c1e4d7f2a90"
branch_labels = None
depends_on = None


_CONSTRAINT = "ck_test_drive_requests_test_drive_status_check"
_DROP_STATUS_CHECK = sa.text(
    """
    DO $$
    DECLARE
        status_constraint text;
    BEGIN
        SELECT conname INTO status_constraint
        FROM pg_constraint
        WHERE conrelid = 'public.test_drive_requests'::regclass
          AND contype = 'c'
          AND pg_get_constraintdef(oid) LIKE '%status%'
          AND pg_get_constraintdef(oid) LIKE '%NEW%'
          AND pg_get_constraintdef(oid) LIKE '%CANCELLED%'
        ORDER BY conname
        LIMIT 1;

        IF status_constraint IS NULL THEN
            RAISE EXCEPTION 'test_drive_requests status check constraint was not found';
        END IF;

        EXECUTE format(
            'ALTER TABLE public.test_drive_requests DROP CONSTRAINT %I',
            status_constraint
        );
    END
    $$;
    """
)


def upgrade():
    op.execute(_DROP_STATUS_CHECK)
    op.execute(
        sa.text(
            f"ALTER TABLE public.test_drive_requests ADD CONSTRAINT {_CONSTRAINT} "
            "CHECK (status IN ('NEW', 'CONFIRMED', 'COMPLETED', 'CANCELLED', 'EXPIRED'))"
        )
    )
    op.execute(
        sa.text(
            "UPDATE test_drive_requests "
            "SET status = 'EXPIRED', updated_at = now() "
            "WHERE status IN ('NEW', 'CONFIRMED') AND preferred_date < CURRENT_DATE"
        )
    )


def downgrade():
    op.execute(
        sa.text(
            "UPDATE test_drive_requests "
            "SET status = 'CANCELLED', cancelled_at = COALESCE(cancelled_at, now()), "
            "updated_at = now() WHERE status = 'EXPIRED'"
        )
    )
    op.execute(_DROP_STATUS_CHECK)
    op.execute(
        sa.text(
            f"ALTER TABLE public.test_drive_requests ADD CONSTRAINT {_CONSTRAINT} "
            "CHECK (status IN ('NEW', 'CONFIRMED', 'COMPLETED', 'CANCELLED'))"
        )
    )
