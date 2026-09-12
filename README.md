# AutoDrive Egypt — AI Car Dealership Agent

AI Sales & Customer Service technical-assessment project for AutoDrive Egypt.

## Current Status

- **Phase 0 — Foundation: COMPLETE**
- **Phase 1 — Database & ORM: COMPLETE**
- **Phase 2 — Catalog import, structured search, recommendation state, visible-list selection/comparison: COMPLETE**
- **Phase 3 — RAG foundation: NOT STARTED**

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

## Phase 2 Catalog Import

The authoritative dataset is `data/egypt_cars_final_import_ready.csv`:

- 7,771 total catalog records
- 1,930 NEW records
- 5,841 USED records

Import or synchronize it after applying migrations:

```bash
uv run flask --app run:app import-catalog
```

The importer validates headers and row types, converts blank optional values to `NULL`, and uses `(source, source_id)` as its stable identity. Existing rows are updated in place, preserving their database IDs; unchanged rows are counted without being rewritten. Running the command repeatedly does not create duplicates.

If a NEW row has no source mileage, the importer defensively stores `mileage_km = 0` and records both `mileage_source_was_missing` and `mileage_normalization` in `data_quality_metadata`. USED mileage is never defaulted. The official dataset currently has zero mileage for every NEW record.

## Phase 2 Catalog and Recommendation Architecture

- `CatalogRepository` owns deterministic ORM queries. It defaults to active records, supports condition, brand, model, year range, price range, body type, transmission, fuel type, and maximum mileage filters, and caps each query at 100 rows.
- Sorting is explicitly allowlisted as `price_asc`, `price_desc`, `year_desc`, or `mileage_asc`; stable ID tie-breakers make repeated results deterministic. `limit` and `offset` provide bounded pagination.
- `CatalogService` provides structured search, recorded car details, fact-only comparison, and transparent recommendation ranking (newest year, then lowest recorded price, then database ID).
- `RecommendationService` creates one transaction-safe snapshot only for the exact list intended to be visible. It persists contiguous `position -> car_id` items in displayed order, supersedes the prior active snapshot, and updates the session pointer only after all items are written.
- Controlled English, Arabic, and numeric ordinals resolve only against the session's active snapshot. The database query is never rerun to infer a visible position, hidden variants consume no positions, and historical snapshots are not a fallback.
- Visible comparison resolves positions once against the same active snapshot and compares those exact recorded cars. Missing specifications remain `None`; no facts are inferred.
- `ConversationStateService` treats `ConversationSession.preferences` as current structured state. Compatible changes preserve the selected car and visible snapshot. A condition, body type, budget, year, or USED-mileage constraint that excludes persisted state invalidates the active snapshot and clears the selected car only when that selected car is incompatible.

The catalog represents recorded data, not guaranteed live showroom availability or real-time market pricing.

RAG retrieval, embeddings, LangGraph, test-drive and lead workflows, customer chat, authentication, and the admin dashboard are intentionally not implemented in Phase 2.

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
- importer validation, NEW-mileage provenance, update-in-place, rollback, and idempotency tests
- complete structured-filter, sorting, pagination, details, recommendation, and comparison tests
- exact visible-order, controlled ordinal, stale-state invalidation, selected-car, and session-isolation tests
- PostgreSQL 17 migration lifecycle tests
- PostgreSQL production-type persistence tests
- PostgreSQL empty-database import proving 7,771 / 1,930 / 5,841 and a 7,771-row unchanged second run
- PostgreSQL transaction-safe snapshot lifecycle and same-session active snapshot enforcement
- Phase 0 health-check regressions

GitHub Actions uses an ephemeral PostgreSQL 17 service. It does not use the live Supabase database and does not build application Docker images.

Live Supabase was verified on 2026-09-12 with 7,771 total active records, 1,930 NEW, 5,841 USED, zero duplicate `(source, source_id)` groups, zero NEW `NULL` mileages, and 1,930 NEW zero mileages. Representative condition, brand, body type, mileage, price-range, and ascending/descending price searches were also verified. The corrected Peugeot 2008 model-year 2026 record is present.

## Roadmap

- **Phase 2:** COMPLETE — catalog import, deterministic recommendation state, visible-list selection/comparison
- **Phase 3:** RAG + pgvector + knowledge CRUD/reindex
- **Phase 4:** LangGraph Sales Orchestrator
- **Phase 5:** Test-drive/cancellation and sales-lead business actions
- **Phase 6:** Customer Flask chat UI
- **Phase 7:** Admin dashboard
- **Phase 8:** Hardening, integration tests, live LLM/graph E2E
- **Phase 9:** Final Dockerization, README/demo polish, submission
