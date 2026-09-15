"""Service handling Supabase Auth OAuth verification and local UserProfile synchronization."""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
import uuid
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import UserProfile


class AuthError(Exception):
    """Base exception for authentication errors."""


class AuthUserInactiveError(AuthError):
    """Raised when an authenticated user profile has been deactivated."""


@dataclass(frozen=True, slots=True)
class VerifiedIdentity:
    """Validated user identity returned by Supabase Auth."""

    id: uuid.UUID
    email: str
    display_name: str | None
    avatar_url: str | None


class AuthService:
    """Request-scoped service for Supabase Google OAuth and UserProfile sync."""

    ALLOWED_ROLES = {"customer", "admin"}

    def __init__(
        self,
        session: Session,
        supabase_url: str | None = None,
        supabase_key: str | None = None,
    ) -> None:
        self.session = session
        self.supabase_url = (
            supabase_url or os.getenv("SUPABASE_URL") or "https://imdprdofxzlhpsmzwxnj.supabase.co"
        ).rstrip("/")
        self.supabase_key = (
            supabase_key
            or os.getenv("SUPABASE_PUBLISHABLE_KEY")
            or os.getenv("SUPABASE_ANON_KEY")
            or ""
        )

    @staticmethod
    def generate_pkce_pair() -> tuple[str, str]:
        """Generate PKCE code_verifier and S256 code_challenge."""
        verifier = secrets.token_urlsafe(64)[:128]
        digest = hashlib.sha256(verifier.encode("utf-8")).digest()
        challenge = base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")
        return verifier, challenge

    def get_google_authorize_url(
        self,
        redirect_to: str,
        code_challenge: str | None = None,
    ) -> str:
        """Construct the Supabase OAuth authorization URL for Google provider."""
        params = [
            ("provider", "google"),
            ("redirect_to", redirect_to),
        ]
        if code_challenge:
            params.extend(
                [
                    ("code_challenge", code_challenge),
                    ("code_challenge_method", "s256"),
                ]
            )
        query_string = "&".join(f"{k}={httpx.QueryParams({k: v})[k]}" for k, v in params)
        return f"{self.supabase_url}/auth/v1/authorize?{query_string}"

    def exchange_code_or_token(
        self,
        code: str | None = None,
        access_token: str | None = None,
        code_verifier: str | None = None,
    ) -> VerifiedIdentity:
        """Exchange PKCE authorization code or verify access token with Supabase Auth."""
        headers = {
            "apikey": self.supabase_key,
            "Content-Type": "application/json",
        }

        user_data: dict[str, Any] | None = None

        with httpx.Client(timeout=10.0) as client:
            if code:
                # 1. Exchange auth code for session tokens
                payload: dict[str, str] = {"auth_code": code}
                if code_verifier:
                    payload["code_verifier"] = code_verifier

                token_res = client.post(
                    f"{self.supabase_url}/auth/v1/token?grant_type=pkce",
                    headers=headers,
                    json=payload,
                )
                if not token_res.is_success:
                    # Fallback to standard authorization_code grant
                    token_res = client.post(
                        f"{self.supabase_url}/auth/v1/token?grant_type=authorization_code",
                        headers=headers,
                        json={"code": code},
                    )

                if token_res.is_success:
                    data = token_res.json()
                    user_data = data.get("user")
                    access_token = access_token or data.get("access_token")

            if user_data is None and access_token:
                # 2. Fetch user metadata using access_token
                user_res = client.get(
                    f"{self.supabase_url}/auth/v1/user",
                    headers={
                        **headers,
                        "Authorization": f"Bearer {access_token}",
                    },
                )
                if user_res.is_success:
                    user_data = user_res.json()

        if not user_data or not isinstance(user_data, dict):
            raise AuthError("Could not verify user identity with Supabase Auth.")

        user_id_raw = user_data.get("id")
        email = user_data.get("email")
        if not user_id_raw or not email:
            raise AuthError("Supabase Auth user payload missing required id or email.")

        try:
            user_uuid = uuid.UUID(str(user_id_raw))
        except (ValueError, TypeError) as exc:
            raise AuthError(f"Invalid user UUID format: {user_id_raw}") from exc

        metadata = user_data.get("user_metadata") or {}
        display_name = (
            metadata.get("full_name")
            or metadata.get("name")
            or metadata.get("custom_claims", {}).get("global_name")
        )
        avatar_url = metadata.get("avatar_url") or metadata.get("picture")

        return VerifiedIdentity(
            id=user_uuid,
            email=str(email).strip().lower(),
            display_name=str(display_name).strip() if display_name else None,
            avatar_url=str(avatar_url).strip() if avatar_url else None,
        )

    def sync_user_profile(self, identity: VerifiedIdentity) -> UserProfile:
        """Idempotently create or update UserProfile for verified Supabase identity."""
        profile = self.session.get(UserProfile, identity.id)
        if profile is None:
            # Check if email is used by different ID (safeguard)
            existing_by_email = self.session.scalar(
                select(UserProfile).where(UserProfile.email == identity.email)
            )
            if existing_by_email is not None and existing_by_email.id != identity.id:
                raise AuthError(
                    "A user with this email address already exists under a different identity."
                )

            profile = UserProfile(
                id=identity.id,
                email=identity.email,
                display_name=identity.display_name,
                avatar_url=identity.avatar_url,
                role="customer",
                active=True,
            )
            self.session.add(profile)
        else:
            profile.email = identity.email
            if identity.display_name:
                profile.display_name = identity.display_name
            if identity.avatar_url:
                profile.avatar_url = identity.avatar_url

        if not profile.active:
            raise AuthUserInactiveError("This account has been deactivated.")

        self.session.commit()
        return profile

    def set_user_role(self, email: str, role: str) -> UserProfile:
        """Update role for an existing UserProfile."""
        normalized_role = str(role).strip().lower()
        if normalized_role not in self.ALLOWED_ROLES:
            raise ValueError(
                f"Invalid role {role!r}. Allowed roles: {', '.join(sorted(self.ALLOWED_ROLES))}"
            )

        normalized_email = str(email).strip().lower()
        profile = self.session.scalar(
            select(UserProfile).where(UserProfile.email == normalized_email)
        )
        if profile is None:
            raise ValueError(f"No user found with email {normalized_email!r}")

        profile.role = normalized_role
        self.session.commit()
        return profile
