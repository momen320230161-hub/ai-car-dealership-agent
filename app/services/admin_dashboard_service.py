"""Read/write services for the authenticated admin dashboard."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from app.models.base import utc_now
from app.models.car import Car
from app.models.knowledge import KnowledgeDocument
from app.models.lead import SalesLead
from app.models.test_drive import TestDriveRequest


class AdminDashboardError(RuntimeError):
    """Base error for controlled admin dashboard failures."""


class AdminValidationError(AdminDashboardError):
    """Raised when an admin mutation contains invalid business data."""


class AdminNotFoundError(AdminDashboardError):
    """Raised when an admin mutation targets a missing row."""


class AdminPersistenceError(AdminDashboardError):
    """Raised when a dashboard write cannot be committed."""


@dataclass(frozen=True, slots=True)
class AdminPage[T]:
    items: list[T]
    page: int
    page_size: int
    total: int
    total_pages: int


@dataclass(frozen=True, slots=True)
class AdminOverview:
    active_cars: int
    test_drives_total: int
    test_drives_new: int
    sales_leads_total: int
    sales_leads_new: int
    knowledge_total: int
    knowledge_indexed: int
    knowledge_failed: int


class AdminDashboardService:
    """Keep dashboard ORM reads and controlled writes outside Flask routes."""

    DEFAULT_PAGE_SIZE = 30
    MAX_PAGE_SIZE = 100
    TEST_DRIVE_TRANSITIONS = {
        "NEW": {"CONFIRMED", "CANCELLED"},
        "CONFIRMED": {"COMPLETED", "CANCELLED"},
        "COMPLETED": set(),
        "CANCELLED": set(),
    }
    LEAD_TRANSITIONS = {
        "NEW": {"CONTACTED", "QUALIFIED", "CLOSED_WON", "CLOSED_LOST"},
        "CONTACTED": {"QUALIFIED", "CLOSED_WON", "CLOSED_LOST"},
        "QUALIFIED": {"CLOSED_WON", "CLOSED_LOST"},
        "CLOSED_WON": set(),
        "CLOSED_LOST": set(),
    }

    def __init__(self, session: Session) -> None:
        self.session = session

    def overview(self) -> AdminOverview:
        return AdminOverview(
            active_cars=self._count(Car, Car.active.is_(True)),
            test_drives_total=self._count(TestDriveRequest),
            test_drives_new=self._count(TestDriveRequest, TestDriveRequest.status == "NEW"),
            sales_leads_total=self._count(SalesLead),
            sales_leads_new=self._count(SalesLead, SalesLead.status == "NEW"),
            knowledge_total=self._count(KnowledgeDocument),
            knowledge_indexed=self._count(
                KnowledgeDocument,
                KnowledgeDocument.index_status == "indexed",
            ),
            knowledge_failed=self._count(
                KnowledgeDocument,
                KnowledgeDocument.index_status == "failed",
            ),
        )

    def cars(
        self,
        *,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
        query: str | None = None,
        condition: str | None = None,
        active: bool | None = None,
    ) -> AdminPage[Car]:
        page, page_size = self._page_args(page, page_size)
        criteria = []
        cleaned_query = (query or "").strip()
        if cleaned_query:
            pattern = f"%{cleaned_query}%"
            criteria.append(
                or_(
                    Car.brand.ilike(pattern),
                    Car.model.ilike(pattern),
                    Car.trim.ilike(pattern),
                )
            )
        if condition in {"new", "used"}:
            criteria.append(Car.condition == condition)
        if active is not None:
            criteria.append(Car.active.is_(active))

        count_statement = select(func.count()).select_from(Car)
        statement = select(Car)
        if criteria:
            count_statement = count_statement.where(*criteria)
            statement = statement.where(*criteria)
        total = int(self.session.scalar(count_statement) or 0)
        items = list(
            self.session.scalars(
                statement.order_by(Car.active.desc(), Car.updated_at.desc(), Car.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        return self._page(items, page, page_size, total)

    def car(self, car_id: int) -> Car | None:
        return self.session.get(Car, car_id)

    def create_car(self, values: Mapping[str, str], *, active: bool = True) -> Car:
        fields = self._validated_car_fields(values)
        car = Car(
            **fields,
            active=active,
            source="admin_dashboard",
            source_id=f"admin:{uuid.uuid4()}",
            data_quality_status="admin_managed",
            data_quality_metadata={"managed_by": "admin_dashboard"},
        )
        self.session.add(car)
        self._commit("create car")
        return car

    def update_car(
        self,
        car_id: int,
        values: Mapping[str, str],
        *,
        active: bool,
    ) -> Car:
        car = self.session.get(Car, car_id)
        if car is None:
            raise AdminNotFoundError("Car was not found")
        fields = self._validated_car_fields(values)
        for name, value in fields.items():
            setattr(car, name, value)
        car.active = active
        self._commit("update car")
        return car

    def deactivate_car(self, car_id: int) -> Car:
        car = self.session.get(Car, car_id)
        if car is None:
            raise AdminNotFoundError("Car was not found")
        if not car.active:
            return car
        car.active = False
        self._commit("deactivate car")
        return car

    def test_drives(
        self,
        *,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> AdminPage[TestDriveRequest]:
        page, page_size = self._page_args(page, page_size)
        total = self._count(TestDriveRequest)
        items = list(
            self.session.scalars(
                select(TestDriveRequest)
                .options(selectinload(TestDriveRequest.car))
                .order_by(TestDriveRequest.created_at.desc(), TestDriveRequest.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        return self._page(items, page, page_size, total)

    def update_test_drive_status(self, request_id: int, new_status: str) -> TestDriveRequest:
        item = self.session.get(TestDriveRequest, request_id)
        if item is None:
            raise AdminNotFoundError("Test drive request was not found")
        target = (new_status or "").strip().upper()
        if target == item.status:
            return item
        allowed = self.TEST_DRIVE_TRANSITIONS.get(item.status, set())
        if target not in allowed:
            raise AdminValidationError(
                f"Test drive cannot move from {item.status} to {target or 'blank'}"
            )
        item.status = target
        if target == "CANCELLED":
            item.cancelled_at = utc_now()
        self._commit("update test drive status")
        return item

    def sales_leads(
        self,
        *,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> AdminPage[SalesLead]:
        page, page_size = self._page_args(page, page_size)
        total = self._count(SalesLead)
        items = list(
            self.session.scalars(
                select(SalesLead)
                .options(selectinload(SalesLead.car))
                .order_by(SalesLead.created_at.desc(), SalesLead.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        return self._page(items, page, page_size, total)

    def update_sales_lead_status(self, lead_id: int, new_status: str) -> SalesLead:
        item = self.session.get(SalesLead, lead_id)
        if item is None:
            raise AdminNotFoundError("Sales lead was not found")
        target = (new_status or "").strip().upper()
        if target == item.status:
            return item
        allowed = self.LEAD_TRANSITIONS.get(item.status, set())
        if target not in allowed:
            raise AdminValidationError(
                f"Sales lead cannot move from {item.status} to {target or 'blank'}"
            )
        item.status = target
        self._commit("update sales lead status")
        return item

    def knowledge_documents(self) -> list[KnowledgeDocument]:
        return list(
            self.session.scalars(
                select(KnowledgeDocument).order_by(
                    KnowledgeDocument.updated_at.desc(),
                    KnowledgeDocument.title.asc(),
                )
            )
        )

    def knowledge_document(self, document_id) -> KnowledgeDocument | None:
        return self.session.get(KnowledgeDocument, document_id)

    def _validated_car_fields(self, values: Mapping[str, str]) -> dict[str, object]:
        brand = self._required_text(values.get("brand"), "brand", 100)
        model = self._required_text(values.get("model"), "model", 100)
        condition = self._required_text(values.get("condition"), "condition", 20).lower()
        if condition not in {"new", "used"}:
            raise AdminValidationError("condition must be new or used")

        year = self._integer(values.get("year"), "year", minimum=1900)
        if year > 2100:
            raise AdminValidationError("year must be 2100 or earlier")
        price = self._decimal(values.get("price_egp"), "price_egp", minimum=Decimal("0"))
        mileage = self._optional_integer(values.get("mileage_km"), "mileage_km", minimum=0)
        engine = self._optional_integer(
            values.get("engine_capacity_cc"),
            "engine_capacity_cc",
            minimum=1,
        )
        horsepower = self._optional_decimal(
            values.get("horsepower"),
            "horsepower",
            minimum=Decimal("0"),
        )

        return {
            "brand": brand,
            "model": model,
            "year": year,
            "condition": condition,
            "price_egp": price,
            "body_type": self._optional_text(values.get("body_type"), 50),
            "transmission": self._optional_text(values.get("transmission"), 50),
            "fuel_type": self._optional_text(values.get("fuel_type"), 50),
            "mileage_km": mileage,
            "engine_capacity_cc": engine,
            "horsepower": horsepower,
            "trim": self._optional_text(values.get("trim"), 100),
            "color": self._optional_text(values.get("color"), 50),
            "location": self._optional_text(values.get("location"), 100),
        }

    @staticmethod
    def _required_text(value: str | None, field: str, max_length: int) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise AdminValidationError(f"{field} is required")
        if len(cleaned) > max_length:
            raise AdminValidationError(f"{field} is too long")
        return cleaned

    @staticmethod
    def _optional_text(value: str | None, max_length: int) -> str | None:
        cleaned = (value or "").strip()
        if not cleaned:
            return None
        if len(cleaned) > max_length:
            raise AdminValidationError("optional text value is too long")
        return cleaned

    @staticmethod
    def _integer(value: str | None, field: str, *, minimum: int) -> int:
        try:
            parsed = int(str(value or "").strip())
        except ValueError as exc:
            raise AdminValidationError(f"{field} must be an integer") from exc
        if parsed < minimum:
            raise AdminValidationError(f"{field} is below its minimum")
        return parsed

    @classmethod
    def _optional_integer(cls, value: str | None, field: str, *, minimum: int) -> int | None:
        if not str(value or "").strip():
            return None
        return cls._integer(value, field, minimum=minimum)

    @staticmethod
    def _decimal(value: str | None, field: str, *, minimum: Decimal) -> Decimal:
        try:
            parsed = Decimal(str(value or "").replace(",", "").strip())
        except InvalidOperation as exc:
            raise AdminValidationError(f"{field} must be numeric") from exc
        if not parsed.is_finite() or parsed < minimum:
            raise AdminValidationError(f"{field} is below its minimum")
        return parsed

    @classmethod
    def _optional_decimal(
        cls,
        value: str | None,
        field: str,
        *,
        minimum: Decimal,
    ) -> Decimal | None:
        if not str(value or "").strip():
            return None
        return cls._decimal(value, field, minimum=minimum)

    def _commit(self, operation: str) -> None:
        try:
            self.session.commit()
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise AdminPersistenceError(f"Could not {operation}") from exc

    def _count(self, model, criterion=None) -> int:
        statement = select(func.count()).select_from(model)
        if criterion is not None:
            statement = statement.where(criterion)
        return int(self.session.scalar(statement) or 0)

    @classmethod
    def _page_args(cls, page: int, page_size: int) -> tuple[int, int]:
        resolved_page = max(1, int(page))
        resolved_size = min(cls.MAX_PAGE_SIZE, max(1, int(page_size)))
        return resolved_page, resolved_size

    @staticmethod
    def _page(items: list[T], page: int, page_size: int, total: int) -> AdminPage[T]:
        total_pages = max(1, (total + page_size - 1) // page_size)
        return AdminPage(
            items=items,
            page=page,
            page_size=page_size,
            total=total,
            total_pages=total_pages,
        )
