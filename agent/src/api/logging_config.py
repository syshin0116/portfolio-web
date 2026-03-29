"""Logging configuration loader and JSON formatter."""

import json
import logging
import logging.config
import os
from datetime import UTC, datetime
from pathlib import Path

import yaml


class JsonFormatter(logging.Formatter):
    """JSON log formatter for structured logging in production."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)
        if hasattr(record, "request_id"):
            log_entry["request_id"] = record.request_id
        return json.dumps(log_entry, ensure_ascii=False)


def setup_logging() -> None:
    """Load logging.yaml and apply LOG_LEVEL / LOG_FORMAT overrides."""
    config_path = Path(__file__).resolve().parent / "logging.yaml"

    if config_path.exists():
        with open(config_path) as f:
            config = yaml.safe_load(f)

        # Override handler based on LOG_FORMAT env var
        log_format = os.getenv("LOG_FORMAT", "standard")
        if log_format == "json":
            for logger_cfg in config.get("loggers", {}).values():
                if "handlers" in logger_cfg:
                    logger_cfg["handlers"] = [
                        "console_json" if h == "console" else h
                        for h in logger_cfg["handlers"]
                    ]
            config["root"]["handlers"] = ["console_json"]

        # Override log level from env
        log_level = os.getenv("LOG_LEVEL", "").upper()
        if log_level and hasattr(logging, log_level):
            config["root"]["level"] = log_level
            for logger_cfg in config.get("loggers", {}).values():
                if logger_cfg.get("level") in ("DEBUG", "INFO"):
                    logger_cfg["level"] = log_level

        logging.config.dictConfig(config)
    else:
        # Fallback: basic config
        log_level = os.getenv("LOG_LEVEL", "INFO").upper()
        logging.basicConfig(
            level=getattr(logging, log_level, logging.INFO),
            format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    logging.getLogger(__name__).debug(
        "Logging configured (format=%s)",
        log_format if config_path.exists() else "basic",
    )
