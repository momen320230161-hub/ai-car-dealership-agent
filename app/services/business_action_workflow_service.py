"""Pending-action readiness and execution for real dealership business actions."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from datetime import date, time
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.agent.catalog_qualification import explicit_brand_from_message, explicit_model_from_message
from app.models.car import Car
from app.models.conversation import ConversationSession
from app.services.business_action_parsing import cairo_today, parse_business_fields
from app.services.recommendation_service import RecommendationService
from app.services.sales_lead_service import SalesLeadService, SalesLeadServiceError
from app.services.test_drive_service import TestDriveService, TestDriveServiceError

BUSINESS_INTENTS = {"test_drive", "cancel_test_drive", "sales_lead"}
_TEST_DRIVE_REQUIRED = ("car_id", "customer_name", "phone", "preferred_date", "preferred_time")
_SALES_LEAD_REQUIRED = ("customer_name", "phone")


class BusinessActionWorkflowError(RuntimeError):
    """Controlled pending-action or action-execution failure."""


class BusinessActionWorkflowService:
    """Collect explicit fields, persist pending state, and execute only when ready."""

    def __init__(
        self,
        session: Session,
        *,
        today_provider: Callable[[], date] = cairo_today,
        test_drives: TestDriveService | None = None,
        sales_leads: SalesLeadService | None = None,
        recommendations: RecommendationService | None = None,
    ) -> None:
        self.session = session
        self.today_provider = today_provider
        self.test_drives = test_drives or TestDriveService(session)
        self.sales_leads = sales_leads or SalesLeadService(session)
        self.recommendations = recommendations or RecommendationService(session)

    def prepare_action(
        self,
        session_id: uuid.UUID,
        requested_intent: str,
        message: str,
        *,
        car_reference: str | int | None = None,
        field_hint: str | None = None,
    ) -> dict[str, Any]:
        """Merge only explicit current-message fields into one persisted pending action."""
        try:
            conversation = self.session.scalar(
                select(ConversationSession)
                .where(ConversationSession.id == session_id)
                .with_for_update()
            )
            if conversation is None:
                raise BusinessActionWorkflowError("Conversation session was not found")

            existing = dict(conversation.pending_action or {})
            intent = self._effective_intent(requested_intent, existing)
            same_attempt = existing.get("type") == intent
            pending = existing if same_attempt else self._new_pending(intent)
            fields = dict(pending.get("fields") or {})

            allow_bare_name = (
                intent in {"test_drive", "sales_lead"}
                and same_attempt
                and not fields.get("customer_name")
            )
            parsed = parse_business_fields(
                message,
                allow_bare_name=allow_bare_name,
                allow_single_name=(field_hint == "customer_name"),
                today=self.today_provider(),
            )
            parsed_fields = parsed.as_json_fields()
            fields.update(parsed_fields)

            if intent == "test_drive":
                self._resolve_action_car(
                    conversation,
                    fields,
                    car_reference=car_reference,
                    message=message,
                    required=True,
                )
                plan = self._prepare_required_action(
                    intent,
                    pending,
                    fields,
                    required=_TEST_DRIVE_REQUIRED,
                )
            elif intent == "sales_lead":
                self._resolve_action_car(
                    conversation,
                    fields,
                    car_reference=car_reference,
                    message=message,
                    required=False,
                )
                plan = self._prepare_required_action(
                    intent,
                    pending,
                    fields,
                    required=_SALES_LEAD_REQUIRED,
                )
            else:
                plan = self._prepare_cancellation(session_id, pending, fields)

            if plan["status"] == "no_active_request":
                conversation.pending_action = None
            else:
                conversation.pending_action = {
                    "type": intent,
                    "attempt_id": plan["attempt_id"],
                    "fields": plan["fields"],
                    **(
                        {"candidate_request_ids": plan["candidate_request_ids"]}
                        if plan.get("candidate_request_ids")
                        else {}
                    ),
                }
            self.session.commit()
            return plan
        except (BusinessActionWorkflowError, ValueError, TypeError):
            self.session.rollback()
            raise
        except (TestDriveServiceError, SalesLeadServiceError) as exc:
            self.session.rollback()
            raise BusinessActionWorkflowError(
                "Pending business action could not be prepared"
            ) from exc
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise BusinessActionWorkflowError(
                "Pending business action could not be updated"
            ) from exc

    def execute_action(
        self,
        session_id: uuid.UUID,
        plan: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Execute a ready plan and return only IDs that came from committed DB rows."""
        if plan.get("status") != "ready":
            raise ValueError("Only a ready business action may be executed")
        intent = str(plan.get("intent") or "")
        if intent not in BUSINESS_INTENTS:
            raise ValueError("Unsupported business action intent")
        attempt_id = str(plan.get("attempt_id") or "").strip()
        if not attempt_id:
            raise ValueError("Business action attempt ID is required")
        fields = dict(plan.get("fields") or {})

        try:
            if intent == "test_drive":
                request = self.test_drives.create_request(
                    session_id=session_id,
                    car_id=int(fields["car_id"]),
                    customer_name=str(fields["customer_name"]),
                    phone=str(fields["phone"]),
                    preferred_date=date.fromisoformat(str(fields["preferred_date"])),
                    preferred_time=time.fromisoformat(str(fields["preferred_time"])),
                    idempotency_key=self._idempotency_key(intent, session_id, attempt_id),
                )
                result = {
                    "status": "success",
                    "intent": intent,
                    "request_id": request.id,
                    "car_id": request.car_id,
                    "preferred_date": request.preferred_date.isoformat(),
                    "preferred_time": request.preferred_time.isoformat(timespec="minutes"),
                }
            elif intent == "sales_lead":
                car_id = int(fields["car_id"]) if fields.get("car_id") is not None else None
                lead = self.sales_leads.create_lead(
                    session_id=session_id,
                    car_id=car_id,
                    customer_name=str(fields["customer_name"]),
                    phone=str(fields["phone"]),
                    email=(str(fields["email"]) if fields.get("email") else None),
                    idempotency_key=self._idempotency_key(intent, session_id, attempt_id),
                )
                result = {
                    "status": "success",
                    "intent": intent,
                    "lead_id": lead.id,
                    "car_id": lead.car_id,
                }
            else:
                request = self.test_drives.cancel_request(
                    session_id=session_id,
                    request_id=int(fields["request_id"]),
                )
                result = {
                    "status": "success",
                    "intent": intent,
                    "request_id": request.id,
                    "car_id": request.car_id,
                    "cancelled_at": (
                        request.cancelled_at.isoformat() if request.cancelled_at else None
                    ),
                }

            self._clear_pending_if_same_attempt(session_id, attempt_id)
            return result
        except (TestDriveServiceError, SalesLeadServiceError) as exc:
            self.session.rollback()
            raise BusinessActionWorkflowError("Business action could not be executed") from exc
        except (KeyError, TypeError, ValueError) as exc:
            self.session.rollback()
            raise BusinessActionWorkflowError("Ready business action data is invalid") from exc

    @staticmethod
    def _effective_intent(requested_intent: str, pending: Mapping[str, Any]) -> str:
        if requested_intent in BUSINESS_INTENTS:
            return requested_intent
        pending_type = str(pending.get("type") or "")
        if pending_type in BUSINESS_INTENTS:
            return pending_type
        raise BusinessActionWorkflowError("No pending business action exists")

    @staticmethod
    def _new_pending(intent: str) -> dict[str, Any]:
        return {
            "type": intent,
            "attempt_id": str(uuid.uuid4()),
            "fields": {},
        }

    def _resolve_action_car(
        self,
        conversation: ConversationSession,
        fields: dict[str, Any],
        *,
        car_reference: str | int | None,
        message: str = "",
        required: bool,
    ) -> None:
        message_lower = message.casefold()
        has_explicit_ordinal = any(
            term in message_lower
            for term in (
                "الأولى",
                "الاولى",
                "الأولاني",
                "الاولاني",
                "التانية",
                "التانيه",
                "الثاني",
                "الثانية",
                "التالتة",
                "التالته",
                "الثالثة",
                "first",
                "second",
                "third",
            )
        )

        # 1. If explicit ordinal phrase is provided, attempt to resolve against active snapshot
        if car_reference is not None and (has_explicit_ordinal or fields.get("car_id") is None):
            try:
                item = self.recommendations.resolve_visible_item(conversation.id, car_reference)
                fields["car_id"] = item.car_id
                conversation.selected_car_id = item.car_id
                return
            except Exception:
                pass

        # 2. If fields already contains a valid active car_id, preserve it
        if fields.get("car_id") is not None:
            try:
                explicit_car_id = int(fields["car_id"])
                car = self.session.get(Car, explicit_car_id)
                if car is not None and car.active:
                    fields["car_id"] = car.id
                    conversation.selected_car_id = car.id
                    return
            except (TypeError, ValueError):
                pass
            fields.pop("car_id", None)

        # 3. If conversation session has a selected_car_id, use it
        if conversation.selected_car_id is not None:
            car = self.session.get(Car, conversation.selected_car_id)
            if car is not None and car.active:
                fields["car_id"] = car.id
                return
            conversation.selected_car_id = None

        # 4. Fallback to car_reference if available
        if car_reference is not None:
            try:
                item = self.recommendations.resolve_visible_item(conversation.id, car_reference)
                fields["car_id"] = item.car_id
                conversation.selected_car_id = item.car_id
                return
            except Exception:
                pass

        # 5. Check active recommendation snapshot if available.
        # Never choose the first same-brand vehicle. A textual fallback is allowed
        # only when the customer's wording uniquely identifies one visible car.
        snapshot = self.recommendations.get_active_snapshot(conversation.id)
        if snapshot and snapshot.items:
            if len(snapshot.items) == 1:
                fields["car_id"] = snapshot.items[0].car_id
                conversation.selected_car_id = snapshot.items[0].car_id
                return

            visible = [
                (item, self.session.get(Car, item.car_id))
                for item in snapshot.items
            ]
            visible = [(item, car) for item, car in visible if car is not None]

            explicit_model = explicit_model_from_message(message)
            model_matches = [
                (item, car)
                for item, car in visible
                if car.model
                and (
                    (explicit_model is not None and car.model.casefold() == explicit_model.casefold())
                    or car.model.casefold() in message_lower
                )
            ]
            if len(model_matches) == 1:
                item, _ = model_matches[0]
                fields["car_id"] = item.car_id
                conversation.selected_car_id = item.car_id
                return
            if len(model_matches) > 1:
                return

            explicit_brand = explicit_brand_from_message(message)
            brand_matches = [
                (item, car)
                for item, car in visible
                if car.brand
                and (
                    (explicit_brand is not None and car.brand.casefold() == explicit_brand.casefold())
                    or car.brand.casefold() in message_lower
                )
            ]
            if len(brand_matches) == 1:
                item, _ = brand_matches[0]
                fields["car_id"] = item.car_id
                conversation.selected_car_id = item.car_id
                return

        if not required:
            return

    @staticmethod
    def _prepare_required_action(
        intent: str,
        pending: Mapping[str, Any],
        fields: dict[str, Any],
        *,
        required: tuple[str, ...],
    ) -> dict[str, Any]:
        missing = [name for name in required if fields.get(name) in (None, "")]
        return {
            "status": "missing_fields" if missing else "ready",
            "intent": intent,
            "attempt_id": pending["attempt_id"],
            "fields": fields,
            "missing_fields": missing,
        }

    def _prepare_cancellation(
        self,
        session_id: uuid.UUID,
        pending: Mapping[str, Any],
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        attempt_id = str(pending["attempt_id"])
        if fields.get("request_id") is not None:
            return {
                "status": "ready",
                "intent": "cancel_test_drive",
                "attempt_id": attempt_id,
                "fields": fields,
                "missing_fields": [],
            }

        active = self.test_drives.active_requests_for_session(session_id)
        if not active:
            return {
                "status": "no_active_request",
                "intent": "cancel_test_drive",
                "attempt_id": attempt_id,
                "fields": fields,
                "missing_fields": [],
            }
        if len(active) == 1:
            fields["request_id"] = active[0].id
            return {
                "status": "ready",
                "intent": "cancel_test_drive",
                "attempt_id": attempt_id,
                "fields": fields,
                "missing_fields": [],
            }
        request_ids = [request.id for request in active]
        return {
            "status": "missing_fields",
            "intent": "cancel_test_drive",
            "attempt_id": attempt_id,
            "fields": fields,
            "missing_fields": ["request_id"],
            "candidate_request_ids": request_ids,
        }

    def _clear_pending_if_same_attempt(self, session_id: uuid.UUID, attempt_id: str) -> None:
        try:
            conversation = self.session.scalar(
                select(ConversationSession)
                .where(ConversationSession.id == session_id)
                .with_for_update()
            )
            if conversation is None:
                raise BusinessActionWorkflowError("Conversation session was not found")
            pending = dict(conversation.pending_action or {})
            if pending.get("attempt_id") == attempt_id:
                conversation.pending_action = None
                self.session.commit()
        except BusinessActionWorkflowError:
            self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise BusinessActionWorkflowError(
                "Completed action state could not be cleared"
            ) from exc

    @staticmethod
    def _idempotency_key(intent: str, session_id: uuid.UUID, attempt_id: str) -> str:
        return f"{intent}:{session_id}:{attempt_id}"
