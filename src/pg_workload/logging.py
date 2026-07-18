from __future__ import annotations

import logging
import logging.handlers
import time
from pathlib import Path


def profile_job_logger(
    log_path: Path,
    *,
    max_bytes: int,
    backup_count: int,
    rotate_on_start: bool,
) -> logging.Logger:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"workload.{log_path.resolve()}.{time.monotonic_ns()}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    if rotate_on_start and log_path.exists() and log_path.stat().st_size > 0:
        handler.doRollover()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    return logger


def close_logger(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)
