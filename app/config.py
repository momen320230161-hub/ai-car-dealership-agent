import os

from dotenv import load_dotenv

load_dotenv()


def sqlalchemy_database_uri(database_url: str) -> str:
    """Use Psycopg 3 for ordinary PostgreSQL URLs supplied in DATABASE_URL."""
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    return database_url


class BaseConfig:
    """Shared settings. Future services read these keys; nothing connects yet."""

    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-me")
    DATABASE_URL = os.getenv("DATABASE_URL", "")
    SQLALCHEMY_DATABASE_URI = sqlalchemy_database_uri(DATABASE_URL)
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    LLM_API_KEY = os.getenv("LLM_API_KEY", "")
    EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY", "")
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    GEMINI_LLM_MODEL = os.getenv("GEMINI_LLM_MODEL", "gemini-3.8-flash")
    GEMINI_EMBEDDING_MODEL = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-2")
    EMBEDDING_DIMENSIONS = int(os.getenv("EMBEDDING_DIMENSIONS", "768"))
    RAG_DEFAULT_TOP_K = int(os.getenv("RAG_DEFAULT_TOP_K", "5"))
    RAG_MAX_TOP_K = int(os.getenv("RAG_MAX_TOP_K", "20"))
    RAG_CHUNK_SIZE = int(os.getenv("RAG_CHUNK_SIZE", "1000"))
    RAG_CHUNK_OVERLAP = int(os.getenv("RAG_CHUNK_OVERLAP", "150"))
    RAG_EMBEDDING_BATCH_SIZE = int(os.getenv("RAG_EMBEDDING_BATCH_SIZE", "10"))


class DevelopmentConfig(BaseConfig):
    DEBUG = True
    TESTING = False
    LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG")


class TestingConfig(BaseConfig):
    DEBUG = True
    TESTING = True
    SECRET_KEY = "test-secret-key"
    LOG_LEVEL = os.getenv("LOG_LEVEL", "WARNING")
    # Tests use an isolated in-memory database; they never use DATABASE_URL.
    SQLALCHEMY_DATABASE_URI = "sqlite+pysqlite:///:memory:"


class ProductionConfig(BaseConfig):
    DEBUG = False
    TESTING = False


CONFIG_MAP = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}


def get_config_class(config_name=None):
    name = (config_name or os.getenv("FLASK_ENV", "development")).lower()
    if name not in CONFIG_MAP:
        raise ValueError(f"Unknown configuration: {name}")
    return CONFIG_MAP[name]
