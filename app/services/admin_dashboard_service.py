"""Read models for the authenticated admin dashboard."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeVar

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.car import Car
from app.models.knowledge import KnowledgeDocument
from app.models.lead import SalesLead
from app.models.test_drive import TestDriveRequest

T = TypeVar("T")


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
    """Keep dashboard ORM reads outside Flask routes and templates."""

    DEFAULT_PAGE_SIZE = 30
    MAX_PAGE_SIZE = 100

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

    def cars(self, *, page: int = 1, page_size: int = DEFAULT_PAGE_SIZE) -> AdminPage[Car]:
        page, page_size = self._page_args(page, page_size)
        total = self._count(Car)
        items = list(
            self.session.scalars(
                select(Car)
                .order_by(Car.active.desc(), Car.updated_at.desc(), Car.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        return self._page(items, page, page_size, total)

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
