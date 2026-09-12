# AutoDrive Egypt

Car Dealership AI Sales & Customer Service technical assessment.

## Current status

**Phase 0 — Foundation**

This branch is a clean rebuild of the final assessment project. No legacy application code is reused.

### Foundation stack

- Python 3.12
- uv for Python/dependency management
- Flask application factory
- SQLAlchemy + Flask-SQLAlchemy
- Flask-Migrate / Alembic
- Psycopg 3
- Supabase PostgreSQL as the target relational database
- Docker
- pytest + Ruff

RAG, pgvector models, LangGraph, business actions, customer UI, and admin dashboard are intentionally deferred to later phases.

## Local setup

Install `uv`, then from the project root:

```bash
uv sync
```

Copy the environment template:

```bash
cp .env.example .env
```

On Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Set `SECRET_KEY` and `DATABASE_URL` in `.env`. For local IPv4 development, use the Supabase Session Pooler connection string on port `5432`. Keep all secrets out of Git.

Run the application:

```bash
uv run flask --app run:app run --debug
```

Health endpoints:

```text
GET /health
GET /health/db
```

`/health` checks the Flask process only. `/health/db` executes `SELECT 1` through SQLAlchemy and returns HTTP 503 if the database is unavailable.

## Tests and lint

```bash
uv run ruff check .
uv run pytest
```

Tests use an isolated in-memory SQLite database. A passing unit/integration test does not count as a live Supabase verification.

## Docker

Generate/sync the lockfile first:

```bash
uv sync
```

Then build and run:

```bash
docker compose up --build
```

The container exposes the Flask application on port `5000` and receives database credentials only through `.env`.

## Phase 0 Definition of Done

Phase 0 is complete only when:

- Python 3.12 is pinned.
- `uv.lock` is committed.
- `uv sync` succeeds.
- Flask app factory starts successfully.
- `/health` returns HTTP 200.
- SQLAlchemy is configured for the Supabase PostgreSQL URL.
- `/health/db` succeeds against the real Supabase database.
- Ruff and pytest pass.
- Docker image builds and the container health check passes.

Until real Supabase and container checks are executed, those items remain implemented but not live verified.
