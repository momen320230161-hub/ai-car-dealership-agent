"""UserProfile model for customer and admin identities authenticated via Supabase Auth."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from flask_login import UserMixin
from sqlalchemy import Boolean, CheckConstraint, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import GUID, Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.conversation import ConversationSession


class UserProfile(Base, UserMixin, TimestampMixin):
    """Application-side identity model anchored on the verified Supabase Auth user UUID."""

    __tablename__ = "user_profiles"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
    )
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    role: Mapped[str] = mapped_column(
        String(50),
        default="customer",
        server_default="customer",
        nullable=False,
    )
    active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default=text("true"),
        nullable=False,
    )

    conversations: Mapped[list[ConversationSession]] = relationship(
        "ConversationSession",
        back_populates="user",
        cascade="all, delete-orphan",
        order_by="ConversationSession.updated_at.desc()",
    )

    __table_args__ = (
        CheckConstraint(
            "role IN ('customer', 'admin')",
            name="user_profile_role_check",
        ),
        Index("ix_user_profiles_role", "role"),
    )

    def get_id(self) -> str:
        """Return text representation of UUID for Flask-Login."""
        return str(self.id)

    @property
    def is_active(self) -> bool:
        """Required by Flask-Login UserMixin."""
        return self.active

    @property
    def is_admin(self) -> bool:
        """Check if user has admin privileges."""
        return self.role == "admin"

    def __repr__(self) -> str:
        return f"<UserProfile id={self.id} email={self.email!r} role={self.role!r}>"
