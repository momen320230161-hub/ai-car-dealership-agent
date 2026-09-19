# AutoDrive Egypt — AI Car Dealership Agent

AutoDrive Egypt is a Flask + LangGraph AI Sales & Customer Service technical-assessment project for a car dealership. It combines a structured PostgreSQL/Supabase vehicle catalog, managed pgvector RAG, deterministic business services, persistent conversation state, real business actions, Supabase authentication, and a protected administration dashboard.

## Current Status

The core product implementation through Phase 7 is complete on the `Final-Project` branch.
The live production-stack golden path was rerun after the conversational and data-integrity
remediation on **2026-09-19** and passed **19/19** checks against real Gemini, PostgreSQL/
Supabase, pgvector RAG and real business rows.

| Phase | Scope | Status |
|---|---|---|
| **0** | Project foundation, configuration and application factory | **COMPLETE** |
| **1** | PostgreSQL schema, SQLAlchemy models and Alembic migrations | **COMPLETE** |
| **2** | Catalog import/search, persisted state, visible recommendations and ordinals | **COMPLETE / TESTED** |
| **3** | Managed RAG, Gemini embeddings and PostgreSQL pgvector retrieval | **COMPLETE / TESTED** |
| **4** | LangGraph conversational Sales Orchestrator | **COMPLETE / TESTED** |
| **5** | Real Test Drive and Sales Lead workflows, validation and idempotency | **COMPLETE / TESTED** |
| **6** | Customer website, Google/Supabase auth, owned chats and Admin Dashboard | **COMPLETE / TESTED** |
| **7** | Deep evaluation, release-blocker remediation, security and lifecycle hardening | **COMPLETE / TESTED** |
| **8** | Documentation, final demo, deployment evidence and submission closure | **IN PROGRESS** |

### Release verdict

- **Code/test quality gate:** PASS — latest disposable-PostgreSQL run: **394 passed**
  (including all **14 PostgreSQL/pgvector integration tests**); Ruff: PASS; Alembic lifecycle:
  PASS; deterministic CSS rebuild: PASS.
- **Live functional gate:** PASS — production-stack golden path: **19/19**.
- **Database safety audit:** PASS after remediation — invalid references create no business rows,
  expired pending data is invalidated, and overdue Test Drives have an explicit `EXPIRED`
  lifecycle.
- **Current release decision:** **CONDITIONAL GO**. The remaining gap is operational rather
  than missing core functionality: rerun Docker/CI from the exact submission commit, agree and
  measure a chat-latency SLO, verify provider throttling behavior, and package final demo/
  deployment evidence.

## Required Stack

- Python 3.12
- Flask application factory
- Flask Templates + HTML/CSS/JavaScript
- Supabase Auth with Google OAuth + Flask-Login
- SQLAlchemy 2.x / Flask-SQLAlchemy
- Flask-Migrate / Alembic
- PostgreSQL / Supabase
- pgvector
- LangGraph `StateGraph`
- Google Gemini for production request understanding, response composition and embeddings
- pytest + Ruff + GitHub Actions
- `uv` with committed `uv.lock`
- Node/npm with committed `package-lock.json` for deterministic CSS builds
- Gunicorn production server
- Docker production image

## Architecture

The customer-facing intelligence is one Sales Orchestrator rather than a many-agent supervisor.

```text
Browser / Customer Chat
        |
        v
Flask blueprints + thin HTTP routes
        |
        v
ConversationalSalesOrchestrator
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
        +--------------------+
        |                    |
        v                    v
PostgreSQL catalog/state   pgvector RAG
        |
        v
real TestDriveRequest / SalesLead rows
```

### Data boundaries

- **Relational DB:** cars, recorded prices/specs, users, conversation sessions, messages, dialogue state, selected car, visible recommendation snapshots, pending actions, test drives and sales leads.
- **RAG:** FAQ, financing, warranty, test-drive/dealership/customer-service policy.
- **LLM:** natural-language understanding and grounded response composition.
- **Deterministic Python:** ordinal resolution, explicit IDs, preference/state transitions, action readiness, inserts, cancellation ownership, duplicate prevention and validations.

Missing car facts are never invented.

## Structured Catalog

The authoritative import file is:

```text
data/egypt_cars_demo_100_balanced.csv
```

Current verified import summary:

