
from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional


DEFAULT_LOG_PATH = "/opt/var/log/keenetic-tg-bot.log"


def setup_logging(debug: bool = False, log_path: str = DEFAULT_LOG_PATH) -> logging.Logger:
    """
    Configure root logger for the bot.
    - Always logs to file (rotating).
    - If debug=True also logs to stdout.
    """
    Path(os.path.dirname(log_path)).mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("keenetic_tg_bot")
    logger.setLevel(logging.DEBUG if debug else logging.INFO)

    # Avoid duplicate handlers on reload
    if logger.handlers:
        return logger

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    file_handler = RotatingFileHandler(log_path, maxBytes=512 * 1024, backupCount=3, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG if debug else logging.INFO)
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    if debug:
        stream = logging.StreamHandler()
        stream.setLevel(logging.DEBUG)
        stream.setFormatter(fmt)
        logger.addHandler(stream)

    # Silence noisy libs a bit
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("telebot").setLevel(logging.INFO if debug else logging.WARNING)

    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger("keenetic_tg_bot")


def log_exception(logger: logging.Logger, context: str, exc: BaseException) -> None:
    logger.error("%s: %s", context, exc, exc_info=True)
