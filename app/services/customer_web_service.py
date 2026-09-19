"""Read models used by the customer Flask website and chat surface."""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.catalog_filters import CatalogFilters
from app.models.car import Car
from app.models.message import ChatMessage
from app.services.catalog_service import CatalogService
from app.services.conversation_context_service import (
    ConversationContext,
    ConversationContextService,
)


@dataclass(frozen=True, slots=True)
class CatalogPage:
    """Bounded catalog page ready for a server-rendered customer view."""

    cars: list[Car]
    total: int
    page: int
    page_size: int
    total_pages: int
    has_previous: bool
    has_next: bool


@dataclass(frozen=True, slots=True)
class CustomerChatState:
    """Safe, bounded customer-visible state for rendering the chat UI."""

    session_id: uuid.UUID
    messages: list[dict[str, Any]]
    selected_car: dict[str, Any] | None
    pending_action_type: str | None
    visible_recommendations: list[dict[str, Any]]


class CustomerWebService:
    """Prepare catalog and conversation data without putting ORM queries in routes/templates."""

    DEFAULT_PAGE_SIZE = 12
    MAX_HISTORY_MESSAGES = 100

    def __init__(self, session: Session, *, recent_message_limit: int = 12) -> None:
        self.session = session
        self.catalog = CatalogService(session)
        self.context = ConversationContextService(
            session,
            recent_message_limit=recent_message_limit,
        )

    def featured_cars(self, *, limit: int = 3) -> list[Car]:
        """Return a small deterministic set for the landing page."""
        return self.catalog.search(sort_by="year_desc", limit=limit)

    def catalog_count(self, filters: CatalogFilters | None = None) -> int:
        return self.catalog.count(filters)

    def catalog_facets(self) -> dict[str, list[str]]:
        """Return only values that actually exist in the active catalog."""
        return {
            "brands": self.catalog.facet_values("brand", limit=80),
            "body_types": self.catalog.facet_values("body_type", limit=40),
        }

    def catalog_page(
        self,
        filters: CatalogFilters,
        *,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
        sort_by: str = "year_desc",
    ) -> CatalogPage:
        if page_size < 1 or page_size > 48:
            raise ValueError("page_size must be between 1 and 48")
        requested_page = max(1, int(page))
        total = self.catalog.count(filters)
        total_pages = max(1, math.ceil(total / page_size))
        resolved_page = min(requested_page, total_pages)
        cars = self.catalog.search(
            filters,
            sort_by=sort_by,
            limit=page_size,
            offset=(resolved_page - 1) * page_size,
        )
        return CatalogPage(
            cars=cars,
            total=total,
            page=resolved_page,
            page_size=page_size,
            total_pages=total_pages,
            has_previous=resolved_page > 1,
            has_next=resolved_page < total_pages,
        )

    def car_details(self, car_id: int) -> Car | None:
        return self.catalog.get_car(car_id)

    def ensure_conversation(
        self,
        session_id: uuid.UUID | str | None,
        user_id: uuid.UUID | str | None = None,
    ) -> ConversationContext:
        return self.context.load_or_create(session_id, user_id=user_id)

    def chat_state(
        self,
        session_id: uuid.UUID | str,
        user_id: uuid.UUID | str | None = None,
    ) -> CustomerChatState:
        context = self.context.load_or_create(session_id, user_id=user_id)
        messages = list(
            self.session.scalars(
                select(ChatMessage)
                .where(ChatMessage.session_id == context.session_id)
                .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
                .limit(self.MAX_HISTORY_MESSAGES)
            )
        )
        messages.reverse()

        selected_car = None
        if context.selected_car_id is not None:
            details = self.catalog.get_car_details(context.selected_car_id)
            if details is not None:
                selected_car = ConversationContextService._json_safe(details)

        active_items = (context.active_snapshot or {}).get("items", [])
        pending_action = context.pending_action or {}
        pending_type = str(pending_action.get("type") or "").strip() or None
        return CustomerChatState(
            session_id=context.session_id,
            messages=[
                {
                    "role": message.role,
                    "content": message.content,
                    "created_at": message.created_at.isoformat(),
                }
                for message in messages
                if message.role in {"user", "assistant"}
            ],
            selected_car=selected_car,
            pending_action_type=pending_type,
            visible_recommendations=list(active_items),
        )

    def user_conversations(
        self,
        user_id: uuid.UUID | str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return self.context.get_user_conversations(user_id, limit=limit)
