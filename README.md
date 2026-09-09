# Car Dealership AI Sales & Customer Service Agent

Production-oriented Flask foundation for an AI sales and customer service agent used by a car dealership.

## Current phase

**Phase 2 — Database Foundation and Core Dealership Model**

The application uses Flask-SQLAlchemy and Flask-Migrate with PostgreSQL/Supabase. It includes the vehicle catalogue, customers, sales leads, conversations, messages, database constraints/indexes, Row Level Security, and an idempotent vehicle importer. It does not include AI, LangGraph, RAG, embeddings, messaging providers, or a CRUD API.

## Setup

### Create a virtual environment

Windows (PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

macOS / Linux:

```bash
python -m venv .venv
source .venv/bin/activate
```

### Install requirements

```bash
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and set values as needed:

```powershell
copy .env.example .env
```

Set `DATABASE_URL` to the Supabase **Session Pooler** URL (port `5432`). Flask derives `SQLALCHEMY_DATABASE_URI` from that one setting and selects Psycopg 3 automatically. Do not commit `.env` or put credentials in source files.

## Database migrations

Alembic/Flask-Migrate is the schema source of truth. Do not use `db.create_all()` for production schema changes.

```bash
flask --app run:app db upgrade
flask --app run:app db current
```

The Phase 2 migration creates `vehicles`, `customers`, `leads`, `conversations`, and `messages`; enables RLS on every table; and creates no permissive public policies. The existing `vector` extension remains enabled but is intentionally unused—there are no vector columns or vector indexes yet.

## Vehicle dataset import

The only production source is [`data/egypt_cars_final_english_v3.csv`](data/egypt_cars_final_english_v3.csv).

```bash
flask --app run:app import-vehicles data/egypt_cars_final_english_v3.csv
```

The command validates all rows before writing, rejects duplicate `source_id` values and Arabic in canonical `brand`/`model`, preserves nulls and audit/research fields, and uses `source_id` for atomic PostgreSQL upserts. A rerun updates existing source IDs instead of adding duplicates.

## Run the Flask application

```bash
python run.py
```

The development server listens on `http://127.0.0.1:5000`.

Health check:

```text
GET /health
```

Example response:

```json
{"status": "ok"}
```

## Run tests

```bash
.venv\Scripts\pytest -q -p no:cacheprovider --basetemp .pytest-phase2-tmp
```

Tests use an isolated in-memory SQLite database and never read or write the Supabase `DATABASE_URL`. PostgreSQL-only behavior (JSONB, RLS, and the production migration) is verified against Supabase separately.
