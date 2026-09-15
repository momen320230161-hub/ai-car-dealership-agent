# AutoDrive Egypt — AI Car Dealership Agent

AutoDrive Egypt is a Flask + LangGraph AI Sales & Customer Service technical-assessment project for a car dealership. The system combines a structured PostgreSQL vehicle catalog, managed RAG knowledge, deterministic business services, and a customer-facing premium Flask website.

## Current Status

- **Phase 0 — Foundation: COMPLETE**
- **Phase 1 — Database & ORM: COMPLETE**
- **Phase 2 — Catalog, state, visible recommendations & ordinals: COMPLETE**
- **Phase 3 — Managed RAG + PostgreSQL pgvector: COMPLETE / LIVE VERIFIED**
- **Phase 4 — LangGraph Sales Orchestrator: COMPLETE / LIVE VERIFIED**
- **Phase 5 — Test-drive & sales-lead business actions: COMPLETE / LIVE VERIFIED**
- **Phase 6 — Premium customer website & browser chat: COMPLETE / LIVE VERIFIED**
- **Phase 6.5 — Supabase Authentication & User-Owned Conversations: IMPLEMENTED / TESTED**

Phase 7 remains the next main phase: Admin Dashboard (cars, test drives, leads, overview metrics, and RAG knowledge CRUD/reindex controls).

## Required Stack

- Python 3.12
- Flask Application Factory
- Supabase Auth (Google OAuth identity provider) + Flask-Login (application session management)
- Flask Templates + HTML/CSS/JavaScript
- SQLAlchemy 2.x / Flask-SQLAlchemy
- Flask-Migrate / Alembic
- PostgreSQL / Supabase
- pgvector
- LangGraph `StateGraph`
- Google Gemini for production LLM + embeddings
- pytest + Ruff + GitHub Actions
- `uv` with committed `uv.lock`

Application Dockerization is intentionally deferred to the final packaging phase. CI may use disposable PostgreSQL/pgvector infrastructure for tests.

## Core Architecture

The customer-facing agent is one Sales Orchestrator, not a multi-agent supervisor:

```text
Browser / Customer Chat
        |
        v
Flask blueprints + thin HTTP routes
        |
        v
SalesOrchestrator.handle_message()
        |
        v
LangGraph
START
  -> input_guard
  -> load_context
  -> understand_request
  -> update_state
  -> route_request
       -> catalog_node
       -> rag_node
       -> business_gate
       -> general_node
  -> compose_response
  -> persist_context
  -> END
        |
        v
PostgreSQL / pgvector
```

Data boundaries are deliberate:

- **Relational DB:** cars, recorded prices/specs, conversation sessions, messages, visible recommendation snapshots, test drives, sales leads.
- **RAG:** FAQ, financing, warranty, test-drive/dealership policy.
- **LLM:** request understanding, routing support, conversational composition.
- **Deterministic Python:** ordinals, explicit IDs, validation, state invalidation, action readiness, inserts, cancellation ownership, duplicate prevention.

Missing car facts are never invented.

## Structured Catalog

The authoritative import file is:

```text
data/egypt_cars_final_import_ready.csv
```

Current verified dataset:

- **7,771** total records
- **1,930 NEW**
- **5,841 USED**
- no duplicate `(source, source_id)` rows in the verified import

Import or synchronize:

```bash
uv run flask --app run:app import-catalog
```

Customer-facing wording intentionally says **"حسب البيانات المتاحة في الكتالوج المسجل"**. The imported catalog is not presented as guaranteed live showroom inventory or a live market-price feed.

### Visible recommendation rule

If the customer sees positions `1..N`, ordinals resolve against exactly those displayed items. Hidden database variants do not consume positions.

Examples:

```text
قارن أول اتنين  -> visible #1 vs visible #2
التانية         -> visible #2
```

The active recommendation snapshot is persisted in PostgreSQL and is authoritative until superseded or invalidated. Historical lists are not silently reused.

## Managed RAG

RAG uses PostgreSQL pgvector. The approved seed contains eight stable dealership knowledge documents. Production embeddings use:

```text
model: gemini-embedding-2
dimension: 768
```

Useful commands:

```bash
uv run flask --app run:app seed-knowledge
uv run flask --app run:app reindex-knowledge --all
uv run flask --app run:app reindex-knowledge --all --failed-only
uv run flask --app run:app rag-search "الضمان مدته كام؟"
```

A document is retrievable only when the indexed version matches the current content version. Managed create/update/delete/reindex prevents stale old content from being returned as current knowledge.

Live regression verification confirmed supported warranty retrieval and safe rejection of unsupported insurance information after restoring the production index to 8 documents / 8 current chunks.

## Real Business Actions

### Test Drive

A booking requires all of:

- resolved active car
- customer name
- Egyptian mobile number
- date
- time

Missing fields are collected over multiple turns. The system never inserts early and never claims success without a committed database request ID.

The car can be resolved from the exact visible recommendation position, the persisted selected car, or an explicitly marked active catalog ID used by the customer website (for example `العربية ID 123`). Explicit IDs are deterministically parsed and validated before action readiness.

Idempotency keys prevent accidental duplicate inserts from repeated execution attempts.

