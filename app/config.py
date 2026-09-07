import os

from dotenv import load_dotenv

load_dotenv()


class BaseConfig:
    """Shared settings. Future services read these keys; nothing connects yet."""

    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-me")
    DATABASE_URL = os.getenv("DATABASE_URL", "")
    LLM_API_KEY = os.getenv("LLM_API_KEY", "")
    EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY", "")
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")


class DevelopmentConfig(BaseConfig):
    DEBUG = True
    TESTING = False
    LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG")


class TestingConfig(BaseConfig):
    DEBUG = True
    TESTING = True
    SECRET_KEY = "test-secret-key"
    LOG_LEVEL = os.getenv("LOG_LEVEL", "WARNING")


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
