# AutoDrive Egypt — Knowledge Base v1

Status: approved baseline content in `data/knowledge_seed.json`; live Gemini seeding is a separate runtime step.

This baseline intentionally contains only information supported by the current AutoDrive project requirements. It does not invent dealership facts that have not been approved.

## Included documents

1. `faq` — بيانات السيارات والأسعار
2. `faq` — توافر السيارات وتأكيد السعر النهائي
3. `financing` — معلومات التمويل
4. `warranty` — معلومات الضمان
5. `test drive policy` — متطلبات حجز تجربة قيادة
6. `test drive policy` — إلغاء طلب تجربة القيادة
7. `purchase policy` — طلب التواصل مع فريق المبيعات
8. `dealership information` — دور مساعد AutoDrive Egypt

## Seeding

Apply migrations first, configure the production Gemini embedding provider, then run:

```bash
uv run flask --app run:app seed-knowledge
```

The command synchronizes the approved JSON file through `KnowledgeService`, so documents are chunked, embedded, and stored in pgvector using the same managed indexing lifecycle as admin CRUD. Re-running the same seed is idempotent: unchanged current documents are not duplicated or re-embedded. Changed content is updated and reindexed, and failed/outdated matching documents are reindexed.

The seed loader refuses files whose status is not `approved_for_seed`.

## Business information still not approved

The following details are intentionally absent until AutoDrive approves them:

- branch address or addresses
- working days and hours
- official phone, email, or WhatsApp
- financing providers, down payment, interest/profit rates, terms, or fees
- warranty duration, coverage, and exclusions for new or used cars
- additional test-drive eligibility rules such as driving licence, age limit, booking lead time, deposit, or insurance
- test-drive cancellation deadline or cancellation fees
- vehicle reservation/deposit/payment/refund policy

Until those details are approved and added through managed knowledge CRUD, the assistant must not invent them.

## Demo relevance

This baseline is enough to demonstrate that RAG retrieves dealership/application policy knowledge and that admin CRUD can later change an answer without code edits. Before final submission, the knowledge base should be expanded with any real AutoDrive business details that are approved for the demo.
