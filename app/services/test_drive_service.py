"""Transaction-safe test-drive business actions."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.car import Car
from app.models.conversation import ConversationSession
from app.models.test_drive import TestDriveRequest


class TestDriveServiceError(RuntimeError):
    """Controlled test-drive business-action failure."""


class TestDriveNotFoundError(TestDriveServiceError):
    """No cancellable request exists inside the current conversation session."""


class AmbiguousTestDriveError(TestDriveServiceError):
    """More than one cancellable request exists and the customer must choose one."""

    def __init__(self, request_ids: list[int]):
        self.request_ids = request_ids
        super().__init__("More than one active test-drive request requires an explicit request ID")


class TestDriveService:
    """Create and cancel persisted test-drive requests without LLM-side writes."""

    __test__ = False

    ACTIVE_STATUSES = ("NEW", "CONFIRMED")

    def __init__(self, session: Session):
        self.session = session

    def create_request(
        self,
        *,
        session_id: uuid.UUID,
        car_id: int,
        customer_name: str,
        phone: str,
        preferred_date: date,
        preferred_time: time,
        idempotency_key: str,
        notes: str | None = None,
    ) -> TestDriveRequest:
        """Create exactly one request for one idempotency key.

        A retry using the same key returns the original row. The caller owns the
        action-attempt key so a genuinely new booking attempt can use a new key.
        """
        name = self._required_text(customer_name, "customer_name", max_length=150)
        normalized_phone = self._required_text(phone, "phone", max_length=50)
        key = self._required_text(idempotency_key, "idempotency_key", max_length=128)
        normalized_notes = self._optional_text(notes, max_length=None)
        if not isinstance(preferred_date, date) or isinstance(preferred_date, datetime):
            raise ValueError("preferred_date must be a date")
        if not isinstance(preferred_time, time):
            raise ValueError("preferred_time must be a time")
        if isinstance(car_id, bool) or not isinstance(car_id, int) or car_id < 1:
            raise ValueError("car_id must be a positive integer")

        try:
            existing = self._by_idempotency_key(key)
            if existing is not None:
                self._assert_same_create_payload(
                    existing,
                    session_id=session_id,
                    car_id=car_id,
                    customer_name=name,
                    phone=normalized_phone,
                    preferred_date=preferred_date,
                    preferred_time=preferred_time,
                )
                return existing

            conversation = self.session.get(ConversationSession, session_id)
            if conversation is None:
                raise TestDriveServiceError("Conversation session was not found")
            car = self.session.get(Car, car_id)
            if car is None or not car.active:
                raise TestDriveServiceError("Selected car is unavailable")

            request = TestDriveRequest(
                session_id=session_id,
                car_id=car_id,
                customer_name=name,
                phone=normalized_phone,
                preferred_date=preferred_date,
                preferred_time=preferred_time,
                status="NEW",
                notes=normalized_notes,
                idempotency_key=key,
            )
            self.session.add(request)
            self.session.commit()
            return request
        except IntegrityError as exc:
            # Protect against concurrent retries racing on the unique key.
            self.session.rollback()
            existing = self._by_idempotency_key(key)
            if existing is not None:
                self._assert_same_create_payload(
                    existing,
                    session_id=session_id,
                    car_id=car_id,
                    customer_name=name,
                    phone=normalized_phone,
                    preferred_date=preferred_date,
                    preferred_time=preferred_time,
                )
                return existing
            raise TestDriveServiceError("Test-drive request could not be created") from exc
        except (TestDriveServiceError, ValueError):
            self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise TestDriveServiceError("Test-drive request could not be created") from exc

    def active_requests_for_session(self, session_id: uuid.UUID) -> list[TestDriveRequest]:
        """Return only cancellable requests owned by this conversation session."""
        try:
            return list(
                self.session.scalars(
                    select(TestDriveRequest)
                    .where(
                        TestDriveRequest.session_id == session_id,
                        TestDriveRequest.status.in_(self.ACTIVE_STATUSES),
                    )
                    .order_by(TestDriveRequest.created_at.desc(), TestDriveRequest.id.desc())
                )
            )
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise TestDriveServiceError("Test-drive requests could not be loaded") from exc

    def cancel_request(
        self,
        *,
        session_id: uuid.UUID,
        request_id: int | None = None,
    ) -> TestDriveRequest:
        """Cancel one session-owned request and never cross session boundaries."""
        try:
            request: TestDriveRequest | None
            if request_id is not None:
                invalid_id = (
                    isinstance(request_id, bool)
                    or not isinstance(request_id, int)
                    or request_id < 1
                )
                if invalid_id:
                    raise ValueError("request_id must be a positive integer")
                request = self.session.scalar(
                    select(TestDriveRequest)
                    .where(
                        TestDriveRequest.id == request_id,
                        TestDriveRequest.session_id == session_id,
                    )
                    .with_for_update()
                )
                if request is None:
                    raise TestDriveNotFoundError(
                        "Test-drive request was not found for this session"
                    )
                if request.status == "CANCELLED":
                    return request
                if request.status not in self.ACTIVE_STATUSES:
                    raise TestDriveServiceError("Test-drive request is no longer cancellable")
            else:
                active = list(
                    self.session.scalars(
                        select(TestDriveRequest)
                        .where(
                            TestDriveRequest.session_id == session_id,
                            TestDriveRequest.status.in_(self.ACTIVE_STATUSES),
                        )
                        .order_by(TestDriveRequest.created_at.desc(), TestDriveRequest.id.desc())
                        .with_for_update()
                    )
                )
                if not active:
                    raise TestDriveNotFoundError(
                        "No active test-drive request exists for this session"
                    )
                if len(active) > 1:
                    raise AmbiguousTestDriveError([item.id for item in active])
                request = active[0]

            request.status = "CANCELLED"
            request.cancelled_at = datetime.now(UTC)
            self.session.commit()
            return request
        except (TestDriveServiceError, ValueError):
            self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise TestDriveServiceError("Test-drive request could not be cancelled") from exc

    def _by_idempotency_key(self, key: str) -> TestDriveRequest | None:
        return self.session.scalar(
            select(TestDriveRequest).where(TestDriveRequest.idempotency_key == key)
        )

    @staticmethod
    def _assert_same_create_payload(
        request: TestDriveRequest,
        *,
        session_id: uuid.UUID,
        car_id: int,
        customer_name: str,
        phone: str,
        preferred_date: date,
        preferred_time: time,
    ) -> None:
        expected = (
            session_id,
            car_id,
            customer_name,
            phone,
            preferred_date,
            preferred_time,
        )
        actual = (
            request.session_id,
            request.car_id,
            request.customer_name,
            request.phone,
            request.preferred_date,
            request.preferred_time,
        )
        if actual != expected:
            raise TestDriveServiceError("Idempotency key is already used by another request")

    @staticmethod
    def _required_text(value: str, field: str, *, max_length: int) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} must not be blank")
        normalized = " ".join(value.split())
        if len(normalized) > max_length:
            raise ValueError(f"{field} is too long")
        return normalized

    @staticmethod
    def _optional_text(value: str | None, *, max_length: int | None) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("notes must be text")
        normalized = value.strip()
        if not normalized:
            return None
        if max_length is not None and len(normalized) > max_length:
            raise ValueError("notes is too long")
        return normalized
