# AutoDrive Egypt — AI Car Dealership Sales & Customer Service Agent

[![AutoDrive CI](https://github.com/momen320230161-hub/ai-car-dealership-agent/actions/workflows/ci.yml/badge.svg?branch=Final-Project)](https://github.com/momen320230161-hub/ai-car-dealership-agent/actions/workflows/ci.yml)

AutoDrive Egypt is a complete **Car Dealership AI Sales & Customer Service** technical-assessment project built with **Python, Flask, PostgreSQL, SQLAlchemy, LangGraph, RAG, Gemini, pgvector, HTML/CSS/JavaScript, and a protected Flask Admin Dashboard**.

The system combines natural-language customer conversations with deterministic catalog logic, persistent conversation state, managed business knowledge, and real database-backed actions such as **Test Drive requests** and **Sales Leads**.

> The core assessment requirements are implemented and covered by automated tests and GitHub Actions. The final demo path is documented below so the evaluator can verify the required end-to-end behavior quickly.

---

## Table of Contents

1. [Business Domain](#business-domain)
2. [Assessment Deliverables Coverage](#assessment-deliverables-coverage)
3. [Core Capabilities](#core-capabilities)
4. [Technology Stack](#technology-stack)
5. [System Architecture](#system-architecture)
6. [How the LangGraph Agent Works](#how-the-langgraph-agent-works)
7. [Structured Catalog and Recommendation Rules](#structured-catalog-and-recommendation-rules)
8. [RAG and Knowledge Management](#rag-and-knowledge-management)
9. [Database Structure](#database-structure)
10. [Available Tools and Functions](#available-tools-and-functions)
11. [Business Actions](#business-actions)
12. [Flask Website and Admin Dashboard](#flask-website-and-admin-dashboard)
13. [Project Structure](#project-structure)
14. [Run Locally](#run-locally)
15. [Environment Variables](#environment-variables)
16. [Example Conversations](#example-conversations)
17. [Testing and CI](#testing-and-ci)
18. [Final Demo Script](#final-demo-script)
19. [Limitations and Assumptions](#limitations-and-assumptions)
20. [Security and Error Handling](#security-and-error-handling)

---

## Business Domain

**Selected domain:** Car Dealership.

AutoDrive Egypt is designed as an AI assistant for dealership sales and customer service. A customer can describe what they need in normal Arabic/Egyptian Arabic, refine requirements over multiple turns, compare cars that were actually shown to them, ask dealership/policy questions, and complete real business actions.

The system intentionally separates different kinds of truth:

- **Relational database:** cars, recorded prices/specifications, users, sessions, messages, recommendation snapshots, Test Drives, Sales Leads.
- **RAG knowledge:** FAQ, financing, warranty, Test Drive/dealership/customer-service policies.
- **LLM:** natural-language understanding, routing support, and response composition.
- **Deterministic Python:** IDs, visible ordinals, validations, action readiness, database writes, cancellation ownership, duplicate prevention, and stale-state invalidation.

Missing car facts are not invented.

---

## Assessment Deliverables Coverage

| Assessment requirement | AutoDrive Egypt implementation | Main location |
|---|---|---|
| Source code | Flask application with layered services and domain logic | <code>app/</code> |
| Database models | SQLAlchemy ORM models + Alembic migrations | <code>app/models/</code>, <code>migrations/</code> |
| Agent / LangGraph | Multi-node <code>StateGraph</code> Sales Orchestrator with conditional routing | <code>app/agent/</code> |
| RAG | Managed PostgreSQL/pgvector retrieval with Gemini embeddings | <code>app/rag/</code>, <code>app/services/rag_service.py</code> |
| RAG management | Admin add/update/delete/reindex with retrieval synchronization | <code>app/services/knowledge_service.py</code>, Admin Knowledge UI |
| Flask dashboard | Cars, Test Drives, Leads, Knowledge and overview metrics | <code>app/blueprints/admin/</code>, <code>app/templates/admin/</code> |
| Function/tool execution | Deterministic catalog, Test Drive, cancellation and Sales Lead services | <code>app/services/</code> |
| Requirements/dependencies | Locked Python and frontend dependencies | <code>pyproject.toml</code>, <code>uv.lock</code>, <code>package-lock.json</code> |
| README | Architecture, graph, RAG, DB, tools, setup, examples, demo and limitations | this file |
| Demo | Connected customer → RAG → business action → Admin → RAG update flow | [Final Demo Script](#final-demo-script) |

---

## Core Capabilities

### Customer-facing

- Natural-language car search and recommendation.
- Structured catalog filtering by supported recorded fields.
- Car details and recorded prices/specifications.
- Visible-list comparison.
- Deterministic ordinal references such as <code>التانية</code> and <code>أول اتنين</code>.
- Persistent selected car and recommendation context.
- Dealership/policy Q&A through managed RAG.
- Real Test Drive creation.
- Real Test Drive cancellation.
- Real Sales Lead creation.
- Persistent authenticated conversation history.
- Safe clarification when required action data is missing.

### Administrator-facing

- Dashboard overview metrics.
- Cars list/search/filter/create/edit/deactivate.
- Car image upload to Supabase Storage.
- Test Drive list and controlled status updates.
- Sales Lead list and controlled status updates.
- RAG Knowledge list/add/edit/delete/reindex.
- Optional PDF knowledge ingestion with preview and provenance.
- Role-protected Admin access.

---

## Technology Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12, Flask |
| Web UI | Flask Templates, HTML, CSS, JavaScript |
| CSS build | Tailwind CSS CLI |
| ORM | SQLAlchemy / Flask-SQLAlchemy |
| Database | PostgreSQL / Supabase |
| Migrations | Flask-Migrate / Alembic |
| Vector retrieval | PostgreSQL + pgvector |
| Agent workflow | LangGraph <code>StateGraph</code> |
| Production LLM | Google Gemini |
| Embeddings | Gemini embeddings |
| Authentication | Supabase Auth + Google OAuth + Flask-Login |
| Tests | pytest |
| Lint | Ruff |
| CI | GitHub Actions |
| Packaging | Docker + Gunicorn |
| Dependency management | uv + locked <code>uv.lock</code> |

---

## System Architecture

The project uses **one customer-facing Sales Orchestrator**, not a many-agent supervisor design. LangGraph coordinates the workflow while deterministic services remain independently testable.

~~~mermaid
flowchart TB
    Customer[Customer Browser]
    Admin[Admin Browser]

    Customer --> Flask[Flask Blueprints / HTTP Routes]
    Admin --> Flask

    Flask --> WebService[Customer / Admin Services]
    WebService --> Orchestrator[Conversational Sales Orchestrator]

    Orchestrator --> Graph[LangGraph StateGraph]

    Graph --> Catalog[Catalog + Recommendation Services]
    Graph --> RAG[RAG Service]
    Graph --> Actions[Business Action Workflow]
    Graph --> Compose[Grounded Response Composition]

    Catalog --> DB[(PostgreSQL / Supabase)]
    Actions --> DB
    WebService --> DB

    RAG --> Embed[Gemini Embeddings]
    RAG --> Vector[(KnowledgeDocument + KnowledgeChunk / pgvector)]

    Vector --> DB
~~~

### Architectural layers

~~~text
app/
├── blueprints/      HTTP routes and Flask pages
├── agent/           LangGraph, orchestration, prompts, grounding and composition
├── domain/          deterministic domain rules such as ordinal resolution
├── services/        application/business logic
├── repositories/    focused data-access abstractions
├── models/          SQLAlchemy ORM models
├── rag/             chunking, embeddings and RAG data types
├── templates/       Flask Templates
└── static/          CSS, JS and images
~~~

The web routes stay thin: they validate/authorize the request, call application services, and render or return the result. Business rules and database actions do not belong in templates.

---

## How the LangGraph Agent Works

Production runtime is built by <code>build_sales_orchestrator()</code> in <code>app/agent/factory.py</code>. The runtime uses <code>ConversationalSalesOrchestrator</code> while preserving the <code>SalesOrchestrator</code> interface and deterministic services underneath it.

### Graph workflow

~~~mermaid
flowchart TD
    START --> Guard[input_guard]
    Guard --> Context[load_context]
    Context --> Understand[understand_request]
    Understand --> Update[update_state]
    Update --> Route[route_request]

    Route -->|catalog / details / compare / selection| Catalog[catalog_node]
    Route -->|knowledge question| RAG[rag_node]
    Route -->|test drive / cancellation / lead| Business[business_gate]
    Route -->|general conversation| General[general_node]

    Catalog --> Compose[compose_response]
    RAG --> Compose
    Business --> Compose
    General --> Compose

    Compose --> Persist[persist_context]
    Persist --> END
~~~

### Main nodes

| Node | Responsibility |
|---|---|
| <code>input_guard</code> | Validate and normalize customer input. |
| <code>load_context</code> | Load session, recent messages, preferences, selected car, active visible snapshot and pending action. |
| <code>understand_request</code> | Use structured LLM understanding for intent, preferences and references. |
| <code>update_state</code> | Apply explicit preference changes and invalidate stale state when required. |
| <code>route_request</code> | Choose catalog, RAG, business-action or general branch. |
| <code>catalog_node</code> | Search, details, recommendation, visible selection and comparison. |
| <code>rag_node</code> | Retrieve managed knowledge, validate grounding and prepare verified evidence. |
| <code>business_gate</code> | Collect missing action fields, validate readiness, and execute real backend actions only when ready. |
| <code>general_node</code> | Handle safe conversational turns that do not require a catalog/RAG/business operation. |
| <code>compose_response</code> | Generate natural language only from verified catalog/RAG/action context. |
| <code>persist_context</code> | Persist messages and durable conversation state. |

### Why LangGraph is meaningful here

The graph is not a wrapper around one LLM call. Different customer intents take different conditional branches, use different services, and converge only after retrieval/action execution.

For example:

~~~text
knowledge question
    → rag_node
    → vector retrieval
    → deterministic grounding
    → knowledge composition
    → persist

Test Drive
    → business_gate
    → missing-fields check
       ├── missing → ask only for missing values
       └── ready   → create real DB request → return real request ID
~~~

### Persistent vs transient state

LangGraph state is transient for the current turn. Durable truth is stored in PostgreSQL.

Persisted conversation context includes:

- structured customer preferences,
- dialogue state,
- selected car,
- active visible recommendation snapshot,
- pending business action,
- customer and assistant messages.

This avoids process-global memory and supports session isolation.

---

## Structured Catalog and Recommendation Rules

The demo catalog is stored in:

~~~text
data/egypt_cars_demo_100_balanced.csv
~~~

Verified dataset shape:

- 100 curated demo records.
- 50 NEW.
- 50 USED.

Import/synchronize it with:

~~~bash
uv run flask --app run:app import-catalog
~~~

### Catalog boundary

The catalog is **recorded project data**, not guaranteed real-time showroom inventory.

Customer-facing responses therefore use language such as:

> حسب البيانات المتاحة عندي / في الكتالوج المسجل

The assistant does not claim that a car is physically available in a showroom today unless that fact is genuinely available from an authoritative source.

### Visible recommendation rule

Customer ordinals are resolved against the exact list the customer saw.

~~~text
Visible list:
1. Car A
2. Car B
3. Car C

"التانية"        → Car B
"قارن أول اتنين" → Car A vs Car B
~~~

Hidden database rows never consume customer-visible positions.

The active <code>RecommendationSnapshot</code> is authoritative until superseded or invalidated. Historical lists are not silently reused unless the customer explicitly refers to an earlier list.

### Preference and selection behavior

- Current structured state outranks stale history.
- Explicit new values override old values.
- A selected car persists through compatible follow-ups.
- Material condition/body/budget changes can invalidate stale recommendations and selection.
- Actual ordinal selection is deterministic; the LLM does not invent a car ID.

---

## RAG and Knowledge Management

RAG is a required core feature and is implemented with **PostgreSQL pgvector**, not external web search.

### RAG flow

~~~mermaid
flowchart LR
    Admin[Admin CRUD] --> Doc[KnowledgeDocument]
    Doc --> Chunk[Deterministic chunking]
    Chunk --> Embed[Gemini embedding]
    Embed --> Vec[KnowledgeChunk + pgvector]

    Question[Customer question] --> Retrieve[Vector retrieval]
    Vec --> Retrieve
    Retrieve --> Ground[Deterministic grounding]
    Ground --> Compose[Grounded LLM composition]
    Compose --> Answer[Customer answer]
~~~

### Managed knowledge categories

The managed seed includes business knowledge such as:

- FAQ.
- Financing.
- Warranty.
- Test Drive policy.
- Purchase/dealership policy.
- Dealership/customer-service information.

The canonical approved seed is:

~~~text
data/knowledge_seed.json
~~~

### Retrieval

<code>RAGService.retrieve()</code> embeds the query and retrieves relevant indexed chunks through pgvector.

The current orchestration also includes:

- topic-aware grounding,
- query-token support scoring,
- soft category hints,
- automatic unfiltered retry when a category hint finds no grounded result,
- concise grounded fallback if LLM composition fails,
- protection against dumping an entire raw knowledge chunk to the customer.

### CRUD synchronization

Knowledge changes go through <code>KnowledgeService</code>.

| Operation | Retrieval effect |
|---|---|
| Create | Save document → chunk → embed → persist vector chunks → mark indexed |
| Update | Increment content version → rebuild chunks/embeddings → update indexed version |
| Delete | Remove managed knowledge and its retrieval chunks |
| Reindex | Rebuild vector representation for one/all documents |

A document is treated as current retrievable knowledge only when its indexed version matches its current content version.

Useful commands:

~~~bash
uv run flask --app run:app seed-knowledge
uv run flask --app run:app reindex-knowledge --all
uv run flask --app run:app reindex-knowledge --all --failed-only
uv run flask --app run:app rag-search "إيه نظام تجربة القيادة؟"
~~~

### Admin RAG management

The Admin Dashboard supports:

- view documents,
- add,
- edit,
- delete,
- manual reindex,
- index status visibility.

This means the evaluator can change business knowledge **without editing source code**, then verify that the next customer retrieval uses the updated indexed content.

### Optional PDF ingestion

PDF ingestion is a bonus feature on top of the required managed RAG flow.

Supported flow:

~~~text
Text-based PDF
→ validation
→ pypdf text extraction
→ preview/edit
→ KnowledgeService
→ chunk
→ embed
→ pgvector
~~~

It includes duplicate SHA-256 protection and provenance metadata. OCR for scanned-image PDFs is intentionally out of scope.

---

## Database Structure

The project uses PostgreSQL with SQLAlchemy ORM and Alembic migrations.

### Core models

| Model | Purpose |
|---|---|
| <code>UserProfile</code> | Authenticated application user and role. |
| <code>Car</code> | Structured catalog vehicle record. |
| <code>ConversationSession</code> | Durable chat/session state and ownership. |
| <code>ChatMessage</code> | Persisted user/assistant message history. |
| <code>RecommendationSnapshot</code> | One customer-visible recommendation list. |
| <code>RecommendationSnapshotItem</code> | Ordered visible item linking a snapshot to a car. |
| <code>TestDriveRequest</code> | Real Test Drive business request. |
| <code>SalesLead</code> | Real sales/customer-contact lead. |
| <code>KnowledgeDocument</code> | Managed RAG source document and index lifecycle state. |
| <code>KnowledgeChunk</code> | Embedded retrievable chunk stored with pgvector. |

### Relationship view

~~~text
UserProfile
└── ConversationSession
    ├── ChatMessage
    ├── RecommendationSnapshot
    │   └── RecommendationSnapshotItem ──→ Car
    ├── TestDriveRequest ────────────────→ Car
    └── SalesLead ──────────────────────→ Car (optional)

KnowledgeDocument
└── KnowledgeChunk (pgvector embedding)
~~~

### Migrations

Schema changes are managed by Alembic/Flask-Migrate:

~~~bash
uv run flask --app run:app db upgrade
~~~

Do not use <code>db.create_all()</code> as the production migration strategy.

---

## Available Tools and Functions

The LLM does **not** directly write arbitrary database rows. LangGraph routes to deterministic Python services.

| Capability | Main implementation | Effect |
|---|---|---|
| Search catalog | <code>CatalogService.search()</code> | Structured DB query |
| Get details | <code>CatalogService.get_car_details()</code> | Recorded car facts |
| Recommend | <code>CatalogService.recommend()</code> / <code>recommend_with_relaxation()</code> | Candidate cars |
| Create visible list | <code>RecommendationService.create_visible_snapshot()</code> | Persist exact customer-visible ordering |
| Resolve ordinal | <code>RecommendationService.resolve_visible_item()</code> | Visible position → stable car ID |
| Select visible car | <code>RecommendationService.select_visible_car()</code> | Persist selected car |
| Compare visible cars | <code>RecommendationService.compare_visible()</code> | Deterministic visible-list comparison |
| Retrieve RAG | <code>RAGService.retrieve()</code> | pgvector knowledge retrieval |
| Manage knowledge | <code>KnowledgeService.create_document()</code>, <code>update_document()</code>, <code>delete_document()</code>, <code>reindex_document()</code> | RAG CRUD + index sync |
| Prepare action | <code>BusinessActionWorkflowService.prepare_action()</code> | Validate/collect required action fields |
| Execute action | <code>BusinessActionWorkflowService.execute_action()</code> | Invoke the correct business service |
| Create Test Drive | <code>TestDriveService.create_request()</code> | Insert real request and return DB row/ID |
| Cancel Test Drive | <code>TestDriveService.cancel_request()</code> | Update correct session-owned request |
| Create Sales Lead | <code>SalesLeadService.create_lead()</code> | Insert real lead and return DB row/ID |

This separation is deliberate: the model can understand language, but deterministic services own business correctness.

---

## Business Actions

### Test Drive request

A Test Drive is only ready when the system has:

- a resolved active car,
- customer name,
- phone,
- date,
- time.

If anything is missing, the assistant asks **only for the missing fields**.

No Test Drive row is inserted early.

A success response is only returned after a real database insert succeeds and a real request ID exists.

### Idempotency

Test Drives and Sales Leads use idempotency protection. Repeating the same confirmation does not create a duplicate row.

### Cancellation

Cancellation is session-scoped.

- The system never cancels another conversation's request.
- If one active request exists, it can be cancelled.
- If multiple active requests exist, the customer must disambiguate.
- Already cancelled or non-cancellable requests are handled deterministically.

### Sales Lead

A Sales Lead requires valid customer contact data and is persisted as a real PostgreSQL row with a real ID.

The selected car can be attached when appropriate, but a lead can also remain unbound if the customer requests general sales contact.

---

## Flask Website and Admin Dashboard

### Customer routes

~~~text
GET  /                              Home
GET  /cars                          Catalog
GET  /cars/<car_id>                 Car details
GET  /chat                          Authenticated AI chat
POST /api/chat/messages             Send customer message
POST /api/chat/session              Start a new conversation
GET  /api/chat/history              Load owned chat history
POST /api/chat/switch_session/<id>  Switch owned conversation
~~~

### Authentication

- Supabase Auth provides verified user identity.
- Google OAuth is supported through Supabase.
- Flask-Login manages the application login session.
- Conversation history is scoped to the authenticated user.
- Cross-user session access is rejected.

### Admin Dashboard

Admin area:

~~~text
/admin/
~~~

Only authenticated users with an Admin role may access it.

Capabilities:

- overview metrics,
- car management,
- image upload,
- Test Drive management,
- Sales Lead management,
- RAG Knowledge CRUD,
- RAG reindex,
- optional PDF ingestion.

Promote an existing authenticated user after they have logged in at least once:

~~~bash
uv run flask --app run:app set-user-role user@example.com admin
~~~

There is intentionally no public Admin registration path.

---

## Project Structure

~~~text
.
├── app/
│   ├── agent/                  LangGraph orchestration, LLM, prompts, grounding
│   ├── blueprints/             site, auth, chat, health, admin
│   ├── common/                 shared security/decorators
│   ├── domain/                 deterministic catalog/ordinal rules
│   ├── models/                 SQLAlchemy models
│   ├── rag/                    chunking, embeddings, RAG types
│   ├── repositories/           focused DB access
│   ├── services/               application/business services
│   ├── static/                 CSS, JS, images
│   └── templates/              Flask Templates
├── artifacts/                  tracked evaluation evidence
├── data/
│   ├── evals/                  evaluation cases
│   ├── egypt_cars_demo_100_balanced.csv
│   └── knowledge_seed.json
├── docs/                       evaluation/design documentation
├── frontend/                   Tailwind source
├── migrations/                 Alembic migrations
├── scripts/                    safe maintenance/evaluation utilities
├── tests/
│   ├── integration/
│   └── unit/
├── .env.example
├── .github/workflows/ci.yml
├── Dockerfile
├── docker-compose.yml
├── package.json
├── package-lock.json
├── pyproject.toml
├── run.py
└── uv.lock
~~~

---

## Run Locally

### Prerequisites

You need:

- Python 3.12.
- <code>uv</code>.
- Node.js + npm.
- PostgreSQL with pgvector, or a Supabase PostgreSQL project.
- A Supabase project for authentication.
- Google OAuth configured in Supabase if using Google login.
- A Gemini API key for production LLM and embeddings.

### 1. Clone the repository

~~~bash
git clone https://github.com/momen320230161-hub/ai-car-dealership-agent.git
cd ai-car-dealership-agent
git checkout Final-Project
~~~

### 2. Create the environment file

Linux/macOS:

~~~bash
cp .env.example .env
~~~

PowerShell:

~~~powershell
Copy-Item .env.example .env
~~~

Fill the required values described in [Environment Variables](#environment-variables).

### 3. Install locked dependencies

~~~bash
uv sync --locked
npm ci
npm run build:css
~~~

### 4. Apply database migrations

~~~bash
uv run flask --app run:app db upgrade
~~~

### 5. Import the demo catalog

~~~bash
uv run flask --app run:app import-catalog
~~~

The importer is synchronization-oriented, so rerunning it does not need to create duplicate source rows.

### 6. Seed the managed RAG knowledge

~~~bash
uv run flask --app run:app seed-knowledge
~~~

Optional full rebuild:

~~~bash
uv run flask --app run:app reindex-knowledge --all
~~~

### 7. Run the Flask application

~~~bash
uv run flask --app run:app run --debug
~~~

Open:

~~~text
http://127.0.0.1:5000/
~~~

### 8. Create an Admin user

1. Sign in once through the customer login so a <code>UserProfile</code> exists.
2. Run:

~~~bash
uv run flask --app run:app set-user-role user@example.com admin
~~~

3. Open:

~~~text
http://127.0.0.1:5000/admin/
~~~

### Health checks

~~~text
GET /health
GET /health/db
GET /health/ready
~~~

### Docker

The production image uses Gunicorn:

~~~bash
docker build -t autodrive-egypt .
~~~

Database migrations should run as a deployment/release step before starting the new application version.

---

## Environment Variables

Copy <code>.env.example</code> and configure these values.

### Required for the main production flow

| Variable | Purpose |
|---|---|
| <code>SECRET_KEY</code> | Flask session/signing key. |
| <code>DATABASE_URL</code> | PostgreSQL/Supabase connection string. |
| <code>SUPABASE_URL</code> | Supabase project URL. |
| <code>SUPABASE_PUBLISHABLE_KEY</code> | Browser-safe Supabase Auth key. |
| <code>GEMINI_API_KEY</code> | Gemini LLM and embedding access. |
| <code>EMBEDDING_PROVIDER</code> | Production value: <code>gemini</code>. |
| <code>EMBEDDING_MODEL</code> | Current configured embedding model. |
| <code>EMBEDDING_DIMENSION</code> | Current project vector dimension: <code>768</code>. |
| <code>AGENT_LLM_PROVIDER</code> | Production value: <code>gemini</code>. |
| <code>AGENT_LLM_MODEL</code> | Gemini model used by the Sales Orchestrator. |

Example:

~~~dotenv
SECRET_KEY=replace-with-a-long-random-value
DATABASE_URL=postgresql://...
SUPABASE_URL=https://<PROJECT_REF>.supabase.co
SUPABASE_PUBLISHABLE_KEY=...
GEMINI_API_KEY=...

EMBEDDING_PROVIDER=gemini
EMBEDDING_MODEL=gemini-embedding-2
EMBEDDING_DIMENSION=768

AGENT_LLM_PROVIDER=gemini
AGENT_LLM_MODEL=gemini-3.5-flash-lite
AGENT_LLM_TEMPERATURE=0.1
~~~

### Optional / tuning variables

| Variable | Purpose |
|---|---|
| <code>SESSION_COOKIE_SECURE</code> | Set to <code>1</code> for HTTPS deployment. |
| <code>SESSION_LIFETIME_DAYS</code> | Login session lifetime. |
| <code>SUPABASE_SECRET_KEY</code> | Server-side maintenance/storage tasks only; never expose to browser JS. |
| <code>CAR_IMAGE_BUCKET</code> | Supabase Storage bucket for car images. |
| <code>MAX_CAR_IMAGE_BYTES</code> | Admin image upload size limit. |
| <code>MAX_CONTENT_LENGTH</code> | Flask request body size limit. |
| <code>RAG_TOP_K</code> | Default RAG retrieval count. |
| <code>RAG_MAX_TOP_K</code> | Maximum retrieval widening. |
| <code>RAG_MIN_SCORE</code> | Optional minimum vector similarity. |
| <code>AGENT_MAX_MESSAGE_LENGTH</code> | Maximum customer message length. |
| <code>AGENT_RECENT_MESSAGE_LIMIT</code> | Recent messages loaded into agent context. |
| <code>AGENT_RECOMMENDATION_LIMIT</code> | Default visible recommendation count. |

The repository contains no real secrets; real credentials belong only in local/deployment environment configuration.

---

## Example Conversations

The exact cars and IDs depend on the current recorded catalog and database state.

### 1. Recommendation → comparison → selection

~~~text
Customer:
معايا مليون ونص وعايز SUV زيرو أوتوماتيك

Assistant:
يعرض اختيارات مناسبة حسب البيانات المتاحة في الكتالوج المسجل.

Customer:
قارن أول اتنين

Assistant:
يقارن العربية رقم 1 والعربية رقم 2 من نفس القائمة الظاهرة للعميل.

Customer:
اختار التانية

Assistant:
يثبت العربية رقم 2 من القائمة الظاهرة كالعربية المختارة.
~~~

### 2. RAG knowledge question

~~~text
Customer:
إيه البيانات الأساسية اللي المفروض تكون في عقد التمويل؟

System behavior:
knowledge_question
→ rag_node
→ pgvector retrieval
→ grounding
→ concise grounded response
~~~

The answer is composed from managed knowledge rather than invented from the model.

### 3. Test Drive action

~~~text
Customer:
عايز أحجز Test Drive للعربية دي

Assistant:
يسأل فقط عن البيانات الناقصة.

Customer:
مؤمن إسماعيل، 010XXXXXXXX، الأحد الساعة 4 العصر

Assistant:
بعد التحقق من كل الحقول، ينشئ الطلب فعليًا ثم يرجع رقم الطلب الحقيقي.
~~~

### 4. Cancellation

~~~text
Customer:
عايز ألغي تجربة القيادة

System behavior:
cancel_test_drive
→ business_gate
→ session-owned active request lookup
→ cancel the correct row or ask for disambiguation
~~~

### 5. Sales Lead

~~~text
Customer:
عايز حد من المبيعات يكلمني

Assistant:
يجمع الاسم ورقم الهاتف إذا كانا ناقصين، ثم ينشئ Sales Lead حقيقي ويرجع رقم الـLead.
~~~

---

## Testing and CI

### Local commands

~~~bash
uv run ruff check .
uv run pytest -q
~~~

Latest final-merge workstation validation before repository cleanup:

~~~text
418 passed
14 skipped
0 failed
Ruff: all checks passed
~~~

The 14 local skips are PostgreSQL/pgvector integration tests that require <code>TEST_DATABASE_URL</code>. They are intentionally not pointed at the live Supabase database because integration tests can run migrations, truncation and lifecycle operations.

### GitHub Actions

<code>.github/workflows/ci.yml</code> uses a **disposable PostgreSQL 17 + pgvector** service and validates:

1. locked Python dependency installation,
2. locked frontend dependency installation,
3. deterministic CSS rebuild,
4. Ruff,
5. Alembic upgrade → downgrade → upgrade lifecycle,
6. full unit + PostgreSQL/pgvector integration suite,
7. production Docker image build,
8. migration files and migration head inside the image.

The <code>Final-Project</code> branch is kept behind a green AutoDrive CI quality gate. The status badge at the top of this README reflects the current workflow state.

### Important regression coverage

Tests cover, among other cases:

- catalog filters and recommendation relaxation,
- visible ordinal selection and comparison,
- stale/superseded recommendation snapshots,
- preference overrides,
- selected-car invalidation,
- session/user isolation,
- conversation memory,
- RAG create/update/delete/reindex,
- embedding/vector failure handling,
- LangGraph routing,
- knowledge grounding and concise fallback,
- missing Test Drive fields with no early insert,
- duplicate prevention,
- cancellation ownership,
- Sales Lead persistence,
- Admin access and CRUD,
- CSRF/security headers,
- customer Flask routes,
- database migrations and model persistence.

A documented production-stack golden path also passed 19/19 checks after release-blocker remediation; see <code>docs/DEEP_EVALUATION_2026-09-19.md</code>. That document deliberately retains earlier failures for traceability before showing their remediation.

---

## Final Demo Script

This sequence is designed to prove the assessment requirements in one connected demo.

### Part A — Customer starts a conversation and the agent understands

1. Log in.
2. Start a new chat.
3. Send:

~~~text
عايز عربية زيرو SUV أوتوماتيك بحد أقصى مليون ونص
~~~

4. Show that returned cars come from the recorded catalog.

### Part B — Visible recommendation logic

5. Send:

~~~text
قارن أول اتنين
~~~

6. Show that the response compares visible item #1 and visible item #2.
7. Send:

~~~text
اختار التانية
~~~

8. Show that the selected car is exactly visible item #2 and remains selected.

### Part C — RAG retrieval

9. Ask:

~~~text
إيه نظام الـ Test Drive؟
~~~

10. Show the grounded dealership-policy answer.

### Part D — Real business action

11. Send:

~~~text
عايز أحجز Test Drive للعربية دي
~~~

12. Supply only the missing name/phone/date/time fields when asked.
13. Show the returned real Test Drive request ID.

### Part E — Admin verifies the backend result

14. Open <code>/admin/</code>.
15. Open **Test Drives**.
16. Show the same request row and ID created by the chat.

This proves the action was not a fake LLM confirmation.

### Part F — Admin updates RAG data

17. Open **Admin → Knowledge**.
18. Edit a suitable AutoDrive FAQ/policy entry with a small, clearly reversible demo change.
19. Save it and allow the system to reindex it.
20. Ask the related question again in chat.
21. Show that the answer now reflects the updated indexed content.
22. Restore the original demo wording after recording if the change was only for demonstration.

This directly demonstrates:

~~~text
Admin update
→ KnowledgeService
→ re-chunk/re-embed
→ pgvector update
→ new retrieval
→ updated customer answer
~~~

### Optional extra proof

- Create a Sales Lead and show the matching Admin row.
- Cancel the Test Drive and show the updated status.
- Refresh the chat and show persisted context.
- Start another chat and show session isolation.
- Open <code>/health/ready</code>.

---

## Limitations and Assumptions

- The bundled catalog is a **curated demo dataset**, not guaranteed live showroom inventory.
- Recorded prices are project catalog values, not guaranteed current market prices.
- The assistant does not invent missing car specifications.
- External vehicle/web research is intentionally disabled from the required core flow.
- RAG is limited to managed indexed knowledge available to the project.
- Gemini-dependent features require external API availability and can be affected by provider latency/rate limits.
- Google login requires correct Supabase OAuth configuration.
- PDF ingestion supports text-based PDFs; OCR for scanned documents is not included.
- Financing/warranty/dealership policy answers are limited to the managed sources loaded into RAG; unsupported provider-specific offers are not invented.
- Test Drive creation requires a resolved car, name, phone, date and time.
- The project is an assessment/demo system and does not claim a live integration with a real dealership inventory management system.

---

## Security and Error Handling

The project includes controlled boundaries for common application risks:

- secrets only through environment configuration,
- authenticated user-owned conversation sessions,
- role-based Admin authorization,
- CSRF protection for state-changing customer/Admin requests,
- safe template/DOM rendering,
- request IDs for correlation,
- controlled customer-facing errors without provider secrets or raw tracebacks,
- deterministic business validation before writes,
- idempotency for retried business actions,
- session-scoped cancellation,
- database transaction rollback on persistence failures,
- security headers such as <code>X-Content-Type-Options</code>, <code>X-Frame-Options</code>, and <code>Referrer-Policy</code>.

### Safe migration rule

Normal deployment uses:

~~~bash
uv run flask --app run:app db upgrade
~~~

Destructive migration lifecycle tests must run only on a disposable test database. Do **not** run routine Alembic downgrade verification against the live Supabase project.

---

## Assessment Summary

AutoDrive Egypt demonstrates the complete required flow:

~~~text
Customer conversation
→ LangGraph understanding/routing
→ structured catalog or RAG retrieval
→ grounded response
→ deterministic business function
→ real PostgreSQL row
→ Admin Dashboard verification
→ Admin RAG update
→ updated retrieval
~~~

The project is intentionally designed so the evaluator can inspect and explain each boundary: what belongs to the LLM, what belongs to LangGraph, what belongs to deterministic Python, what belongs to PostgreSQL, and what belongs to managed RAG.
