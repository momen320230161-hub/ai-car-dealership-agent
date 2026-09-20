"""Smoke test for the 5 Arabic demo PDFs in 'demo knowledge pdfs/'."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).parent.parent
PDF_DIR = ROOT / "demo knowledge pdfs"

# Service under test
import sys  # noqa: E402

sys.path.insert(0, str(ROOT))
os.environ.setdefault("SECRET_KEY", "smoke-test-key")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.services.knowledge_pdf_ingestion_service import (  # noqa: E402
    KnowledgePDFIngestionService,
    PDFIngestionError,
)

svc = KnowledgePDFIngestionService(
    max_bytes=10 * 1024 * 1024,
    max_pages=50,
    max_chars=100_000,
)

pdfs = sorted(PDF_DIR.glob("*.pdf"))
print(f"\nFound {len(pdfs)} PDFs in '{PDF_DIR.name}/'")
print("=" * 65)

results = []
for pdf_path in pdfs:
    try:
        with open(pdf_path, "rb") as fh:
            result = svc.extract_from_stream(fh, filename=pdf_path.name)
        status = "OK"
        results.append({
            "file": pdf_path.name,
            "status": "success",
            "pages": result.page_count,
            "chars": result.char_count,
            "sha256": result.sha256_hex[:16] + "...",
            "size_kb": result.file_size // 1024,
        })
        preview_text = result.extracted_text[:120].replace("\n", " ").strip()
        print(f"  {status}  {pdf_path.name}")
        print(f"         Pages: {result.page_count} | Chars: {result.char_count:,} | "
              f"Size: {result.file_size//1024} KB | SHA256: {result.sha256_hex[:16]}...")
        print(f"         Preview: {preview_text[:80]!r}")
    except PDFIngestionError as exc:
        status = "FAIL"
        results.append({
            "file": pdf_path.name,
            "status": "failed",
            "error": str(exc),
        })
        print(f"  {status}  {pdf_path.name}")
        print(f"         Error: {exc}")
    print()

print("=" * 65)
success_count = sum(1 for r in results if r["status"] == "success")
fail_count = sum(1 for r in results if r["status"] == "failed")
print(f"Results: {success_count}/{len(results)} succeeded, {fail_count} failed")

if fail_count > 0:
    print("\nFailed PDFs:")
    for r in results:
        if r["status"] == "failed":
            print(f"  - {r['file']}: {r['error']}")
    sys.exit(1)
