"""Run a tagged production-stack golden path and leave created actions safely closed."""

from __future__ import annotations

import json
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app
from app.agent.factory import build_sales_orchestrator
from app.extensions import db
from app.models.car import Car
from app.models.conversation import ConversationSession
from app.models.lead import SalesLead
from app.models.test_drive import TestDriveRequest
from app.models.user import UserProfile
from app.services.admin_dashboard_service import AdminDashboardService


def main() -> int:
    app = create_app()
    output_dir = Path(".artifacts/deep-eval")
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report: dict[str, Any] = {
        "run_id": run_id,
        "started_at": datetime.now(UTC).isoformat(),
        "steps": [],
        "checks": [],
        "failures": [],
        "created": {},
    }

    def check(name: str, passed: bool, detail: str) -> None:
        report["checks"].append({"name": name, "passed": passed, "detail": detail})
        if not passed:
            report["failures"].append(f"{name}: {detail}")

    def turn(orchestrator, session_id: uuid.UUID, message: str):
        started = time.perf_counter()
        result = orchestrator.handle_message(session_id, message)
        report["steps"].append(
            {
                "message": message,
                "intent": result.intent,
                "route": result.route,
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                "response": result.response,
                "selected_car_id": result.selected_car_id,
                "visible_car_ids": [item.get("car_id") for item in result.visible_recommendations],
            }
        )
        return result

    request_row: TestDriveRequest | None = None
    lead_row: SalesLead | None = None
    conversation: ConversationSession | None = None
    with app.app_context():
        user = UserProfile(
            id=uuid.uuid4(),
            email=f"deep-eval+{run_id.lower()}@autodrive.invalid",
            display_name="EVAL Deep Run",
        )
        conversation = ConversationSession(user_id=user.id)
        db.session.add_all([user, conversation])
        db.session.commit()
        report["created"].update({"user_id": str(user.id), "session_id": str(conversation.id)})
        orchestrator = build_sales_orchestrator(db.session, app.config)

        try:
            search = turn(
                orchestrator,
                conversation.id,
                "عايز عربية زيرو SUV أوتوماتيك بحد أقصى مليون ونص",
            )
            check("search_route", search.route == "catalog", f"route={search.route}")
            check(
                "search_has_two_results",
                len(search.visible_recommendations) >= 2,
                f"visible={len(search.visible_recommendations)}",
            )
            for item in search.visible_recommendations:
                car = db.session.get(Car, int(item["car_id"]))
                valid = bool(
                    car
                    and car.active
                    and car.condition == "new"
                    and car.body_type == "SUV"
                    and car.transmission == "Automatic"
                    and float(car.price_egp) <= 1_500_000
                )
                check(
                    f"grounded_catalog_car_{item.get('car_id')}",
                    valid,
                    "must be active new automatic SUV under 1.5M",
                )

            compared = turn(orchestrator, conversation.id, "قارن أول اتنين")
            check("compare_route", compared.route == "catalog", f"route={compared.route}")

            selected = turn(orchestrator, conversation.id, "اختار التانية")
            db.session.expire_all()
            persisted_conversation = db.session.get(ConversationSession, conversation.id)
            selected_id = persisted_conversation.selected_car_id if persisted_conversation else None
            expected_second = int(search.visible_recommendations[1]["car_id"])
            check(
                "selection_persisted",
                selected_id == expected_second,
                f"selected={selected_id}, expected={expected_second}",
            )
            check(
                "selection_response_consistent",
                selected.selected_car_id == expected_second,
                f"response selected={selected.selected_car_id}",
            )

            policy = turn(orchestrator, conversation.id, "إيه نظام التست درايف؟")
            check("policy_rag_route", policy.route == "rag", f"route={policy.route}")
            check(
                "policy_not_false_confirmation",
                "اتأكد" not in policy.response and "مؤكد" not in policy.response,
                policy.response,
            )

            started = turn(orchestrator, conversation.id, "عايز احجز تست درايف")
            check(
                "booking_pending",
                started.route == "business_gate",
                f"route={started.route}",
            )

            completed = turn(
                orchestrator,
                conversation.id,
                "اسمي EVAL Deep Run ورقمي 01000000001 بكره الساعة 2 العصر",
            )
            request_row = db.session.scalar(
                select(TestDriveRequest)
                .where(TestDriveRequest.session_id == conversation.id)
                .order_by(TestDriveRequest.id.desc())
            )
            check("booking_row_created", request_row is not None, completed.response)
            if request_row is not None:
                report["created"]["test_drive_request_id"] = request_row.id
                report["created"]["test_drive_phone_suffix"] = request_row.phone[-2:]
                check(
                    "booking_car_matches_selection",
                    request_row.car_id == expected_second,
                    f"car={request_row.car_id}, selected={expected_second}",
                )
                check(
                    "booking_contact_exact",
                    request_row.customer_name == "EVAL Deep Run"
                    and request_row.phone == "01000000001",
                    f"name={request_row.customer_name!r}, phone_suffix={request_row.phone[-2:]}",
                )
                check(
                    "booking_time_exact",
                    request_row.preferred_time.isoformat(timespec="minutes") == "14:00",
                    request_row.preferred_time.isoformat(),
                )
                cancelled = turn(
                    orchestrator,
                    conversation.id,
                    f"عايز ألغي طلب تجربة القيادة رقم {request_row.id}",
                )
                db.session.refresh(request_row)
                check(
                    "booking_cancelled",
                    request_row.status == "CANCELLED" and request_row.cancelled_at is not None,
                    f"status={request_row.status}, response={cancelled.response}",
                )

            lead_result = turn(
                orchestrator,
                conversation.id,
                "عايز حد من المبيعات يكلمني",
            )
            lead_row = db.session.scalar(
                select(SalesLead)
                .where(SalesLead.session_id == conversation.id)
                .order_by(SalesLead.id.desc())
            )
            check("sales_lead_created", lead_row is not None, lead_result.response)
            if lead_row is not None:
                report["created"]["sales_lead_id"] = lead_row.id
                check(
                    "sales_lead_reused_verified_contact",
                    lead_row.customer_name == "EVAL Deep Run" and lead_row.phone == "01000000001",
                    f"name={lead_row.customer_name!r}, phone_suffix={lead_row.phone[-2:]}",
                )
                AdminDashboardService(db.session).update_sales_lead_status(
                    lead_row.id, "CLOSED_LOST"
                )
                db.session.refresh(lead_row)
                check(
                    "eval_lead_closed",
                    lead_row.status == "CLOSED_LOST",
                    f"status={lead_row.status}",
                )
        except Exception as exc:
            report["failures"].append(f"{type(exc).__name__}: {exc}")
        finally:
            if request_row is not None and request_row.status != "CANCELLED":
                AdminDashboardService(db.session).update_test_drive_status(
                    request_row.id, "CANCELLED"
                )
            if lead_row is not None and lead_row.status != "CLOSED_LOST":
                AdminDashboardService(db.session).update_sales_lead_status(
                    lead_row.id, "CLOSED_LOST"
                )
            if conversation is not None:
                conversation.status = "closed"
                db.session.commit()

    report["finished_at"] = datetime.now(UTC).isoformat()
    report["passed"] = not report["failures"]
    output = output_dir / "live-golden-path.json"
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    print(f"Report: {output}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
