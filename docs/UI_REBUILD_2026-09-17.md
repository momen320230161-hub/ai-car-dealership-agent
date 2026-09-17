# Customer UI Rebuild — 2026-09-17

## Classification

- Scope: Core polish / assessment-critical UX
- Risk: Medium–High frontend change, low backend risk
- Required stack preserved: Flask Templates + HTML/CSS/JavaScript
- React SPA intentionally not introduced because the assessment requires Flask Templates

## Root cause found

The customer UI had multiple overlapping stylesheet paths and the Chat template/dynamic renderer contained Tailwind utility classes without a Tailwind build/runtime being loaded. This caused pages—especially Chat—to render as partially or almost completely unstyled HTML.

## Implemented

- Replaced the customer-facing stylesheet switching with one local design system: `app/static/css/ui-v2.css`.
- Added a dedicated semantic Chat layer: `app/static/css/chat-v2.css`.
- Rebuilt Home with a compact responsive hero, assistant preview, search command bar, process cards, featured catalog cards, intelligence/grounding explanation, and trust section.
- Rebuilt the Chat shell with semantic classes while preserving existing API IDs/data attributes and behavior.
- Rebuilt dynamic recommendation/selected-car rendering in `chat.js` using semantic classes and `textContent`; no dynamic-value `innerHTML` is used.
- Added responsive mobile navigation and Chat sidebar drawer.
- Restyled catalog cards and kept recorded-data wording/fields grounded in the database.
- The existing Car Details template now consumes the shared v2 design system.
- Restyled Admin controls, including filter forms, create/edit form grids, number/search/select controls, tables, status pills, actions, and responsive states.
- Supabase/Google login remains standalone because its existing design is already consistent and its auth behavior was not changed.

## Behavior intentionally unchanged

No changes were made to LangGraph routing, RAG retrieval, ORM/domain models, business action rules, recommendation snapshots, customer memory, authentication semantics, or Admin business services as part of this UI sprint.

## Automated verification

Customer UI foundation passed AutoDrive CI run `35270105896`.

Admin visual-alignment pass passed AutoDrive CI run `35270539619` at commit `84113944dfcca30eaac89f9f69219acba3178f0a`.

The green gate includes:

- Ruff
- Alembic upgrade → downgrade → upgrade
- full unit + PostgreSQL integration tests
- UI regression contracts
- production Docker image build
- migration packaging verification

## Status

- IMPLEMENTED: YES
- AUTOMATED TESTED: YES
- BROWSER VISUAL VERIFIED AFTER REBUILD: NO

A real browser pass is still required before calling the new presentation LIVE VERIFIED. The next visual check should cover desktop and mobile Home, Catalog, Car Details, Chat, Login, and Admin pages and should confirm there is no stale browser-cached CSS.
