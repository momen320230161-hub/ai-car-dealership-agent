# AutoDrive Egypt — AI Car Dealership Agent

AI Sales & Customer Service platform for AutoDrive Egypt.

## Current Status

**Phase 0 — Foundation**

This branch contains the foundational infrastructure for the AutoDrive Egypt platform. Legacy code has been pruned in favor of a clean, production-oriented architecture.

### Technology Stack

- **Language & Runtime:** Python 3.12 (pinned via `.python-version`)
- **Package & Dependency Management:** `uv` (using `pyproject.toml` and `uv.lock`)
- **Web Framework:** Flask (Application Factory pattern)
- **ORM & Database Toolkit:** SQLAlchemy 2.x & Flask-SQLAlchemy
- **Schema & Migrations:** Flask-Migrate / Alembic
- **Database Driver:** Psycopg 3 (`psycopg[binary]`)
- **Relational Database:** External Supabase PostgreSQL (via Session Pooler)
- **WSGI Production Server:** Gunicorn
- **Containerization:** Docker & Docker Compose
- **Quality Assurance:** pytest & Ruff

---

## Local Development Setup

### 1. Prerequisites

Ensure Python 3.12 and [`uv`](https://github.com/astral-sh/uv) are installed on your system.

### 2. Dependency Installation

Synchronize locked dependencies in a virtual environment:

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
- `SECRET_KEY`: A secure random string
- `DATABASE_URL`: Supabase PostgreSQL connection string (use port `5432` Session Pooler for IPv4 compatibility)

> **Security Note:** Never commit `.env` or real database passwords to version control.

### 4. Running the Application Locally

Start the development server using `uv`:

```bash
uv run flask --app run:app run --debug --port 5000
```

Or run via Gunicorn:

```bash
uv run gunicorn --bind 0.0.0.0:5000 run:app
```

---

## Health Check Endpoints

The application provides two explicit health monitoring endpoints:

- **Process Health:** `GET /health`
  - Verifies the Flask process is alive without querying external services.
  - Returns `200 OK` with JSON: `{"status": "ok", "service": "autodrive-egypt"}`
- **Database Health:** `GET /health/db`
  - Executes a lightweight `SELECT 1` query via SQLAlchemy.
  - Returns `200 OK` with JSON: `{"status": "ok", "database": "reachable"}`
  - Returns `503 Service Unavailable` with JSON: `{"status": "error", "database": "unreachable"}` on failure without exposing internal exceptions.

---

## Testing & Code Quality

Run tests with `pytest`:

```bash
uv run pytest -q
```

Lint and format checking with `Ruff`:

```bash
uv run ruff check .
```

---

## Docker & Containerization

### Build and Run with Docker

Build the Docker image:

```bash
docker build --tag autodrive-egypt:phase0 .
```

Run the container:

```bash
docker run -d --name autodrive-web -p 5000:5000 --env-file .env autodrive-egypt:phase0
```

### Run with Docker Compose

```bash
docker compose up --build
```

---

## Project Roadmap (Future Phases)

- **Phase 1:** Relational database domain models & initial Alembic migrations
- **Phase 2:** Vehicle catalog schema, CSV dataset ingestion CLI, and inventory queries
- **Phase 3:** pgvector semantic search & RAG knowledge base
- **Phase 4:** LangGraph orchestration agent & multilingual dialogue engine
- **Phase 5:** Business actions (leads, test-drive scheduling, human escalation)
- **Phase 6:** Customer chat UI & dealership admin dashboard

