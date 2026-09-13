"""AutoDrive Egypt Flask application factory."""

from __future__ import annotations

from typing import Any

import click
from flask import Flask
from sqlalchemy import event

from app.config import Config
from app.extensions import db, migrate


def create_app(config_overrides: dict[str, Any] | None = None) -> Flask:
    """Create and configure the Flask application."""
    app = Flask(__name__)
    app.config.from_object(Config)

    if config_overrides:
        app.config.update(config_overrides)

    _validate_required_config(app)

    # Import models so that SQLAlchemy and Flask-Migrate discover metadata
    from app import models  # noqa: F401

    db.init_app(app)
    migrate.init_app(app, db, compare_type=True)
    _configure_postgres_search_path(app)

    from app.blueprints.health import bp as health_bp

    app.register_blueprint(health_bp)
    _register_cli(app)
    return app


def _validate_required_config(app: Flask) -> None:
    missing: list[str] = []

    if not app.config.get("SECRET_KEY"):
        missing.append("SECRET_KEY")
    if not app.config.get("SQLALCHEMY_DATABASE_URI"):
        missing.append("DATABASE_URL")

    if missing:
        joined = ", ".join(missing)
        raise RuntimeError(f"Missing required environment configuration: {joined}")


def _configure_postgres_search_path(app: Flask) -> None:
    """Make pgvector operators in Supabase's extensions schema resolvable."""
    with app.app_context():
        engine = db.engine
        if engine.dialect.name != "postgresql":
            return

        @event.listens_for(engine, "connect")
        def set_search_path(dbapi_connection, connection_record) -> None:
            del connection_record
            previous_autocommit = dbapi_connection.autocommit
            dbapi_connection.autocommit = True
            try:
                with dbapi_connection.cursor() as cursor:
                    cursor.execute("SET SESSION search_path TO public, extensions")
            finally:
                dbapi_connection.autocommit = previous_autocommit


