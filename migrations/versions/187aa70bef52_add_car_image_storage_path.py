"""add car image storage path

Revision ID: 187aa70bef52
Revises: 1318e75d22c4
Create Date: 2026-09-19 21:12:46.822634

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "187aa70bef52"
down_revision = "1318e75d22c4"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("cars", sa.Column("image_storage_path", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("cars", "image_storage_path")