### Cancellation

Cancellation only operates on active test-drive requests belonging to the same conversation session. One matching active request can be cancelled directly; multiple active requests require disambiguation by request ID.

### Sales Lead

Sales leads are real PostgreSQL rows with real lead IDs. Required contact data is collected before insertion. A valid explicit/selected car may be associated; otherwise a lead can remain unbound to a car.

## Phase 6 — Premium Customer Website

Phase 6 adds the real Flask browser experience on top of the existing services and graph. It is not a mocked frontend.

Customer routes:

```text
GET  /                     Home / landing page
GET  /cars                 Structured catalog browsing
GET  /cars/<car_id>        Recorded car details
GET  /chat                 Customer AI chat
POST /api/chat/messages    Send one message to the Sales Orchestrator
POST /api/chat/session     Start a new isolated browser conversation
```

### Browser/session behavior

- A signed Flask session stores the conversation UUID.
- Refreshing `/chat` reloads persisted message history from PostgreSQL.
- The HTTP route does **not** write duplicate chat messages; the graph remains responsible for turn persistence.
- A new chat creates a new conversation session instead of reusing stale state.
- Selected car, pending business action, and the active visible recommendation list are rendered from persisted state.
- Catalog recommendation cards preserve the exact visible positions used by later ordinals.
- Car-detail CTAs pass an explicitly marked catalog ID into the conversation so test-drive requests resolve the exact displayed car without fabricating or guessing a position.

### Frontend behavior

The premium RTL UI includes:

- responsive Home, Catalog, Car Details, and Chat pages
- real DB-backed catalog filters/pagination
- recommendation cards
- selected-car and pending-action status
- loading / typing state
- request timeout handling
- controlled customer-safe errors
- escaped server-rendered and JavaScript-rendered chat text

Internal traceback, provider secrets, and raw exception text are not returned to the customer UI.

## Local Setup

Create `.env` from `.env.example` and configure at least:

```text
SECRET_KEY=...
DATABASE_URL=...
GEMINI_API_KEY=...
```

Install exactly the locked dependencies:

```bash
uv sync --locked
```

Apply migrations:

```bash
uv run flask --app run:app db upgrade
```

Seed/rebuild the approved knowledge index when required:

```bash
uv run flask --app run:app seed-knowledge
```

Run locally:

```bash
uv run flask --app run:app run --debug
```

Then open:

```text
http://127.0.0.1:5000/
```

## CLI Agent Smoke

```bash
uv run flask --app run:app agent-chat "عايز SUV مستعملة"
uv run flask --app run:app agent-chat --session-id <UUID> "قارن أول اتنين"
uv run flask --app run:app agent-llm-smoke --model "gemini-3.5-flash-lite" --all-scenarios
```

## Tests & CI

Run locally:

```bash
uv run ruff check .
uv run pytest -q
```

GitHub Actions uses a disposable PostgreSQL 17 + pgvector service. The pipeline runs:

1. dependency sync
2. Ruff
3. Alembic `upgrade -> downgrade -> upgrade` against the disposable CI database
4. unit + PostgreSQL integration tests

Phase 6 regression coverage includes:

- Home, catalog filtering, and car details
- browser session creation/reuse
- separate-client session isolation
- graph invocation through the HTTP endpoint
- exact-once chat persistence and history after refresh
- visible recommendation payloads
- explicit car-ID resolution from a detail-page test-drive CTA
- no premature test-drive insert while fields are missing
- invalid/blank request handling
- controlled dependency failure without leaking traceback/provider details

The current Phase 6 implementation commit is not considered fully **LIVE VERIFIED** until the final manual browser E2E is executed against the configured live development environment.

## Safe Migration Rule

Normal operation uses only:

```bash
uv run flask --app run:app db upgrade
```

Do **not** run routine `db downgrade` verification against live Supabase. The CI migration lifecycle runs only on a disposable database. A destructive live downgrade can remove derived RAG chunks/index state; after any deliberate reset, `seed-knowledge` and retrieval verification are required before serving RAG traffic again.

Do not use `db.create_all()` as the application migration strategy.

## Phase 6 Live Browser E2E Checklist

Before marking Phase 6 closed, verify through the real browser UI:

1. Home loads and links to the DB-backed catalog.
2. Catalog filters and one Car Details page load recorded data.
3. Chat: `عايز SUV مستعملة` returns a visible recommendation list.
4. `قارن أول اتنين` compares exactly visible #1 and #2.
5. A warranty question routes through RAG.
6. Test-drive booking collects missing fields and creates one real DB row/ID.
7. Cancellation updates that same session-owned request.
8. Sales Lead creates one real DB row/ID.
9. Refresh preserves chat history and context.
10. New Chat starts an isolated conversation.
11. Unsupported insurance information is rejected safely.

## Next Required Work

After Phase 6 live browser verification, the next required phase is the Admin Dashboard:

- overview metrics
- cars management/view
- test drives
- sales leads
- RAG knowledge list/add/edit/delete/reindex
- demo proof that an admin knowledge edit changes subsequent retrieval without a code change

External vehicle web research remains optional and is not required by the core graph or demo.