def _register_cli(app: Flask) -> None:
    @app.cli.command("import-catalog")
    @click.option(
        "--path",
        default="data/egypt_cars_final_import_ready.csv",
        type=click.Path(path_type=str, dir_okay=False),
        show_default=True,
    )
    def import_catalog(path: str) -> None:
        """Import or synchronize the authoritative structured car catalog."""
        from app.services.catalog_import_service import CatalogImportService

        report = CatalogImportService(db.session).import_file(path)
        click.echo(f"file rows: {report.file_rows}")
        click.echo(f"inserted: {report.inserted}")
        click.echo(f"updated: {report.updated}")
        click.echo(f"unchanged: {report.unchanged}")
        click.echo(f"rejected: {report.rejected}")
        for error in report.errors:
            click.echo(f"error: {error}", err=True)

    @app.cli.command("reindex-knowledge")
    @click.option("--document-id", type=click.UUID, default=None)
    @click.option("--all", "reindex_all", is_flag=True)
    @click.option("--failed-only", is_flag=True)
    def reindex_knowledge(document_id, reindex_all: bool, failed_only: bool) -> None:
        """Rebuild vector chunks for one document or an observable document set."""
        if (document_id is None and not reindex_all) or (
            document_id is not None and reindex_all
        ):
            raise click.UsageError("Choose exactly one of --document-id or --all")
        if failed_only and not reindex_all:
            raise click.UsageError("--failed-only requires --all")

        from app.rag.embeddings import EmbeddingError, build_embedding_provider
        from app.services.knowledge_service import KnowledgeService, KnowledgeServiceError

        try:
            service = KnowledgeService(db.session, build_embedding_provider(app.config))
            if document_id is not None:
                document = service.reindex_document(document_id)
                click.echo(f"indexed document: {document.id}")
                click.echo(f"status: {document.index_status}")
            else:
                report = service.reindex_all(failed_only=failed_only)
                click.echo(f"requested: {report.requested}")
                click.echo(f"indexed: {report.indexed}")
                click.echo(f"failed: {report.failed}")
                for error in report.errors:
                    click.echo(f"error: {error}", err=True)
                if report.failed:
                    raise KnowledgeServiceError(
                        f"{report.failed} knowledge document(s) failed to reindex"
                    )
        except (EmbeddingError, KnowledgeServiceError) as exc:
            raise click.ClickException(str(exc)) from exc

    @app.cli.command("seed-knowledge")
    @click.option(
        "--path",
        default="data/knowledge_seed.json",
        type=click.Path(path_type=str, dir_okay=False),
        show_default=True,
    )
    def seed_knowledge(path: str) -> None:
        """Synchronize the approved production knowledge seed through managed RAG."""
        from app.rag.embeddings import EmbeddingError, build_embedding_provider
        from app.services.knowledge_seed_service import KnowledgeSeedError, KnowledgeSeedService
        from app.services.knowledge_service import KnowledgeService, KnowledgeServiceError

        try:
            knowledge = KnowledgeService(db.session, build_embedding_provider(app.config))
            report = KnowledgeSeedService(knowledge).seed_file(path)
            click.echo(f"seed version: {report.version}")
            click.echo(f"documents: {report.total}")
            click.echo(f"created: {report.created}")
            click.echo(f"updated: {report.updated}")
            click.echo(f"reindexed: {report.reindexed}")
            click.echo(f"unchanged: {report.unchanged}")
            click.echo(f"failed: {report.failed}")
            for error in report.errors:
                click.echo(f"error: {error}", err=True)
            if report.failed:
                raise KnowledgeSeedError(
                    f"{report.failed} knowledge document(s) failed to synchronize"
                )
        except (EmbeddingError, KnowledgeServiceError, KnowledgeSeedError) as exc:
            raise click.ClickException(str(exc)) from exc

    @app.cli.command("rag-search")
    @click.argument("query")
    @click.option("--category", default=None)
    @click.option("--top-k", type=click.IntRange(min=1), default=None)
    @click.option("--min-score", type=float, default=None)
    def rag_search(
        query: str, category: str | None, top_k: int | None, min_score: float | None
    ) -> None:
        """Run structured pgvector retrieval without composing an LLM answer."""
        from app.rag.embeddings import EmbeddingError, build_embedding_provider
        from app.services.rag_service import RAGRetrievalError, RAGService

        try:
            service = RAGService(
                db.session,
                build_embedding_provider(app.config),
                default_top_k=app.config["RAG_TOP_K"],
                max_top_k=app.config["RAG_MAX_TOP_K"],
                default_min_score=app.config["RAG_MIN_SCORE"],
            )
            results = service.retrieve(
                query, category=category, top_k=top_k, min_score=min_score
            )
            if not results:
                click.echo("no indexed knowledge matched")
            for result in results:
                excerpt = result.content[:160].replace("\n", " ")
                click.echo(
                    f"{result.title} | {result.category} | "
                    f"similarity={result.similarity:.4f} | {excerpt}"
                )
        except (EmbeddingError, RAGRetrievalError, ValueError) as exc:
            raise click.ClickException(str(exc)) from exc

    @app.cli.command("agent-chat")
    @click.argument("message")
    @click.option("--session-id", type=click.UUID, default=None)
    def agent_chat(message: str, session_id) -> None:
        """Invoke the Phase 4 sales graph without exposing an HTTP/UI surface."""
        from app.agent.graph import SalesOrchestrator
        from app.agent.llm import AgentLLMError, build_agent_llm
        from app.rag.embeddings import EmbeddingError, build_embedding_provider

        try:
            orchestrator = SalesOrchestrator(
                db.session,
                build_agent_llm(app.config),
                build_embedding_provider(app.config),
                max_message_length=app.config["AGENT_MAX_MESSAGE_LENGTH"],
                recent_message_limit=app.config["AGENT_RECENT_MESSAGE_LIMIT"],
                recommendation_limit=app.config["AGENT_RECOMMENDATION_LIMIT"],
                rag_top_k=app.config["RAG_TOP_K"],
                rag_max_top_k=app.config["RAG_MAX_TOP_K"],
                rag_min_score=app.config["RAG_MIN_SCORE"],
            )
            result = orchestrator.handle_message(session_id, message)
            click.echo(f"session id: {result.session_id}")
            click.echo(f"intent: {result.intent}")
            click.echo(f"route: {result.route}")
            if result.recommendation_snapshot_id is not None:
                click.echo(f"snapshot id: {result.recommendation_snapshot_id}")
            if result.selected_car_id is not None:
                click.echo(f"selected car id: {result.selected_car_id}")
            if result.errors:
                click.echo(f"errors: {', '.join(result.errors)}")
            click.echo(result.response)
        except (AgentLLMError, EmbeddingError, ValueError) as exc:
            raise click.ClickException(str(exc)) from exc

    @app.cli.command("agent-llm-smoke")
    @click.option("--model", default=None, help="Target Gemini model ID to smoke test.")
    @click.option(
        "--message",
        default="عايز عربية بي ام مستعملة ومعايا 3 مليون",
        help="Test query message.",
    )
    @click.option(
        "--all-scenarios",
        is_flag=True,
        help="Run all 5 live compatibility scenarios.",
    )
    def agent_llm_smoke(model: str | None, message: str, all_scenarios: bool) -> None:
        """Perform a safe live smoke test for Gemini LLM understanding and composition."""
        from app.agent.llm import AgentLLMError, GeminiAgentLLM
        from app.agent.schemas import sanitize_understanding

        target_model = model or app.config.get("AGENT_LLM_MODEL", "gemini-3.6-flash")
        api_key = app.config.get("GEMINI_API_KEY")
        if not api_key:
            raise click.ClickException("GEMINI_API_KEY is not configured")

        llm = GeminiAgentLLM(
            api_key=api_key,
            model_name=target_model,
            temperature=float(app.config.get("AGENT_LLM_TEMPERATURE", 0.1)),
        )

        click.echo(f"model: {target_model}")
        try:
            if all_scenarios:
                scenarios = [
                    (
                        "Scenario 1 (Catalog Understanding)",
                        "عايز عربية بي ام مستعملة ومعايا 3 مليون",
                        [],
                        {},
                    ),
                    (
                        "Scenario 2 (Multi-turn Understanding)",
                        "عايزها X6",
                        [
                            {"role": "user", "content": "عايز عربية بي ام مستعملة ومعايا 3 مليون"},
                            {"role": "assistant", "content": "تمام، في موديل معين في دماغك؟"},
                        ],
                        {"brand": "BMW", "max_price": 3000000},
                    ),
                    (
                        "Scenario 3 (Knowledge Routing)",
                        "الضمان مدته كام؟",
                        [],
                        {},
                    ),
                    (
                        "Scenario 4 (Unsupported Knowledge Routing)",
                        "هل عندكم تأمين سيارات ضد الحوادث؟",
                        [],
                        {},
                    ),
                    (
                        "Scenario 5 (General)",
                        "شكراً",
                        [],
                        {},
                    ),
                ]
                for name, msg, recent, prefs in scenarios:
                    click.echo(f"\n--- {name} ---")
                    click.echo(f"input: {msg}")
                    raw = llm.understand(msg, recent_messages=recent, preferences=prefs)
                    raw_prefs = raw.preference_updates.model_dump(exclude_none=True)
                    click.echo(f"raw parsed intent: {raw.intent}")
                    click.echo(f"raw parsed preferences: {raw_prefs}")
                    sanitized = sanitize_understanding(raw, msg)
                    sanitized_prefs = sanitized.preference_updates.model_dump(exclude_none=True)
                    click.echo(f"sanitized intent: {sanitized.intent}")
                    click.echo(f"sanitized preferences: {sanitized_prefs}")

                click.echo("\n--- Composition Test ---")
                comp = llm.compose_general("شكراً", verified_context={"topic": "general_closing"})
                click.echo(f"composition response: {comp}")
                click.echo("\nstatus: PASS")
            else:
                raw_understanding = llm.understand(
                    message,
                    recent_messages=[],
                    preferences={},
                )
                raw_prefs = raw_understanding.preference_updates.model_dump(exclude_none=True)
                click.echo(f"raw parsed intent: {raw_understanding.intent}")
                click.echo(f"raw parsed preferences: {raw_prefs}")

                sanitized = sanitize_understanding(raw_understanding, message)
                sanitized_prefs = sanitized.preference_updates.model_dump(exclude_none=True)
                click.echo(f"sanitized intent: {sanitized.intent}")
                click.echo(f"sanitized preferences: {sanitized_prefs}")

                comp = llm.compose_general("شكراً", verified_context={"topic": "general_closing"})
                click.echo(f"composition response: {comp}")
                click.echo("status: PASS")
        except AgentLLMError as exc:
            click.echo(f"status: FAIL ({exc})", err=True)
            raise click.ClickException(f"Live smoke test failed: {exc}") from exc
        except Exception as exc:
            click.echo(f"status: FAIL ({exc})", err=True)
            raise click.ClickException(
                f"Live smoke test encountered an unexpected error: {exc}"
            ) from exc
