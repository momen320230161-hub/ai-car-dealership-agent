# Car Dealership AI Sales & Customer Service Agent

Production-oriented Flask foundation for an AI sales and customer service agent used by a car dealership.

## Current phase

**Phase 3 — RAG / Knowledge Base Foundation**

The application now includes a production RAG foundation for unstructured dealership knowledge. It does not include LangGraph, agent routing, a chatbot, a frontend, or Phase 4 orchestration.

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

The migrations create the Phase 2 dealership tables plus `knowledge_documents` and `knowledge_chunks`. RLS is enabled on all public application tables and no permissive public policies are created.

## Vehicle dataset import

The only production source is [`data/egypt_cars_final_english_v3.csv`](data/egypt_cars_final_english_v3.csv).

```bash
flask --app run:app import-vehicles data/egypt_cars_final_english_v3.csv
```

The command validates all rows before writing, rejects duplicate `source_id` values and Arabic in canonical `brand`/`model`, preserves nulls and audit/research fields, and uses `source_id` for atomic PostgreSQL upserts. A rerun updates existing source IDs instead of adding duplicates.

## RAG knowledge architecture

Structured vehicle inventory remains in `vehicles` and is queried with SQL filters. Vehicle rows are not embedded. RAG is reserved for approved unstructured dealership material such as policies, procedures, FAQs, and purchasing guidance.

Each `knowledge_documents` row stores normalized source content, provenance, metadata, and a SHA-256 content hash. Its ordered `knowledge_chunks` rows store readable text chunks and Gemini embeddings using `gemini-embedding-2` with exactly 768 dimensions. PostgreSQL pgvector performs cosine-distance search, and the application returns `cosine_similarity = 1 - cosine_distance` along with document and source provenance.

The single HNSW index uses `vector_cosine_ops`. HNSW provides useful indexed search without the training step required by IVFFlat and is appropriate for a knowledge collection that will change over time.

Defaults are configured through `.env`:

- chunk size: 1,000 characters
- chunk overlap: 150 characters
- embedding batch size: 10
- default top-k: 5
- maximum top-k: 20

An optional similarity threshold can return no result rather than forcing unrelated knowledge. Threshold selection must be tuned against approved dealership content. Changing `EMBEDDING_DIMENSIONS` requires a schema migration and re-embedding all knowledge chunks.

Knowledge creation generates and validates all embeddings before committing the document. Content-changing updates generate a complete replacement first, then atomically delete old chunks and insert new ones. Metadata-only or normalized-content-equivalent updates do not re-embed. Document deletion cascades to its chunks.

### Knowledge CLI

```bash
flask --app run:app knowledge add --title "Approved title" --category faq --file path/to/approved.md
flask --app run:app knowledge update DOCUMENT_UUID --file path/to/revised.md
flask --app run:app knowledge list
flask --app run:app knowledge search "customer question" --top-k 5 --min-similarity 0.5
flask --app run:app knowledge delete DOCUMENT_UUID
```

Add/update commands read content from files, delete requires one explicit UUID, and search output contains concise text and provenance but never embeddings or credentials.

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
.venv\Scripts\pytest -q -p no:cacheprovider --basetemp .pytest-phase3-tmp
```

Tests use an isolated in-memory SQLite database and mocked Gemini responses; they never read or write the Supabase `DATABASE_URL`. PostgreSQL-specific vector, HNSW, RLS, cascade, and cosine behavior is verified through an explicit controlled Supabase smoke test whose synthetic rows are deleted afterward.
