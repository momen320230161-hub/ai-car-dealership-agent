"""AutoDrive Egypt Flask application factory."""

from __future__ import annotations

import uuid
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from typing import Any

import click
from flask import Flask, url_for
from sqlalchemy import event

from app.config import Config
from app.extensions import db, login_manager, migrate


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

    login_manager.init_app(app)
    login_manager.login_view = "auth.login_page"
    login_manager.login_message = "يرجى تسجيل الدخول أولاً للوصول هذه الصفحة."

    @login_manager.user_loader
    def load_user(user_id_str: str) -> models.UserProfile | None:
        try:
            user_id = uuid.UUID(user_id_str)
        except (ValueError, TypeError):
            return None
        user = db.session.get(models.UserProfile, user_id)
        if user and user.active:
            return user
        return None

    from app.blueprints.auth import bp as auth_bp
    from app.blueprints.chat import bp as chat_bp
    from app.blueprints.health import bp as health_bp
    from app.blueprints.site import bp as site_bp

    app.register_blueprint(site_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(health_bp)
    _register_asset_versioning(app)
    _register_cli(app)
    return app


def _register_asset_versioning(app: Flask) -> None:
    """Expose content-hashed static URLs without disabling browser caching."""

    static_root = Path(app.static_folder or "")

    @lru_cache(maxsize=128)
    def asset_version(filename: str) -> str:
        path = static_root / filename
        try:
            return sha256(path.read_bytes()).hexdigest()[:12]
        except OSError:
            return "missing"

    @app.context_processor
    def inject_static_asset_url():
        def static_asset(filename: str) -> str:
            return url_for("static", filename=filename, v=asset_version(filename))

        return {"static_asset": static_asset}


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
        default="data/egypt_cars_demo_100_balanced.csv",
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
        if (document_id is None and not reindex_all) or (document_id is not None and reindex_all):
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
            results = service.retrieve(query, category=category, top_k=top_k, min_score=min_score)
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
        """Invoke the sales graph from the command line."""
        from app.agent.factory import build_sales_orchestrator
        from app.agent.llm import AgentLLMError
        from app.rag.embeddings import EmbeddingError

        try:
            result = build_sales_orchestrator(db.session, app.config).handle_message(
                session_id, message
            )
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
        help="Run all live compatibility and conversational-semantic scenarios.",
    )
    def agent_llm_smoke(model: str | None, message: str, all_scenarios: bool) -> None:
        """Perform a safe live smoke test for Gemini LLM understanding and composition."""
        from app.agent.llm import AgentLLMError, GeminiAgentLLM
        from app.agent.schemas import sanitize_understanding

        target_model = model or app.config.get("AGENT_LLM_MODEL", "gemini-3.5-flash-lite")
        api_key = app.config.get("GEMINI_API_KEY")
        if not api_key:
            raise click.ClickException("GEMINI_API_KEY is not configured")

        llm = GeminiAgentLLM(
            api_key=api_key,
            model_name=target_model,
            temperature=float(app.config.get("AGENT_LLM_TEMPERATURE", 0.1)),
        )

        def assert_semantics(
            name: str,
            sanitized,
            expected_intent: str,
            expected_preferences: dict[str, Any],
        ) -> None:
            failures: list[str] = []
            if sanitized.intent != expected_intent:
                failures.append(f"intent expected {expected_intent!r}, got {sanitized.intent!r}")

            actual_preferences = sanitized.preference_updates.model_dump(exclude_none=True)
            for key, expected_value in expected_preferences.items():
                actual_value = actual_preferences.get(key)
                if key in {"brand", "model", "condition"}:
                    if str(actual_value).casefold() != str(expected_value).casefold():
                        failures.append(f"{key} expected {expected_value!r}, got {actual_value!r}")
                elif key == "max_price":
                    try:
                        matches = abs(float(actual_value) - float(expected_value)) < 1
                    except (TypeError, ValueError):
                        matches = False
                    if not matches:
                        failures.append(f"{key} expected {expected_value!r}, got {actual_value!r}")
                elif actual_value != expected_value:
                    failures.append(f"{key} expected {expected_value!r}, got {actual_value!r}")

            if failures:
                details = "; ".join(failures)
                raise AgentLLMError(f"{name} semantic validation failed: {details}")

        def assert_conversational_semantics(
            name: str,
            sanitized,
            *,
            expected_actions: set[str] | None = None,
            required_clears: set[str] | None = None,
            forbidden_clears: set[str] | None = None,
            expected_pending_field: str | None = None,
            expected_selector: dict[str, str] | None = None,
        ) -> None:
            failures: list[str] = []
            if expected_actions and sanitized.dialogue_action not in expected_actions:
                failures.append(
                    "dialogue_action expected one of "
                    f"{sorted(expected_actions)!r}, got {sanitized.dialogue_action!r}"
                )

            clears = set(sanitized.preference_clears)
            missing_clears = (required_clears or set()) - clears
            if missing_clears:
                failures.append(f"missing preference clears: {sorted(missing_clears)!r}")
            unexpected_clears = clears & (forbidden_clears or set())
            if unexpected_clears:
                failures.append(f"forbidden preference clears: {sorted(unexpected_clears)!r}")

            if (
                expected_pending_field is not None
                and sanitized.pending_field_answer != expected_pending_field
            ):
                failures.append(
                    f"pending_field_answer expected {expected_pending_field!r}, "
                    f"got {sanitized.pending_field_answer!r}"
                )

            if expected_selector is not None:
                selector = sanitized.visible_reference_selector.model_dump()
                for key, expected_value in expected_selector.items():
                    if str(selector.get(key) or "").casefold() != str(expected_value).casefold():
                        failures.append(
                            f"selector.{key} expected {expected_value!r}, "
                            f"got {selector.get(key)!r}"
                        )

            if failures:
                details = "; ".join(failures)
                raise AgentLLMError(f"{name} conversational validation failed: {details}")

        click.echo(f"model: {target_model}")
        try:
            if all_scenarios:
                scenarios = [
                    (
                        "Scenario 1 (Catalog Understanding)",
                        "عايز عربية بي ام مستعملة ومعايا 3 مليون",
                        [],
                        {},
                        "catalog_search",
                        {"brand": "BMW", "condition": "used", "max_price": 3_000_000},
                    ),
                    (
                        "Scenario 2 (Multi-turn Understanding)",
                        "عايزها X6",
                        [
                            {"role": "user", "content": "عايز عربية بي ام مستعملة ومعايا 3 مليون"},
                            {"role": "assistant", "content": "تمام، في موديل معين في دماغك؟"},
                        ],
                        {"brand": "BMW", "max_price": 3000000},
                        "catalog_search",
                        {"model": "X6"},
                    ),
                    (
                        "Scenario 3 (Knowledge Routing)",
                        "الضمان مدته كام؟",
                        [],
                        {},
                        "knowledge_question",
                        {},
                    ),
                    (
                        "Scenario 4 (Unsupported Knowledge Routing)",
                        "هل عندكم تأمين سيارات ضد الحوادث؟",
                        [],
                        {},
                        "knowledge_question",
                        {},
                    ),
                    (
                        "Scenario 5 (General)",
                        "شكراً",
                        [],
                        {},
                        "general",
                        {},
                    ),
                ]
                for (
                    name,
                    msg,
                    recent,
                    prefs,
                    expected_intent,
                    expected_preferences,
                ) in scenarios:
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
                    assert_semantics(
                        name,
                        sanitized,
                        expected_intent,
                        expected_preferences,
                    )
                    click.echo("semantic validation: PASS")

                semantic_scenarios = [
                    {
                        "name": "Scenario 6 (Scoped Preference Waiver)",
                        "message": "مش فارق معايا سيدان ولا SUV، بس لازم جديدة",
                        "preferences": {
                            "body_type": "Sedan",
                            "condition": "used",
                            "max_price": 800000,
                        },
                        "context": {},
                        "intent": "catalog_search",
                        "expected_preferences": {"condition": "new"},
                        "actions": {"refine", "broaden", "recommend"},
                        "required_clears": {"body_type"},
                        "forbidden_clears": {"max_price"},
                    },
                    {
                        "name": "Scenario 7 (Flexible Automatic Request)",
                        "message": "أي حاجة أوتوماتيك بس",
                        "preferences": {
                            "condition": "used",
                            "body_type": "Sedan",
                            "max_price": 1000000,
                        },
                        "context": {},
                        "intent": "catalog_search",
                        "expected_preferences": {"transmission": "Automatic"},
                        "actions": {"refine", "broaden", "recommend"},
                        "required_clears": {"condition", "body_type"},
                        "forbidden_clears": {"max_price"},
                    },
                    {
                        "name": "Scenario 8 (Pending Single Name)",
                        "message": "مؤمن",
                        "preferences": {},
                        "context": {
                            "pending_action": {
                                "type": "test_drive",
                                "collected_fields": ["car_id"],
                                "missing_fields": [
                                    "customer_name",
                                    "phone",
                                    "preferred_date",
                                    "preferred_time",
                                ],
                            }
                        },
                        "intent": "general",
                        "expected_preferences": {},
                        "pending_field": "customer_name",
                    },
                    {
                        "name": "Scenario 9 (Visible Cheapest Reference)",
                        "message": "الأرخص عاجباني",
                        "preferences": {},
                        "context": {
                            "visible_recommendations": [
                                {
                                    "position": 1,
                                    "brand": "Kia",
                                    "model": "Sportage",
                                    "price_egp": 1800000,
                                },
                                {
                                    "position": 2,
                                    "brand": "Nissan",
                                    "model": "Sunny",
                                    "price_egp": 900000,
                                },
                                {
                                    "position": 3,
                                    "brand": "Toyota",
                                    "model": "Corolla",
                                    "price_egp": 1300000,
                                },
                            ]
                        },
                        "intent": "car_selection",
                        "expected_preferences": {},
                        "selector": {"field": "price_egp", "operator": "min"},
                    },
                    {
                        "name": "Scenario 10 (Visible Attribute Reference)",
                        "message": "هات تفاصيل الأوتوماتيك",
                        "preferences": {},
                        "context": {
                            "visible_recommendations": [
                                {
                                    "position": 1,
                                    "brand": "Kia",
                                    "model": "Sportage",
                                    "transmission": "Automatic",
                                },
                                {
                                    "position": 2,
                                    "brand": "Nissan",
                                    "model": "Sunny",
                                    "transmission": "Manual",
                                },
                            ]
                        },
                        "intent": "car_details",
                        "expected_preferences": {},
                        "selector": {
                            "field": "transmission",
                            "operator": "equals",
                            "value": "Automatic",
                        },
                    },
                ]

                for scenario in semantic_scenarios:
                    name = str(scenario["name"])
                    msg = str(scenario["message"])
                    prefs = dict(scenario["preferences"])
                    context = dict(scenario["context"])
                    click.echo(f"\n--- {name} ---")
                    click.echo(f"input: {msg}")
                    raw = llm.understand_with_context(
                        msg,
                        recent_messages=[],
                        preferences=prefs,
                        conversation_context=context,
                    )
                    sanitized = sanitize_understanding(raw, msg)
                    click.echo(f"sanitized intent: {sanitized.intent}")
                    click.echo(
                        "sanitized preferences: "
                        f"{sanitized.preference_updates.model_dump(exclude_none=True)}"
                    )
                    click.echo(f"dialogue action: {sanitized.dialogue_action}")
                    click.echo(f"preference clears: {sanitized.preference_clears}")
                    click.echo(f"pending field: {sanitized.pending_field_answer}")
                    click.echo(
                        "visible selector: "
                        f"{sanitized.visible_reference_selector.model_dump()}"
                    )
                    assert_semantics(
                        name,
                        sanitized,
                        str(scenario["intent"]),
                        dict(scenario["expected_preferences"]),
                    )
                    assert_conversational_semantics(
                        name,
                        sanitized,
                        expected_actions=scenario.get("actions"),
                        required_clears=scenario.get("required_clears"),
                        forbidden_clears=scenario.get("forbidden_clears"),
                        expected_pending_field=scenario.get("pending_field"),
                        expected_selector=scenario.get("selector"),
                    )
                    click.echo("conversational semantic validation: PASS")

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

    @app.cli.command("set-user-role")
    @click.argument("email")
    @click.argument("role")
    def set_user_role(email: str, role: str) -> None:
        """Assign or update role for an existing UserProfile."""
        from app.services.auth_service import AuthService

        try:
            user = AuthService(db.session).set_user_role(email, role)
            click.echo(
                f"Successfully set role {user.role!r} for user {user.email!r} (ID: {user.id})"
            )
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