- **100** curated demo records
- **50 NEW**
- **50 USED**
- no duplicate `(source, source_id)` rows in the verified import

Import or synchronize:

```bash
uv run flask --app run:app import-catalog
```

Customer-facing wording intentionally uses language such as **"حسب البيانات المتاحة في الكتالوج المسجل"**. The imported dataset is not presented as guaranteed live showroom inventory or a live market-price feed.

### Visible recommendation rule

If the customer sees positions `1..N`, ordinal references resolve against exactly those visible items. Hidden database variants never consume customer-visible positions.

```text
قارن أول اتنين  -> visible #1 vs visible #2
التانية         -> visible #2
```

The active recommendation snapshot is persisted and authoritative until superseded or invalidated. Historical lists are not silently reused unless the customer explicitly refers to an earlier list.

### Conversational state

Current structured state outranks stale history. The production conversational layer additionally preserves a small control-plane `dialogue_state`, for example `catalog_goal=recommend`, separately from SQL catalog filters. This allows a flow such as:

```text
رشحلي BMW
معايا 5 مليون
```

to continue the recommendation goal without polluting `CatalogFilters` with dialogue metadata.

Material condition/body/budget changes invalidate stale visible lists when required. A selected car persists through compatible refinements and is cleared when a new constraint makes it incompatible.

## Managed RAG

RAG uses PostgreSQL pgvector. Production embeddings are configured for 768 dimensions.

```text
EMBEDDING_PROVIDER=gemini
EMBEDDING_MODEL=gemini-embedding-2
EMBEDDING_DIMENSION=768
```

Useful commands:

```bash
uv run flask --app run:app seed-knowledge
uv run flask --app run:app reindex-knowledge --all
uv run flask --app run:app reindex-knowledge --all --failed-only
uv run flask --app run:app rag-search "الضمان مدته كام؟"
```

A document is retrievable only when its indexed version matches the current content version. Managed create/update/delete/reindex prevents stale old content from being returned as current knowledge.

Automated coverage includes embedding-provider failure, wrong dimensions, partial embeddings, chunk-persistence failure, stale indexed versions and full create/update/delete/reindex lifecycle.

## Real Business Actions

### Test Drive

A Test Drive request requires all of:

- resolved active car
- customer name
- Egyptian mobile number
- date
- time

Missing fields are collected across turns. The application never inserts early and never claims success without a committed database request ID.

Contact data from a verified prior action can be silently reused for later actions, including another conversation owned by the same authenticated user. Explicit contact data in the current message always overrides remembered data.

Ambiguous clock-only input such as `الساعة 5` is handled conservatively in the hardened conversational flow; the assistant asks for the missing daypart instead of fabricating AM/PM.

### Idempotency

Business rows use deterministic idempotency keys. Repeated execution/confirmation returns the existing request or lead instead of creating a duplicate row.

### Cancellation

Cancellation operates only on active Test Drive requests owned by the correct conversation. Multiple active requests require disambiguation instead of cancelling an arbitrary row.

### Sales Lead

Sales leads are real PostgreSQL rows with real lead IDs. Required contact data is validated before insertion. A valid selected/explicit car may be associated; the lead may also remain unbound when appropriate.

## Customer Website & Authentication

Main customer routes:

```text
GET  /                     Home
GET  /cars                 Structured catalog browsing
GET  /cars/<car_id>        Recorded car details
GET  /chat                 Authenticated AI chat
POST /api/chat/messages    Send one message to the Sales Orchestrator
POST /api/chat/session     Start a new owned conversation
GET  /api/chat/history     Current user's conversation history
POST /api/chat/switch_session/<uuid>  Switch to an owned conversation
```

Supabase Auth supplies the verified user identity; Flask-Login manages the application session. `ConversationSession.user_id` scopes history and state to the authenticated user. Cross-user conversation access is rejected.

The chat UI reloads persisted messages, selected car, pending action and the active visible recommendation list. A new chat starts a new conversation rather than reusing stale state.

The current customer experience also includes:

- responsive Arabic/RTL landing, catalog, detail and chat pages
- a customer-first recommendation preview and comparison interaction
- catalog photography resolved through Supabase Storage with safe fallbacks
- a consistent AutoDrive brand mark and favicon across customer/auth pages
- explicit loading/error states and persisted conversation switching
- POST-only, CSRF-protected logout that clears the Flask-Login remember cookie

## Admin Dashboard

