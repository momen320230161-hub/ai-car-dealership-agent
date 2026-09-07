import logging
from logging.config import dictConfig


def configure_logging(app):
    """Configure process-wide logging from the active Flask config."""
    level_name = str(app.config.get("LOG_LEVEL", "INFO")).upper()
    level = getattr(logging, level_name, logging.INFO)

    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "standard": {
                    "format": (
                        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
                    ),
                    "datefmt": "%Y-%m-%d %H:%M:%S",
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "standard",
                    "level": level,
                }
            },
            "root": {
                "handlers": ["console"],
                "level": level,
            },
            "loggers": {
                "app": {"level": level, "propagate": True},
                "app.agent": {"level": level, "propagate": True},
                "app.tools": {"level": level, "propagate": True},
                "app.api": {"level": level, "propagate": True},
                "werkzeug": {"level": level, "propagate": True},
            },
        }
    )

    app.logger.setLevel(level)
