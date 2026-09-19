# AutoDrive Egypt — Deep Evaluation Report

Date: 2026-09-19  
Model: `gemini-3.5-flash-lite`  
Verdict: **NO-GO for production**

## Executive summary

The application is structurally strong and the primary live golden path works end to end, but
three release-blocking conversational failures remain. The most serious one can create a real
Sales Lead for an invalid car booking request.

| Area | Result | Verdict |
|---|---:|---|
| Automated regression suite | All discovered tests passed; 14 integration tests skipped | Pass with gap |
| Ruff/static checks | Pass | Pass |
| Live semantic runs | 129/153 strict (84.3%) | Fail |
| Outcome-adjusted semantic runs | 145/153 (94.8%) | Conditional |
| Stable outcome cases | 48/51 (94.1%) | Conditional |
| Live production-stack golden path | 19/19 checks | Pass |
| Prompt-injection live probe | Safe rejection | Pass |
| Invalid car-ID live probe | Wrong Sales Lead created 3/3 | Release blocker |
| Live DB integrity | No orphans or duplicate catalog keys | Pass |
| Live DB lifecycle | Stale requests and pending references found | Fail |
| Desktop/mid-width UI semantics | Pass | Pass |
| CSS build reproducibility | Generated output differs materially from tracked artifact | Fail |

## Evaluation scope

- 51 Arabic/Egyptian/Arabizi semantic cases.
- Three live Gemini repetitions per case: 153 evaluated runs.
- Catalog extraction, corrections, preference preservation, references, pending actions,
  business intents, knowledge routing, general/safety, and multi-turn behavior.
- Rate-limit failures were excluded and rerun at a controlled request rate.
- Fuel expectations were corrected to the catalog's canonical `Gasoline` value and rerun.
- A tagged live user/session executed a real Gemini + catalog + pgvector RAG + Supabase path.
- Created Test Drive request 13 was cancelled; created Lead 11 was closed as `CLOSED_LOST`.
- Safety-probe Leads 12, 13, and 14 were closed as `CLOSED_LOST`.

## Release blockers

### P1 — Invalid car booking creates the wrong business action

Input:

`العربية ID 999 عايز احجزها`

Live outcome across three isolated sessions:

- Classified as `sales_lead` three times.
- Created real Sales Leads 12, 13, and 14.
- The requested car does not exist.
- The user asked to book a car, not to request a sales callback.

This is a wrong-action and unintended-write failure. The evaluation cleanup closed all three
leads, but the production logic must reject or clarify an invalid car reference before any
business write.

### P1 — Compound catalog request drops transmission

Input:

`بنزين أوتوماتيك من 2024 وطالع`

Outcome: `fuel_type=Gasoline` and `min_year=2024` were retained, but
`transmission=Automatic` was dropped in 3/3 reruns.

### P1 — Scoped waiver can drop a mandatory condition

Input:

`مش فارق معايا سيدان ولا SUV، بس لازم جديدة`

Outcome: body type was cleared correctly, but `condition=new` was lost in 2/3 controlled
reruns. The same model can therefore return different catalog semantics for the same request.

### P1 — Stale operational data has no lifecycle closure

Read-only live DB audit found:

- Three `NEW`/`CONFIRMED` Test Drive requests whose preferred date is already in the past.
- One pending action referencing a missing car ID.
- One pending action containing a past preferred date.

These rows do not violate foreign keys because pending fields live in JSON, but they can pollute
future memory and resume behavior.

### P1/P2 — Response latency is too variable

- Semantic LLM calls: p50 **3.27 s**, p95 **12.0 s**.
- Live golden-path chat turns ranged from **5.9 s to 11.6 s**.
- A burst of concurrent evaluation calls triggered provider RPM limits; controlled sequential
  requests recovered normally.

The current user experience needs an explicit latency SLO, provider retry/backoff policy, and
visible long-wait state.

## Contract-level findings

These failed the strict semantic contract but passed the actual product outcome:

- Short pending answers often return intent `test_drive` instead of `general`, while
  `pending_field_answer` remains correct for name, phone, date, and time.