The protected dashboard is available under:

```text
/admin/
```

Only authenticated users with `UserProfile.role == "admin"` may enter. Anonymous users are redirected to login and normal customer accounts receive `403`.

Promote a known authenticated user explicitly through the CLI:

```bash
uv run flask --app run:app set-user-role user@example.com admin
```

Do not create a public admin-registration path.

Dashboard capabilities:

- overview metrics
- Cars search/filter/list
- create/edit car records
- validated JPEG/PNG/WebP car-image upload to Supabase Storage, normalized to WebP
- image preview, replacement and safe cleanup of superseded admin uploads
- deactivate catalog records without pretending they are deleted from source history
- Test Drive list + controlled status transitions
- automatic overdue Test Drive expiry plus controlled `EXPIRED -> COMPLETED` correction
- Sales Lead list + controlled status transitions
- RAG knowledge list/add/edit/delete
- index status and manual reindex

RAG admin writes call the same `KnowledgeService` used by the application, so an edit increments the content version and rebuilds retrieval data rather than merely changing dashboard text.

Admin state-changing forms are protected by CSRF tokens.

## Security & Operational Hardening

The latest hardening adds:

- secrets only through environment/configuration; no credentials committed in application code
- authenticated role-based Admin access
- CSRF protection for customer chat mutation APIs
- POST-only CSRF-protected logout
- server-rendered escaping plus DOM construction with `textContent` for dynamic chat/catalog state
- controlled customer-safe error responses with no raw traceback/provider secret leakage
- request correlation through `X-Request-ID`
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: strict-origin-when-cross-origin`
- restrictive camera/microphone/geolocation `Permissions-Policy`

The CSRF token is stored in the signed Flask session and exposed to same-origin JavaScript via a separate `SameSite=Lax` cookie so `fetch()` mutation requests can send `X-CSRF-Token`.

## Health & Readiness

```text
GET /health        process liveness
GET /health/db     database connectivity
GET /health/ready  deployment readiness
```

`/health/ready` verifies database access plus critical provider configuration. It does not make paid/external LLM calls and does not return secret values.

## Local Setup

Create `.env` from `.env.example`.

Core values:

```text
SECRET_KEY=...
DATABASE_URL=...
SUPABASE_URL=...
SUPABASE_PUBLISHABLE_KEY=...
GEMINI_API_KEY=...

EMBEDDING_PROVIDER=gemini
EMBEDDING_MODEL=gemini-embedding-2
EMBEDDING_DIMENSION=768

