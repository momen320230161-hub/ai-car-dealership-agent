# Conversational Agent Hardening

## Classification

- **Category:** Core Product hardening
- **Assessment impact:** Supports the required coherent-context and natural response-composition behavior without changing deterministic business-action safety.
- **Scope risk:** Low-to-medium. No schema migration is required; existing session/user/action rows are reused.

## Problems being fixed

1. Catalog, RAG and business-action branches currently expose deterministic renderers directly, which makes customer replies feel template-driven.
2. Chat history is loaded for request understanding but is not supplied to the final response composer.
3. Customer contact data (name/phone/email) is not reusable memory after a completed action.
4. `customer_name` is incorrectly written into vehicle catalog preferences and can later break strict `CatalogFilters` validation.
5. A pending business action can capture unrelated side questions instead of allowing the customer to temporarily ask about a car/policy and then resume.
6. Completed Test Drive contact data is not reused by a later Sales Lead request, including a new conversation owned by the same authenticated user.

## Target architecture

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
- No database migration is required.

## Required regression coverage

- Test Drive completes with name + phone, then Sales Lead reuses both without asking again.
- Same authenticated user starts a new chat and can reuse verified contact data from an earlier action.
- Explicit new phone overrides remembered phone.
- `customer_name` never remains in `ConversationSession.preferences`.
- Legacy polluted preferences are cleaned before catalog updates.
- Pending Test Drive + warranty/details question routes to RAG/catalog instead of re-asking a slot.
- Pending Test Drive + phone/date/time follows the business branch.
- Real LLM composition can vary wording, while deterministic fixture/failure returns the safe fallback.

## Evidence status

- **IMPLEMENTED:** pending
- **TESTED:** pending
- **LIVE VERIFIED:** pending
