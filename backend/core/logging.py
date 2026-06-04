import logging
import os
import sys
from logging import Logger


DEFAULT_LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
DEFAULT_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def _resolve_log_level() -> int:
    configured = str(os.getenv("LOG_LEVEL", "INFO")).strip().upper()
    return getattr(logging, configured, logging.INFO)


def configure_logging() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="backslashreplace")

    logging.basicConfig(
        level=_resolve_log_level(),
        format=DEFAULT_LOG_FORMAT,
        datefmt=DEFAULT_DATE_FORMAT,
        stream=sys.stdout,
        force=True,
    )


def get_logger(name: str) -> Logger:
    return logging.getLogger(name)