AGENT_LLM_PROVIDER=gemini
AGENT_LLM_MODEL=gemini-3.5-flash-lite
```

Install locked dependencies:

```bash
uv sync --locked
npm ci
npm run build:css
```

Apply migrations:

```bash
uv run flask --app run:app db upgrade
```

Import catalog when setting up an empty database:

```bash
uv run flask --app run:app import-catalog
```

Seed/rebuild approved RAG knowledge:

```bash
uv run flask --app run:app seed-knowledge
```

Run locally:

```bash
uv run flask --app run:app run --debug
```

Open:

```text
http://127.0.0.1:5000/
```

For an HTTPS deployment set:

```text
SESSION_COOKIE_SECURE=1
```

## Docker

The production image runs Gunicorn and includes the Alembic migration directory.

```bash
docker build -t autodrive-egypt .
```

Migrations should run as a deployment/release step before rolling out the new web container:

```bash
uv run flask --app run:app db upgrade
```

The image itself contains `migrations/`, and CI explicitly verifies that packaging invariant.

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

GitHub Actions uses a disposable PostgreSQL 17 + pgvector service and runs:

1. locked dependency sync
2. locked frontend dependency install plus deterministic CSS rebuild verification
3. Ruff lint
4. Alembic `upgrade -> downgrade -> upgrade`
5. full unit + PostgreSQL integration suite
6. production Docker image build
7. verification that the image contains the same Alembic head as the checkout

Automated coverage includes:

- model/constraint tests
- catalog filtering, empty results and relaxation behavior
- exact visible-list ordinal resolution and comparison order
- stale/superseded snapshot behavior
- selected-car compatibility/invalidation rules
- session/user isolation
- current explicit contact overriding remembered contact
- RAG create/update/delete/reindex
- embedding/vector and persistence failures
- LangGraph branch routing
- LLM understanding/composition failures
- controlled DB/context failure
- missing Test Drive fields with no early insert
- duplicate action retry/idempotency
- cancellation ownership
- real lead creation
- Flask customer routes
- Admin access, Cars management, action-status management and RAG CRUD
- CSRF, security headers, request IDs and readiness
- DOM escaping regression for dynamic selected-car state

Latest local validation on **2026-09-19**:

```text
pytest:             394 passed
PostgreSQL/pgvector: 14 integration tests executed, 0 skipped
ruff:               all checks passed
Alembic lifecycle:  upgrade -> downgrade -> upgrade passed at head 187aa70bef52
CSS reproducibility: npm ci + build:css produced no tracked CSS diff
setup rehearsal:    catalog 100 inserted then 100 unchanged; knowledge 8 created then 8 unchanged
```

The PostgreSQL/pgvector integration group was run against a disposable PostgreSQL 17 + pgvector
container, never against the live Supabase project. When `TEST_DATABASE_URL` is absent, those
14 tests intentionally skip because they use schema lifecycle operations, truncation and
identity resets.

Reference security/release hardening CI evidence:

```text
run: 35266929975
head: 3d8477dc970453d910f539a4615b3b751f12ab3e
result: PASS
```

All lint, Alembic lifecycle, unit/PostgreSQL tests, Docker build and migration-packaging checks
passed in that historical run. The local result above covers the newer application/UI and
release-hardening work. The local Docker build completed every Dockerfile layer but Docker
Desktop failed while exporting the image because its internal filesystem became read-only, so
Docker build/migration-packaging must be reconfirmed by the final CI run from the exact submission
commit; it is not claimed as passed for the current worktree.

## Safe Migration Rule

Normal operation uses:

```bash
uv run flask --app run:app db upgrade
```

Do **not** run routine `db downgrade` verification against live Supabase. The downgrade lifecycle in CI runs only on a disposable database. A destructive live downgrade can remove derived RAG/index state.

Do not use `db.create_all()` as the production migration strategy.

## Live Demo Status & Final Demo Script

The production-stack golden path below was executed on **2026-09-19** and passed **19/19**
checks. The resulting Test Drive and Sales Lead were verified as real rows, and the evaluation
artifacts are stored under `.artifacts/deep-eval/`.

Use the same path for the final recorded/submission demo. Because the later changes are
presentation and branding changes, perform a short desktop/mobile browser smoke before recording:

1. Log in with Google.
2. `عايز عربية زيرو SUV أوتوماتيك بحد أقصى مليون ونص`.
3. Verify the visible catalog results are grounded in recorded data.
4. `قارن أول اتنين` and verify visible #1 vs #2.
5. Select the second car and verify the selection persists.
6. Ask `إيه نظام الـ test drive؟` and verify RAG-grounded policy retrieval.
7. Request a Test Drive for the selected car.
8. Supply only missing contact/date/time fields and receive a real request ID.
9. Open Admin → Test Drives and verify the same row.
10. Create a Sales Lead and verify the real lead row/ID.
11. In Admin → Knowledge, edit the relevant policy and let it reindex.
12. Ask the related RAG question again and verify retrieval reflects the updated content.
13. Refresh the chat and verify persisted context/history.
14. Start New Chat and verify session isolation.
15. Verify `/health/ready` is `ready` in the configured deployment environment.

## Remaining Required Work

Only Phase 8 closure work remains. Core product phases are complete.

### Required before final production/submission sign-off

- define the chat latency SLO and record p50/p95 against the intended production provider;
  the deep evaluation observed variable latency and provider RPM throttling
- verify the visible long-wait/retry experience under throttling and timeout conditions
- rerun the documented setup from the exact committed tree in CI/a fresh clone; the commands,
  tracked catalog path and idempotent catalog/knowledge imports passed locally on disposable DB
- run a short final desktop + mobile browser smoke after the latest UI/branding changes
- trigger and archive one final CI run from the exact submission commit
- capture final demo evidence: customer golden path, matching Admin rows, RAG edit/reindex and
  `/health/ready`
- complete repository hygiene: review `.env.example`, remove local-only artifacts, verify no
  secrets, tag the release and prepare the submission link

### Optional follow-up after submission

- production observability dashboard and alerting for latency/error rate
- richer inventory/media operations and live-stock integration
- external vehicle-market research; it is intentionally outside the required grounded core flow
