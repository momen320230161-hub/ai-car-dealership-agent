"""Real PostgreSQL 17 + pgvector integration coverage for managed RAG."""

from __future__ import annotations

from flask_migrate import upgrade
from sqlalchemy import func, select, text

from app.extensions import db
from app.models.knowledge import KnowledgeChunk
from app.rag.embeddings import DeterministicEmbeddingProvider
from app.services.knowledge_service import KnowledgeService
from app.services.rag_service import RAGService


def _truncate_knowledge() -> None:
    db.session.execute(
        text(
            "TRUNCATE TABLE knowledge_chunks, knowledge_documents "
            "RESTART IDENTITY CASCADE"
        )
    )
    db.session.commit()


def _services():
    provider = DeterministicEmbeddingProvider()
    return KnowledgeService(db.session, provider), RAGService(db.session, provider)


def test_phase3_migration_creates_vector_schema_column_hnsw_and_rls(pg_app):
    with pg_app.app_context():
        upgrade()
        extension = db.session.execute(
            text(
                """
                SELECT e.extname, n.nspname
                FROM pg_extension AS e
                JOIN pg_namespace AS n ON n.oid = e.extnamespace
                WHERE e.extname = 'vector'
                """
            )
        ).one()
        vector_type = db.session.scalar(
            text(
                """
                SELECT format_type(a.atttypid, a.atttypmod)
                FROM pg_attribute AS a
                WHERE a.attrelid = 'public.knowledge_chunks'::regclass
                  AND a.attname = 'embedding'
                """
            )
        )
        index_definition = db.session.scalar(
            text(
                """
                SELECT indexdef
                FROM pg_indexes
                WHERE schemaname = 'public'
                  AND indexname = 'ix_knowledge_chunks_embedding_hnsw'
                """
            )
        )
        rls_enabled = db.session.scalar(
            text(
                """
                SELECT relrowsecurity
                FROM pg_class
                WHERE oid = 'public.knowledge_chunks'::regclass
                """
            )
        )

        assert extension == ("vector", "extensions")
        assert vector_type == "vector(768)"
        assert "USING hnsw" in index_definition
        assert "vector_cosine_ops" in index_definition
        assert rls_enabled is True
        assert db.session.scalar(text("SHOW search_path")) == "public, extensions"
        db.session.rollback()


def test_actual_cosine_order_category_and_active_filtering(pg_app):
    with pg_app.app_context():
        upgrade()
        _truncate_knowledge()
        knowledge, rag = _services()
        relevant = knowledge.create_document(
            title="Relevant",
            category="faq",
            content="Phase3 verification policy alpha",
        )
        unrelated = knowledge.create_document(
            title="Unrelated",
            category="faq",
            content="Synthetic showroom color information omega",
        )
        other_category = knowledge.create_document(
            title="Other category",
            category="warranty",
            content="Phase3 verification policy alpha warranty",
        )

        results = rag.retrieve("Phase3 verification policy alpha", top_k=3)
        assert [result.document_id for result in results[:2]] == [
            relevant.id,
            other_category.id,
        ]
        assert results[0].similarity > results[-1].similarity
        faq_results = rag.retrieve(
            "Phase3 verification policy alpha", category="FAQ", top_k=3
        )
        assert [result.document_id for result in faq_results] == [
            relevant.id,
            unrelated.id,
        ]

        knowledge.set_active(relevant.id, False)
        inactive_filtered = rag.retrieve(
            "Phase3 verification policy alpha", category="faq", top_k=3
        )
        assert relevant.id not in {result.document_id for result in inactive_filtered}
        _truncate_knowledge()


def test_current_version_filter_excludes_stale_failed_or_pending_documents(pg_app):
    with pg_app.app_context():
        upgrade()
        _truncate_knowledge()
        knowledge, rag = _services()
        document = knowledge.create_document(
            title="Stale fixture",
            category="stale-test",
            content="Phase3 stale version alpha",
        )
        assert knowledge.repository.count_chunks(document.id) == 1

        document.content = "Phase3 current version beta"
        document.content_version = 2
        document.index_status = "failed"
        document.index_error = "Synthetic failure"
        db.session.commit()

        assert rag.retrieve("Phase3 stale version alpha", category="stale-test") == []
        document.index_status = "pending"
        db.session.commit()
        assert rag.retrieve("Phase3 stale version alpha", category="stale-test") == []
        _truncate_knowledge()


def test_managed_crud_retrieval_lifecycle_replaces_and_deletes_content(pg_app):
    with pg_app.app_context():
        upgrade()
        _truncate_knowledge()
        knowledge, rag = _services()

        document = knowledge.create_document(
            title="Test Drive Policy",
            category="test drive policy",
            content="Phase3 verification policy alpha",
        )
        alpha_results = rag.retrieve(
            "Phase3 verification policy alpha", category="test drive policy"
        )
        assert any(
            result.document_id == document.id
            and result.content == "Phase3 verification policy alpha"
            for result in alpha_results
        )

        updated = knowledge.update_document(
            document.id, content="Phase3 verification policy beta"
        )
        beta_results = rag.retrieve(
            "Phase3 verification policy beta", category="test drive policy"
        )
        assert updated.content_version == updated.indexed_version == 2
        assert any(result.content == "Phase3 verification policy beta" for result in beta_results)
        assert all("alpha" not in result.content for result in beta_results)
        assert knowledge.repository.count_chunks(document.id) == 1

        reindexed = knowledge.reindex_document(document.id)
        assert reindexed.index_status == "indexed"
        assert knowledge.repository.count_chunks(document.id) == 1
        stored_dimension = db.session.scalar(
            select(func.vector_dims(KnowledgeChunk.embedding)).where(
                KnowledgeChunk.document_id == document.id
            )
        )
        assert stored_dimension == 768

        knowledge.delete_document(document.id)
        assert rag.retrieve("Phase3 verification policy beta", category="test drive policy") == []
        assert db.session.scalar(select(func.count()).select_from(KnowledgeChunk)) == 0
        _truncate_knowledge()
