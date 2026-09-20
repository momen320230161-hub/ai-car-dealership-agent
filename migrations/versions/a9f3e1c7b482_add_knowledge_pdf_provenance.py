"""add_knowledge_pdf_provenance

Revision ID: a9f3e1c7b482
Revises: 187aa70bef52
Create Date: 2026-09-20

Adds optional PDF provenance columns to knowledge_documents:
  source_type, source_name, source_url, source_filename,
  source_sha256, source_mime_type, source_file_size,
  source_page_count, ingested_at, extraction_method

All columns are nullable so existing manual documents remain valid.
A non-unique index on source_sha256 supports duplicate detection queries.
"""

import sqlalchemy as sa
from alembic import op

revision = "a9f3e1c7b482"
down_revision = "187aa70bef52"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "knowledge_documents",
        sa.Column("source_type", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column("source_name", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column("source_url", sa.Text(), nullable=True),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column("source_filename", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column("source_sha256", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column("source_mime_type", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column("source_file_size", sa.Integer(), nullable=True),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column("source_page_count", sa.Integer(), nullable=True),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column("extraction_method", sa.String(length=50), nullable=True),
    )
    # Non-unique index for fast sha256 lookups (duplicate check).
    # We intentionally allow NULL (manual docs) — only one PDF per hash.
    op.create_index(
        "ix_knowledge_documents_source_sha256",
        "knowledge_documents",
        ["source_sha256"],
        unique=True,
    )
    op.create_index(
        "ix_knowledge_documents_source_type",
        "knowledge_documents",
        ["source_type"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_knowledge_documents_source_type", table_name="knowledge_documents")
    op.drop_index("ix_knowledge_documents_source_sha256", table_name="knowledge_documents")
    op.drop_column("knowledge_documents", "extraction_method")
    op.drop_column("knowledge_documents", "ingested_at")
    op.drop_column("knowledge_documents", "source_page_count")
    op.drop_column("knowledge_documents", "source_file_size")
    op.drop_column("knowledge_documents", "source_mime_type")
    op.drop_column("knowledge_documents", "source_sha256")
    op.drop_column("knowledge_documents", "source_filename")
    op.drop_column("knowledge_documents", "source_url")
    op.drop_column("knowledge_documents", "source_name")
    op.drop_column("knowledge_documents", "source_type")
