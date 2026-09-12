"""add_pgvector_knowledge_chunks

Revision ID: 4f6a8c2d91b7
Revises: cd73103ae9e0
Create Date: 2026-09-12
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import VECTOR

from app.models.base import GUID


revision = "4f6a8c2d91b7"
down_revision = "cd73103ae9e0"
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
    op.execute(sa.text("CREATE SCHEMA IF NOT EXISTS extensions"))
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions"))
    op.execute(sa.text("SET LOCAL search_path TO public, extensions"))

    op.add_column(
        "knowledge_documents",
        sa.Column("content_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column("index_status", sa.String(length=20), server_default="pending", nullable=False),
    )
    op.add_column(
        "knowledge_documents", sa.Column("indexed_version", sa.Integer(), nullable=True)
    )
    op.add_column(
        "knowledge_documents",
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "knowledge_documents", sa.Column("index_error", sa.Text(), nullable=True)
    )
    op.add_column(
        "knowledge_documents",
        sa.Column("embedding_model", sa.String(length=255), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_knowledge_documents_knowledge_document_content_version_positive_check"),
        "knowledge_documents",
        "content_version > 0",
    )
    op.create_check_constraint(
        op.f("ck_knowledge_documents_knowledge_document_indexed_version_positive_check"),
        "knowledge_documents",
        "indexed_version IS NULL OR indexed_version > 0",
    )
    op.create_check_constraint(
        op.f("ck_knowledge_documents_knowledge_document_index_status_check"),
        "knowledge_documents",
        "index_status IN ('pending', 'indexed', 'failed')",
    )
    op.create_index(
        "ix_knowledge_documents_retrieval_state",
        "knowledge_documents",
        ["active", "index_status", "indexed_version", "content_version"],
        unique=False,
    )

    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("document_id", GUID(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("document_version", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("embedding", VECTOR(768), nullable=False),
        sa.Column("embedding_model", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "chunk_index >= 0",
            name=op.f("ck_knowledge_chunks_knowledge_chunk_index_non_negative_check"),
        ),
        sa.CheckConstraint(
            "document_version > 0",
            name=op.f(
                "ck_knowledge_chunks_knowledge_chunk_document_version_positive_check"
            ),
        ),
        sa.CheckConstraint(
            "length(trim(content)) > 0",
            name=op.f("ck_knowledge_chunks_knowledge_chunk_content_not_blank_check"),
        ),
        sa.CheckConstraint(
            "length(content_hash) = 64",
            name=op.f("ck_knowledge_chunks_knowledge_chunk_content_hash_length_check"),
        ),
        sa.CheckConstraint(
            "length(trim(embedding_model)) > 0",
            name=op.f(
                "ck_knowledge_chunks_knowledge_chunk_embedding_model_not_blank_check"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["knowledge_documents.id"],
            name="fk_knowledge_chunks_document_id_knowledge_documents",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_chunks"),
    )
    op.create_index(
        "ix_knowledge_chunks_document_id",
        "knowledge_chunks",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_chunks_document_version",
        "knowledge_chunks",
        ["document_id", "document_version"],
        unique=False,
    )
    op.create_index(
        "uq_knowledge_chunks_document_version_index",
        "knowledge_chunks",
        ["document_id", "document_version", "chunk_index"],
        unique=True,
    )
    op.create_index(
        "ix_knowledge_chunks_embedding_hnsw",
        "knowledge_chunks",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    _enable_rls_and_revoke_data_api("knowledge_chunks")


def downgrade():
    op.drop_table("knowledge_chunks")
    op.drop_index(
        "ix_knowledge_documents_retrieval_state", table_name="knowledge_documents"
    )
    op.drop_constraint(
        op.f("ck_knowledge_documents_knowledge_document_index_status_check"),
        "knowledge_documents",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_knowledge_documents_knowledge_document_indexed_version_positive_check"),
        "knowledge_documents",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_knowledge_documents_knowledge_document_content_version_positive_check"),
        "knowledge_documents",
        type_="check",
    )
    op.drop_column("knowledge_documents", "embedding_model")
    op.drop_column("knowledge_documents", "index_error")
    op.drop_column("knowledge_documents", "indexed_at")
    op.drop_column("knowledge_documents", "indexed_version")
    op.drop_column("knowledge_documents", "index_status")
    op.drop_column("knowledge_documents", "content_version")
