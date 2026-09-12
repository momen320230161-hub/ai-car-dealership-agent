# AutoDrive Egypt — AI Car Dealership Agent

AI Sales & Customer Service platform for AutoDrive Egypt.

## Current Status

**Phase 0 — Foundation: COMPLETE**

This branch is the clean final-project rebuild. Phase 0 establishes the runtime, dependency management, Flask application factory, SQLAlchemy/Migration wiring, health checks, tests, Docker runtime, and CI validation. No legacy application code is reused.

### Technology Stack

- **Language & Runtime:** Python 3.12 (pinned via `.python-version`)
- **Package & Dependency Management:** `uv` (`pyproject.toml` + committed `uv.lock`)
- **Web Framework:** Flask (Application Factory pattern)
- **ORM & Database Toolkit:** SQLAlchemy 2.x & Flask-SQLAlchemy
- **Schema & Migrations:** Flask-Migrate / Alembic
- **Database Driver:** Psycopg 3 (`psycopg[binary]`)
- **Relational Database:** External Supabase PostgreSQL
- **WSGI Production Server:** Gunicorn
- **Containerization:** Docker & Docker Compose
- **Quality Assurance:** pytest, Ruff, GitHub Actions

RAG, pgvector domain schema, LangGraph, business actions, customer UI, and admin dashboard are intentionally deferred to later phases.

---

## Local Development Setup

### 1. Prerequisites

Install Python 3.12 and [`uv`](https://github.com/astral-sh/uv).

### 2. Dependency Installation

```bash
uv sync --locked
```

### 3. Environment Configuration

Copy the example environment template:

```bash
# Linux / macOS
cp .env.example .env

# Windows PowerShell
Copy-Item .env.example .env
```

Configure `.env` with appropriate values:

- `FLASK_ENV`: `development` or `production`
- `FLASK_DEBUG`: `1` for local debugging
- `SECRET_KEY`: a secure random string
- `DATABASE_URL`: Supabase PostgreSQL connection string

For IPv4-only local environments, the Supabase Session Pooler on port `5432` is suitable. A long-running deployment with IPv6 support may use the direct PostgreSQL connection. Keep all secrets out of Git.

### 4. Running the Application Locally

```bash
uv run flask --app run:app run --debug --port 5000
```

Or with Gunicorn:

```bash
uv run gunicorn --bind 0.0.0.0:5000 run:app
```

---

## Health Check Endpoints

### `GET /health`

Process-level health only. It does not depend on the database.

Success:

```json
{"service": "autodrive-egypt", "status": "ok"}
```

### `GET /health/db`

Executes a lightweight `SELECT 1` through SQLAlchemy.

Success:

```json
{"database": "reachable", "status": "ok"}
```

Database failure returns HTTP `503` with a controlled response:

```json
{"database": "unreachable", "status": "error"}
```

Raw database exceptions, connection strings, and credentials are not returned to the client.

---

## Testing & Code Quality

```bash
uv run ruff check .
uv run pytest -q
```

Tests use an isolated SQLite database by default and do not modify the live Supabase project.

---

## Docker & Containerization

Build the image:

```bash
docker build --tag autodrive-egypt:phase0 .
```

Run with environment variables from `.env`:

```bash
docker run -d --name autodrive-web -p 5000:5000 --env-file .env autodrive-egypt:phase0
```

Or use Compose:

```bash
docker compose up --build
```

Supabase remains external; Phase 0 does not run a local PostgreSQL or vector-database container.

---

## Continuous Integration

`.github/workflows/phase0-ci.yml` runs on pushes and pull requests targeting `Final-Project` and verifies:

- Python 3.12 setup
- pinned `uv` installation
- `uv sync --locked --dev`
- Ruff
- pytest
- Docker image build
- Docker container startup
- `/health` container smoke test
- `/health/db` container smoke test against an isolated SQLite configuration

Third-party GitHub Actions are pinned to immutable commit SHAs.

---

## Project Roadmap (Future Phases)

- **Phase 1:** Relational database domain models & initial Alembic migrations
- **Phase 2:** Catalog, deterministic recommendation state, visible-list selection/comparison
- **Phase 3:** pgvector RAG & knowledge management CRUD
- **Phase 4:** LangGraph Sales Orchestrator
- **Phase 5:** Business actions: test drives, cancellation, sales leads
- **Phase 6:** Customer Flask chat UI
- **Phase 7:** Admin dashboard
- **Phase 8:** hardening, integration tests, and live E2E
- **Phase 9:** final README/demo/submission polish
