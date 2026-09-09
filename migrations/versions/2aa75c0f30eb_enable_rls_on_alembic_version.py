"""enable rls on alembic version

Revision ID: 2aa75c0f30eb
Revises: eab82d9238b1
Create Date: 2026-09-09 17:32:03.428763

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '2aa75c0f30eb'
down_revision = 'eab82d9238b1'
branch_labels = None
depends_on = None


def upgrade():
    # The backend migration role owns this table and can continue to maintain
    # the revision marker. No Data API policy is created.
    op.execute("ALTER TABLE public.alembic_version ENABLE ROW LEVEL SECURITY")


def downgrade():
    op.execute("ALTER TABLE public.alembic_version DISABLE ROW LEVEL SECURITY")
