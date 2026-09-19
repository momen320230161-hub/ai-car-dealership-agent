"""Produce a read-only integrity and security audit of the configured live database."""

from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app
from app.extensions import db

PUBLIC_TABLES = (
    "cars",
    "chat_messages",
    "conversation_sessions",
    "knowledge_chunks",
    "knowledge_documents",
    "recommendation_snapshot_items",
    "recommendation_snapshots",
    "sales_leads",
    "test_drive_requests",
    "user_profiles",
)


def _scalar(sql: str, **params: Any) -> Any:
    return db.session.execute(text(sql), params).scalar()


def _rows(sql: str, **params: Any) -> list[dict[str, Any]]:
    return [dict(row) for row in db.session.execute(text(sql), params).mappings()]


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# AutoDrive Live Database Audit",
        "",
        f"- Timestamp: `{report['timestamp']}`",
        f"- Database round-trip: **{report['database_latency_ms']:.1f} ms**",
        f"- Findings: **{len(report['findings'])}**",
        "",
        "## Findings",
        "",
    ]
    if not report["findings"]:
        lines.append("No integrity or security findings were detected by this audit.")
    else:
        for finding in report["findings"]:
            lines.append(f"- **{finding['severity']} — {finding['code']}**: {finding['detail']}")
    lines.extend(["", "## Row counts", "", "| Table | Rows |", "|---|---:|"])
    for table, count in report["row_counts"].items():
        lines.append(f"| {table} | {count} |")
    lines.extend(
        [
            "",
            "## Recent test-drive rows (PII masked)",
            "",
            "| ID | Car | Date | Time | Status | Name tokens | Phone suffix |",
            "|---:|---:|---|---|---|---:|---|",
        ]
    )
    for row in report["recent_test_drives"]:
        lines.append(
            f"| {row['id']} | {row['car_id']} | {row['preferred_date']} | "
            f"{row['preferred_time']} | {row['status']} | {row['name_tokens']} | "
            f"***{row['phone_suffix']} |"
        )
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    app = create_app()
    output_dir = Path(".artifacts/deep-eval")
    output_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    with app.app_context():
        db.session.execute(text("SET TRANSACTION READ ONLY"))
        _scalar("SELECT 1")
        latency_ms = (time.perf_counter() - started) * 1000

        row_counts = {
            table: int(_scalar(f'SELECT count(*) FROM "{table}"') or 0) for table in PUBLIC_TABLES
        }
        rls_rows = _rows(
            """
            SELECT c.relname AS table_name, c.relrowsecurity AS enabled
            FROM pg_class AS c
            JOIN pg_namespace AS n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relname = ANY(CAST(:tables AS text[]))
            ORDER BY c.relname
            """,
            tables=list(PUBLIC_TABLES),
        )
        policy_counts = _rows(
            """
            SELECT tablename AS table_name, count(*)::int AS policies
            FROM pg_policies
            WHERE schemaname = 'public' AND tablename = ANY(CAST(:tables AS text[]))
            GROUP BY tablename
            ORDER BY tablename
            """,
            tables=list(PUBLIC_TABLES),
        )
        exposed_grants = _rows(
            """
            SELECT grantee, table_name, string_agg(privilege_type, ',' ORDER BY privilege_type)
                AS privileges
            FROM information_schema.role_table_grants
            WHERE table_schema = 'public'
              AND grantee IN ('anon', 'authenticated')
              AND table_name = ANY(CAST(:tables AS text[]))
            GROUP BY grantee, table_name
            ORDER BY grantee, table_name
            """,
            tables=list(PUBLIC_TABLES),
        )
        orphan_counts = {
            "test_drive_session": int(
                _scalar(
                    """SELECT count(*) FROM test_drive_requests r LEFT JOIN
                    conversation_sessions s ON s.id=r.session_id WHERE s.id IS NULL"""
                )
                or 0
            ),
            "test_drive_car": int(
                _scalar(
                    """SELECT count(*) FROM test_drive_requests r LEFT JOIN cars c
                    ON c.id=r.car_id WHERE c.id IS NULL"""
                )
                or 0
            ),
            "lead_session": int(
                _scalar(
                    """SELECT count(*) FROM sales_leads l LEFT JOIN conversation_sessions s
                    ON s.id=l.session_id WHERE s.id IS NULL"""
                )
                or 0
            ),
            "message_session": int(
                _scalar(
                    """SELECT count(*) FROM chat_messages m LEFT JOIN conversation_sessions s
                    ON s.id=m.session_id WHERE s.id IS NULL"""
                )
                or 0
            ),
            "snapshot_item_snapshot": int(
                _scalar(
                    """SELECT count(*) FROM recommendation_snapshot_items i LEFT JOIN
                    recommendation_snapshots s ON s.id=i.snapshot_id WHERE s.id IS NULL"""
                )
                or 0
            ),
            "snapshot_item_car": int(
                _scalar(
                    """SELECT count(*) FROM recommendation_snapshot_items i LEFT JOIN cars c
                    ON c.id=i.car_id WHERE c.id IS NULL"""
                )
                or 0
            ),
        }
        duplicate_catalog_keys = int(
            _scalar(
                """
                SELECT count(*) FROM (
                    SELECT source, source_id FROM cars
                    GROUP BY source, source_id HAVING count(*) > 1
                ) AS duplicates
                """
            )
            or 0
        )
        stale_active_requests = int(
            _scalar(
                """
                SELECT count(*) FROM test_drive_requests
                WHERE status IN ('NEW', 'CONFIRMED') AND preferred_date < CURRENT_DATE
                """
            )
            or 0
        )
        pending_actions = int(
            _scalar(
                """
                SELECT count(*) FROM conversation_sessions
                WHERE jsonb_typeof(pending_action) = 'object'
                  AND pending_action <> '{}'::jsonb
                """
            )
            or 0
        )
        invalid_pending_car_refs = int(
            _scalar(
                """
                SELECT count(*)
                FROM conversation_sessions s
                LEFT JOIN cars c
                  ON c.id = (s.pending_action #>> '{fields,car_id}')::int
                WHERE jsonb_typeof(s.pending_action) = 'object'
                  AND (s.pending_action #>> '{fields,car_id}') ~ '^[0-9]+$'
                  AND c.id IS NULL
                """
            )
            or 0
        )
        expired_pending_dates = int(
            _scalar(
                """
                SELECT count(*) FROM conversation_sessions
                WHERE jsonb_typeof(pending_action) = 'object'
                  AND (pending_action #>> '{fields,preferred_date}')
                      ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
                  AND (pending_action #>> '{fields,preferred_date}')::date < CURRENT_DATE
                """
            )
            or 0
        )
        fuel_values = _rows(
            "SELECT fuel_type AS value, count(*)::int AS rows FROM cars "
            "GROUP BY fuel_type ORDER BY rows DESC NULLS LAST"
        )
        recent_test_drives = _rows(
            """
            SELECT id, car_id, preferred_date::text, preferred_time::text, status,
                   cardinality(regexp_split_to_array(trim(customer_name), '\\s+')) AS name_tokens,
                   right(regexp_replace(phone, '\\D', '', 'g'), 2) AS phone_suffix
            FROM test_drive_requests
            ORDER BY id DESC
            LIMIT 15
            """
        )
        extension = _rows(
            """
            SELECT e.extname AS name, n.nspname AS schema
            FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace
            WHERE e.extname='vector'
            """
        )
        db.session.rollback()

    findings: list[dict[str, str]] = []
    rls_by_table = {row["table_name"]: bool(row["enabled"]) for row in rls_rows}
    for table in PUBLIC_TABLES:
        if not rls_by_table.get(table, False):
            findings.append(
                {"severity": "P0", "code": "RLS_DISABLED", "detail": f"{table} has no RLS"}
            )
    for name, count in orphan_counts.items():
        if count:
            findings.append(
                {
                    "severity": "P0",
                    "code": "ORPHAN_ROWS",
                    "detail": f"{name} has {count} orphan row(s)",
                }
            )
    if duplicate_catalog_keys:
        findings.append(
            {
                "severity": "P1",
                "code": "DUPLICATE_CATALOG_KEYS",
                "detail": f"{duplicate_catalog_keys} duplicate source/source_id group(s)",
            }
        )
    if stale_active_requests:
        findings.append(
            {
                "severity": "P1",
                "code": "STALE_ACTIVE_TEST_DRIVES",
                "detail": (
                    f"{stale_active_requests} NEW/CONFIRMED request(s) have a past preferred date"
                ),
            }
        )
    if invalid_pending_car_refs:
        findings.append(
            {
                "severity": "P1",
                "code": "INVALID_PENDING_CAR_REFERENCE",
                "detail": f"{invalid_pending_car_refs} pending action(s) reference a missing car",
            }
        )
    if expired_pending_dates:
        findings.append(
            {
                "severity": "P2",
                "code": "EXPIRED_PENDING_DATE",
                "detail": f"{expired_pending_dates} pending action(s) contain a past date",
            }
        )
    if exposed_grants:
        findings.append(
            {
                "severity": "INFO",
                "code": "DATA_API_GRANTS_PRESENT",
                "detail": f"{len(exposed_grants)} anon/authenticated table grant group(s) exist",
            }
        )

    report = {
        "timestamp": datetime.now(UTC).isoformat(),
        "database_latency_ms": round(latency_ms, 1),
        "row_counts": row_counts,
        "rls": rls_rows,
        "policy_counts": policy_counts,
        "exposed_grants": exposed_grants,
        "orphan_counts": orphan_counts,
        "duplicate_catalog_keys": duplicate_catalog_keys,
        "stale_active_requests": stale_active_requests,
        "pending_actions": pending_actions,
        "invalid_pending_car_refs": invalid_pending_car_refs,
        "expired_pending_dates": expired_pending_dates,
        "fuel_values": fuel_values,
        "vector_extension": extension,
        "recent_test_drives": recent_test_drives,
        "findings": findings,
    }
    (output_dir / "database-audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    (output_dir / "database-audit.md").write_text(_markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 1 if any(item["severity"] == "P0" for item in findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
