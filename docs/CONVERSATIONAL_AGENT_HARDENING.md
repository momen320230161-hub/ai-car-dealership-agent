# Conversational Agent Hardening

## Classification

- **Category:** Core Product hardening
- **Assessment impact:** Supports the required coherent-context and natural response-composition behavior without changing deterministic business-action safety.
- **Scope risk:** Low-to-medium. No schema migration is required; existing session/user/action rows are reused.

## Problems fixed

1. Catalog, RAG and business-action branches exposed deterministic renderers directly, which made customer replies feel template-driven.
2. Chat history was loaded for request understanding but was not supplied to the final response composer.
3. Customer contact data (name/phone/email) was not reusable memory after a completed action.
4. `customer_name` was written into vehicle catalog preferences and could later break strict `CatalogFilters` validation.
5. A pending business action could capture unrelated side questions instead of allowing the customer to temporarily ask about a car/policy and then resume.
6. Completed Test Drive contact data was not reused by a later Sales Lead request, including a new conversation owned by the same authenticated user.

## Implemented architecture

```text
User message
  -> LangGraph understanding/routing
  -> deterministic catalog/RAG/business services
  -> verified result + recent conversation + safe customer memory
  -> grounded conversational LLM composer
  -> deterministic validation
       -> accepted natural reply
       -> or deterministic renderer fallback
  -> persist turn
```

### State boundaries

- **Vehicle preferences:** condition, brand/model, price, body type, transmission, fuel/year/mileage filters only.
- **Customer memory:** name/phone/email derived from verified business rows and authenticated user identity; never stored in catalog filters.
- **Conversation state:** selected car, active visible recommendation snapshot, pending action.
- **Business execution:** remains deterministic for readiness, IDs, inserts, cancellation ownership and idempotency.

## Contact-memory precedence

For a new business action:

1. Explicit fields in the current message.
2. Existing fields in the same pending action.
3. Verified contact data from completed/current-session business rows.
4. For an authenticated user, verified contact data from that user's previous conversation action rows.
5. Authenticated profile display name/email where available.
6. Ask only for fields still missing.

Explicit current-message values always override remembered values.

## Pending-action interruption rule

A pending action continues automatically only when the new message:
- supplies one of its missing business fields,
- directly requests/resumes the same business action,
- or explicitly asks to continue it.

A car-details/comparison/selection question, RAG/policy question, or ordinary conversational side question may route normally while the pending action remains persisted for later resumption.

## Response-composition safety

The LLM may vary language, but not facts. It receives:
- deterministic fallback text,
- verified catalog/RAG/action result,
- bounded recent messages,
- vehicle preferences,
- selected car/pending action metadata,
- masked customer contact memory.

The deterministic fallback remains authoritative. Generated output is rejected when it introduces unsupported numeric claims or violates business-action success requirements (for example omitting the real committed request/lead ID or claiming a test-drive appointment is finally confirmed).

## Affected files/layers

- `app/agent/` — production orchestrator composition/routing and prompt.
- `app/services/` — reusable customer memory, catalog-preference cleanup, business-action memory prefill.
- `tests/unit/` — cross-action/cross-session contact reuse, preference separation, interruption routing, grounded composer fallback.
- `tests/integration/` and Phase 6 browser regression coverage were aligned with the current auth/migration/demo-dataset state.
- No database migration was required for this hardening change.

## Regression coverage

Automated coverage now includes:
- Test Drive completes with name + phone, then Sales Lead reuses both without asking again.
- Same authenticated user starts a new chat and can reuse verified contact data from an earlier action.
- Explicit new phone overrides remembered phone.
- `customer_name`/phone never remain in `ConversationSession.preferences`.
- Legacy polluted preferences are cleaned before catalog updates.
- Pending Test Drive + warranty/details question routes to RAG/catalog instead of re-asking a slot.
- Pending Test Drive + phone/date/time follows the business branch.
- Unsupported generated numeric claims are rejected in favor of deterministic fallback.
- Repeated action execution remains idempotent.
- Browser business-flow regression now proves Test Drive contact is reused by Sales Lead.

## CI evidence

Code commit `683e74c8d9e1537a686c18fc3b422d225cca5ca2` passed AutoDrive CI run `35038818512` on 16 September 2026:
- Ruff lint: PASS
- Alembic upgrade/downgrade/upgrade lifecycle: PASS
- Unit + PostgreSQL integration tests: PASS

## Evidence status

- **IMPLEMENTED:** YES
- **TESTED:** YES
- **LIVE VERIFIED:** NO — a real Gemini + browser + live Supabase conversational scenario is still required before marking the behavior live verified.
