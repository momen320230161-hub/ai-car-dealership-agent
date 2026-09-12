# AutoDrive Egypt — AI Car Dealership Agent

AI Sales & Customer Service technical-assessment project for AutoDrive Egypt.

## Current Status

- **Phase 0 — Foundation: COMPLETE**
- **Phase 1 — Database & ORM: COMPLETE**
- **Next: Phase 2 — Catalog import, structured search, recommendation state, visible-list selection/comparison**

This is the clean final-project rebuild on the `Final-Project` branch. Legacy application code is not reused.

## Current Stack

- Python 3.12
- `uv` with `pyproject.toml` + committed `uv.lock`
- Flask Application Factory
- Flask-SQLAlchemy / SQLAlchemy 2.x
- Flask-Migrate / Alembic
- Psycopg 3
- Supabase PostgreSQL
- pytest
- Ruff
- GitHub Actions

Docker foundation files exist from Phase 0, but **application Dockerization is frozen until Phase 9**. Phases 2–8 must not create per-phase application images. GitHub Actions may use an ephemeral PostgreSQL service only as test infrastructure.

## Phase 1 Relational Schema

Alembic revision `cd73103ae9e0` is the application schema source of truth.

Application tables:

- `cars` — structured catalog records and source/data-quality metadata
- `conversation_sessions` — structured session preferences, selected car, active visible snapshot, pending action
- `chat_messages` — persisted session messages
- `recommendation_snapshots` — versioned customer-visible recommendation lists
- `recommendation_snapshot_items` — deterministic `position -> car_id` mapping
- `test_drive_requests` — persisted booking records with session ownership and idempotency
- `sales_leads` — persisted sales leads with idempotency
- `knowledge_documents` — dealership-owned knowledge metadata/content; chunks/vectors come in Phase 3

`RecommendationSnapshotItem` enforces unique visible positions and prevents the same car from occupying multiple positions in one snapshot. PostgreSQL also enforces that a session's `active_recommendation_snapshot_id` belongs to that same session.

Business workflows, ordinal resolution, RAG retrieval, LangGraph, chat UI, and admin UI are intentionally not implemented yet.

## Database Access and Security

The application access path is:

```text
Flask -> SQLAlchemy -> Psycopg -> Supabase PostgreSQL
```

The browser does not access Supabase tables directly.

Phase 1 enables RLS on application tables in `public` and revokes direct `anon` / `authenticated` table privileges when those roles exist. No broad Data API policies are created because the Flask backend is the database access layer.

The previous prototype schema was moved out of `public` into `legacy_archive` during the final Phase 1 live reset. This preserves legacy catalog data as a backup/reference while keeping the final application's `public` schema clean.

## Local Setup

```bash
uv sync --locked
```

Create `.env` from `.env.example` and provide:

- `SECRET_KEY`
- `DATABASE_URL`
- optional Flask development settings

Run locally:

```bash
uv run flask --app run:app run --debug
```

## Health Checks

```text
GET /health
GET /health/db
```

`/health` checks the Flask process only. `/health/db` executes a lightweight `SELECT 1` through SQLAlchemy and returns a controlled `503` if the database is unavailable.

## Migrations

Alembic / Flask-Migrate is the only application schema migration source of truth.

```bash
uv run flask --app run:app db upgrade
uv run flask --app run:app db downgrade
uv run flask --app run:app db upgrade
```

Do not use `db.create_all()` as an application migration strategy. It is used only inside isolated SQLite unit-test fixtures.

## Tests and Quality

```bash
uv run ruff check .
uv run pytest -q
```

The test suite includes:

- isolated SQLite model/constraint tests
- PostgreSQL 17 migration lifecycle tests
- PostgreSQL production-type persistence tests
- same-session active recommendation snapshot enforcement
- Phase 0 health-check regressions

GitHub Actions uses an ephemeral PostgreSQL 17 service. It does not use the live Supabase database and does not build application Docker images.

## Roadmap

- **Phase 2:** Catalog import, deterministic recommendation state, visible-list selection/comparison
- **Phase 3:** RAG + pgvector + knowledge CRUD/reindex
- **Phase 4:** LangGraph Sales Orchestrator
- **Phase 5:** Test-drive/cancellation and sales-lead business actions
- **Phase 6:** Customer Flask chat UI
- **Phase 7:** Admin dashboard
- **Phase 8:** Hardening, integration tests, live LLM/graph E2E
- **Phase 9:** Final Dockerization, README/demo polish, submission
