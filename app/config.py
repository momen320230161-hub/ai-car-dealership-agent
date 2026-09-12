"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os

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


class Config:
    """Base runtime configuration."""

    FLASK_ENV = os.getenv("FLASK_ENV", "production")
    DEBUG = os.getenv("FLASK_DEBUG", "0").lower() in ("1", "true", "yes")
    SECRET_KEY = os.getenv("SECRET_KEY")
    SQLALCHEMY_DATABASE_URI = normalize_database_url(os.getenv("DATABASE_URL"))
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }
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
    RAG_MIN_SCORE = (
        float(os.environ["RAG_MIN_SCORE"]) if os.getenv("RAG_MIN_SCORE") else None
    )
    AGENT_LLM_PROVIDER = os.getenv("AGENT_LLM_PROVIDER", "gemini")
    AGENT_LLM_MODEL = os.getenv("AGENT_LLM_MODEL", "gemini-3.6-flash")
    AGENT_LLM_TEMPERATURE = float(os.getenv("AGENT_LLM_TEMPERATURE", "0.1"))
    AGENT_MAX_MESSAGE_LENGTH = int(os.getenv("AGENT_MAX_MESSAGE_LENGTH", "4000"))
    AGENT_RECENT_MESSAGE_LIMIT = int(os.getenv("AGENT_RECENT_MESSAGE_LIMIT", "12"))
    AGENT_RECOMMENDATION_LIMIT = int(os.getenv("AGENT_RECOMMENDATION_LIMIT", "3"))
