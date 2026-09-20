# AutoDrive Egypt — Knowledge Base v2

> Filename retained as `KNOWLEDGE_BASE_V1.md` for repository compatibility. The approved seed payload itself is now version `2.0`.

## Canonical baseline

The canonical approved seed is:

```text
data/knowledge_seed.json
```

Current seed metadata:

- version: `2.0`
- status: `approved_for_seed`
- language: `ar-EG`
- documents: 8

The seed mirrors the currently approved managed knowledge baseline. It is intentionally limited to supported dealership/application policy content and must not be extended with guessed showroom, financing, warranty, or operational facts.

## Included documents

1. `faq` — بيانات السيارات والأسعار في AutoDrive
2. `faq` — توافر السيارات وتأكيد السعر النهائي
3. `financing` — ما هو التمويل الاستهلاكي للسيارات في مصر؟
4. `warranty` — معلومات الضمان
5. `test drive policy` — متطلبات حجز تجربة قيادة في AutoDrive
6. `test drive policy` — إلغاء طلب تجربة القيادة
7. `purchase policy` — طلب التواصل مع فريق المبيعات في AutoDrive
8. `dealership information` — دور مساعد AutoDrive Egypt

## Managed indexing lifecycle

Knowledge content is managed through `KnowledgeService`.

The expected lifecycle is:

```text
KnowledgeDocument
  -> deterministic chunking
  -> embedding generation
  -> KnowledgeChunk persistence
  -> pgvector retrieval
```

`KnowledgeChunk` rows and vector embeddings are generated retrieval data. They must not be edited manually in Supabase during normal content maintenance.

When a managed document changes, the service is responsible for updating its content version, rebuilding the required chunks and embeddings, and updating the indexed version/status.

## Seeding

Apply migrations first and configure the production embedding provider, then run:

```bash
uv run flask --app run:app seed-knowledge
```

The seed command synchronizes `data/knowledge_seed.json` through the same `KnowledgeService` used by the application.

Expected behavior:

- missing seeded documents are created and indexed;
- changed seeded documents are updated and reindexed;
- failed or stale matching documents can be reindexed;
- unchanged current documents are not duplicated or re-embedded;
- the loader rejects a seed whose status is not `approved_for_seed`.

For the approved v2 baseline, an idempotency verification should report:

```text
seed version: 2.0
documents: 8
created: 0
updated: 0
reindexed: 0
unchanged: 8
failed: 0
```

## Admin knowledge CRUD

The Admin Knowledge interface is the supported runtime path for managed knowledge changes.

Admin CRUD must preserve the retrieval lifecycle:

```text
Add / Update / Delete
        |
        v
KnowledgeService
        |
        v
Chunk + Embed + Persist / Remove
        |
        v
Updated Retrieval
```

A successful content update is not considered complete merely because the `KnowledgeDocument` row changed. Retrieval must reflect the updated indexed version.

## PDF ingestion — Optional / Bonus

PDF ingestion is an optional/bonus capability layered on top of the existing managed RAG system.

Flow:

```text
PDF upload
  -> validation
  -> pypdf text extraction
  -> preview/edit
  -> KnowledgeService
  -> deterministic chunking
  -> embeddings
  -> pgvector retrieval
```

Important rules:

- text-based PDFs are supported; OCR is not part of the core implementation;
- the original PDF binary is not persisted in the database;
- extracted text is stored as managed knowledge content;
- PDF provenance can include filename, SHA-256, MIME type, file size, page count, extraction method, source metadata, and ingestion timestamp;
- identical PDF binaries are protected against duplicate ingestion through `source_sha256`;
- PDF documents are not automatically inserted into the 8-document seed baseline;
- demo PDFs should be imported through the Admin flow so the ingestion feature itself is demonstrated.

## Data boundaries

Use the following ownership boundaries:

- structured vehicle facts, prices and catalog specs -> relational catalog tables;
- dealership FAQ, financing, warranty and policy knowledge -> managed RAG knowledge;
- PDF-derived policy/reference text -> managed RAG knowledge after review;
- customer actions such as Test Drives and Sales Leads -> dedicated relational business tables;
- missing unsupported facts -> do not invent them.

## Business information that must not be guessed

Unless explicitly present in approved managed knowledge, do not invent:

- showroom branch addresses;
- working days or opening hours;
- official phone, email or WhatsApp details;
- financing provider offers, down payment, interest/profit rates, terms or fees;
- vehicle-specific warranty duration, coverage or exclusions;
- extra Test Drive eligibility rules such as age limit, licence requirements, deposits or insurance;
- cancellation fees or deadlines;
- reservation, deposit, payment or refund policy;
- live showroom inventory;
- live market prices.

For catalog answers, prefer wording such as:

```text
حسب البيانات المتاحة عندي / في الكتالوج المسجل
```

rather than claiming current showroom stock or a live market price.

## Verification expectations

Do not treat RAG behavior as complete from code inspection alone.

Before final submission, verification should cover:

1. approved v2 seed is idempotent;
2. all active seed documents are indexed at their current content version;
3. stored embeddings have the configured dimension;
4. Admin create/update/delete changes retrieval;
5. stale versions are not treated as current indexed knowledge;
6. PDF upload creates managed knowledge and retrievable chunks;
7. duplicate PDF ingestion is blocked;
8. one live browser scenario proves PDF upload -> indexed state -> grounded chat retrieval.

The required assessment feature remains managed RAG CRUD with updated retrieval. PDF ingestion strengthens the demo but does not replace the core RAG requirement.
