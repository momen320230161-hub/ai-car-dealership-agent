"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from datetime import timedelta

from dotenv import load_dotenv

load_dotenv()


def normalize_database_url(url: str | None) -> str | None:
    """Normalize PostgreSQL URLs to SQLAlchemy + Psycopg 3 syntax."""
    if not url:
        return None

    url = url.strip()
    if not url:
        return None
    if url.startswith("postgres://"):
        url = "postgresql://" + url.removeprefix("postgres://")
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class Config:
    """Base runtime configuration."""

    FLASK_ENV = os.getenv("FLASK_ENV", "production")
    DEBUG = _env_bool("FLASK_DEBUG")
    SECRET_KEY = os.getenv("SECRET_KEY") or os.getenv("FLASK_SECRET_KEY")
    SQLALCHEMY_DATABASE_URI = normalize_database_url(os.getenv("DATABASE_URL"))
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _env_bool("SESSION_COOKIE_SECURE")
    PERMANENT_SESSION_LIFETIME = timedelta(
        days=max(1, int(os.getenv("SESSION_LIFETIME_DAYS", "7")))
    )

    # Supabase Auth is used only as the identity provider. Application data still
    # goes through SQLAlchemy/PostgreSQL.
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_PUBLISHABLE_KEY = os.getenv("SUPABASE_PUBLISHABLE_KEY")
    SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
    # Server-side only. This key is used by protected admin operations such as
    # uploading catalog images and must never be exposed to browser JavaScript.
    SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY") or os.getenv(
        "SUPABASE_SERVICE_ROLE_KEY"
    )
    CAR_IMAGE_BUCKET = os.getenv("CAR_IMAGE_BUCKET", "car-images")
    MAX_CAR_IMAGE_BYTES = int(os.getenv("MAX_CAR_IMAGE_BYTES", str(5 * 1024 * 1024)))
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", str(16 * 1024 * 1024)))

    EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "gemini")
    EMBEDDING_MODEL = os.getenv(
        "EMBEDDING_MODEL", os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-2")
    )
    EMBEDDING_DIMENSION = int(
        os.getenv("EMBEDDING_DIMENSION", os.getenv("EMBEDDING_DIMENSIONS", "768"))
    )
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("EMBEDDING_API_KEY")
    RAG_TOP_K = int(os.getenv("RAG_TOP_K", "4"))
    RAG_MAX_TOP_K = int(os.getenv("RAG_MAX_TOP_K", "20"))
    RAG_MIN_SCORE = float(os.environ["RAG_MIN_SCORE"]) if os.getenv("RAG_MIN_SCORE") else None
    AGENT_LLM_PROVIDER = os.getenv("AGENT_LLM_PROVIDER", "gemini")
    AGENT_LLM_MODEL = os.getenv("AGENT_LLM_MODEL", "gemini-3.5-flash-lite")
    AGENT_LLM_TEMPERATURE = float(os.getenv("AGENT_LLM_TEMPERATURE", "0.1"))
    AGENT_MAX_MESSAGE_LENGTH = int(os.getenv("AGENT_MAX_MESSAGE_LENGTH", "4000"))
    AGENT_RECENT_MESSAGE_LIMIT = int(os.getenv("AGENT_RECENT_MESSAGE_LIMIT", "12"))
    AGENT_RECOMMENDATION_LIMIT = int(os.getenv("AGENT_RECOMMENDATION_LIMIT", "3"))
    CHAT_SLOW_REQUEST_MS = int(os.getenv("CHAT_SLOW_REQUEST_MS", "5000"))

    # PDF Knowledge Ingestion (optional/bonus feature)
    MAX_KNOWLEDGE_PDF_BYTES = int(os.getenv("MAX_KNOWLEDGE_PDF_BYTES", str(10 * 1024 * 1024)))
    MAX_KNOWLEDGE_PDF_PAGES = int(os.getenv("MAX_KNOWLEDGE_PDF_PAGES", "50"))
    MAX_KNOWLEDGE_EXTRACTED_CHARS = int(os.getenv("MAX_KNOWLEDGE_EXTRACTED_CHARS", "100000"))