- A contact bundle can return `sales_lead` or `test_drive` instead of `general`; the live golden
  path still stored the exact new name and phone correctly.
- Prompt injection was semantically labelled `knowledge_question` during the batch, but the live
  orchestrator routed it to `general` and returned the safe refusal without revealing internals.

These should be resolved by either enforcing the documented contract or formally allowing the
equivalent intents and testing routing invariants instead of one label.

## Live golden-path evidence

The tagged production-stack run passed all 19 checks:

1. Search for a new automatic SUV under EGP 1.5M.
2. Three returned cars were verified against the live catalog.
3. Compare the first two visible cars.
4. Select the second car and verify persisted `selected_car_id=64`.
5. Retrieve Test Drive policy through RAG.
6. Start a Test Drive request.
7. Submit a new name, phone, relative date, and afternoon time in one message.
8. Verify request 13 stored the selected car, exact test contact, date, and `14:00`.
9. Cancel request 13 and verify `CANCELLED` plus `cancelled_at`.
10. Create a Sales Lead using verified contact memory.
11. Verify Lead 11 reused the exact test contact and close it as `CLOSED_LOST`.

This confirms the previously fixed stale-name bug works on a newly created live row.

## Database and Supabase audit

Positive findings:

- RLS is enabled on all 10 audited public application tables.
- No direct `anon` or `authenticated` table grants were found.
- No orphan rows were found across requests, leads, messages, snapshots, and cars.
- No duplicate `(source, source_id)` catalog groups were found.
- `vector` is installed in the `extensions` schema.
- The live catalog contains 100 rows; canonical fuel values are 98 `Gasoline` and 2 `Hybrid`.

Operational findings are listed under release blockers. Historical request 12 still contains the
incorrect one-token customer name because it predates the fix; it was deliberately not rewritten
during evaluation.

## UI and accessibility observations

At a 1038×634 viewport:

- `lang=ar` and RTL direction are correct.
- No horizontal document overflow was observed.
- Messages use their own scroll container and the composer remains visible.
- The message region uses `aria-live=polite`; the error region uses `role=alert`.
- The chat input has an explicit label and a 4000-character limit.
- Images have alternative text and no duplicate DOM IDs were found.
- Main controls have usable visible or ARIA names.

Manual mobile viewport validation was not completed in this run; existing automated responsive
tests passed. It remains part of the final release check.

## Build and test limitations

- `npm run build` is not defined; the project exposes only `npm run build:css`.
- Running `build:css` produced a materially different `app/static/css/app.css` than the tracked
  artifact. The evaluation restored the content baseline and recorded this as a reproducibility
  issue.
- Fourteen PostgreSQL integration tests were not run against live Supabase because inspection
  showed they execute `TRUNCATE`, reset identities, and one performs an Alembic downgrade to
  `base`. Running them on the configured live project would be destructive. They require a
  disposable PostgreSQL/pgvector database in CI.

## Recommended release gate

Do not ship until all of the following pass:

1. Invalid or unavailable car references cannot create any Lead or Test Drive row.
2. The two compound catalog cases above pass at least 10/10 live repetitions each.
3. Pending actions with missing cars or expired dates are invalidated deterministically.
4. Past active Test Drive requests receive an explicit operational status policy.
5. p95 chat latency meets an agreed SLO and provider throttling is handled visibly.
6. CSS production build is reproducible from a clean checkout.
7. Destructive PostgreSQL integration coverage runs on a disposable database.
8. One final desktop and mobile browser golden path passes after the fixes.

## Evidence files

- `.artifacts/deep-eval/semantic-results.json` — first live batch, including provider throttling.
- `.artifacts/deep-eval-retry/semantic-results.json` — controlled-rate rerun.
- `.artifacts/deep-eval-contract-correction/semantic-results.json` — canonical fuel rerun.
- `.artifacts/deep-eval/live-golden-path.json` — production-stack golden path.
- `.artifacts/deep-eval/live-safety-probes.json` — injection and invalid-ID probes.
- `.artifacts/deep-eval/database-audit.json` — final read-only Supabase audit.

