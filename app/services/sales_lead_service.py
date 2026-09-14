"""Transaction-safe sales-lead business actions."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.car import Car
from app.models.conversation import ConversationSession
from app.models.lead import SalesLead


class SalesLeadServiceError(RuntimeError):
    """Controlled sales-lead business-action failure."""


class SalesLeadService:
    """Create persisted sales leads with retry-safe idempotency."""

    def __init__(self, session: Session):
        self.session = session

    def create_lead(
        self,
        *,
        session_id: uuid.UUID,
        customer_name: str,
        phone: str,
        idempotency_key: str,
        car_id: int | None = None,
        email: str | None = None,
        notes: str | None = None,
    ) -> SalesLead:
        name = self._required_text(customer_name, "customer_name", max_length=150)
        normalized_phone = self._required_text(phone, "phone", max_length=50)
        key = self._required_text(idempotency_key, "idempotency_key", max_length=128)
        normalized_email = self._optional_text(email, "email", max_length=150)
        normalized_notes = self._optional_text(notes, "notes", max_length=None)
        if car_id is not None and (
            isinstance(car_id, bool) or not isinstance(car_id, int) or car_id < 1
        ):
            raise ValueError("car_id must be a positive integer when supplied")

        try:
            existing = self._by_idempotency_key(key)
            if existing is not None:
                self._assert_same_create_payload(
                    existing,
                    session_id=session_id,
                    car_id=car_id,
                    customer_name=name,
                    phone=normalized_phone,
                    email=normalized_email,
                )
                return existing

            conversation = self.session.get(ConversationSession, session_id)
            if conversation is None:
                raise SalesLeadServiceError("Conversation session was not found")
            if car_id is not None:
                car = self.session.get(Car, car_id)
                if car is None or not car.active:
                    raise SalesLeadServiceError("Selected car is unavailable")

            lead = SalesLead(
                session_id=session_id,
                car_id=car_id,
                customer_name=name,
                phone=normalized_phone,
                email=normalized_email,
                notes=normalized_notes,
                status="NEW",
                idempotency_key=key,
            )
            self.session.add(lead)
            self.session.commit()
            return lead
        except IntegrityError as exc:
            self.session.rollback()
            existing = self._by_idempotency_key(key)
            if existing is not None:
                self._assert_same_create_payload(
                    existing,
                    session_id=session_id,
                    car_id=car_id,
                    customer_name=name,
                    phone=normalized_phone,
                    email=normalized_email,
                )
                return existing
            raise SalesLeadServiceError("Sales lead could not be created") from exc
        except (SalesLeadServiceError, ValueError):
            self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise SalesLeadServiceError("Sales lead could not be created") from exc

    def _by_idempotency_key(self, key: str) -> SalesLead | None:
        return self.session.scalar(select(SalesLead).where(SalesLead.idempotency_key == key))

    @staticmethod
    def _assert_same_create_payload(
        lead: SalesLead,
        *,
        session_id: uuid.UUID,
        car_id: int | None,
        customer_name: str,
        phone: str,
        email: str | None,
    ) -> None:
        expected = (session_id, car_id, customer_name, phone, email)
        actual = (lead.session_id, lead.car_id, lead.customer_name, lead.phone, lead.email)
        if actual != expected:
            raise SalesLeadServiceError("Idempotency key is already used by another lead")

    @staticmethod
    def _required_text(value: str, field: str, *, max_length: int) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} must not be blank")
        normalized = " ".join(value.split())
        if len(normalized) > max_length:
            raise ValueError(f"{field} is too long")
        return normalized

    @staticmethod
    def _optional_text(
        value: str | None,
        field: str,
        *,
        max_length: int | None,
    ) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError(f"{field} must be text")
        normalized = value.strip()
        if not normalized:
            return None
        if max_length is not None and len(normalized) > max_length:
            raise ValueError(f"{field} is too long")
        return normalized
