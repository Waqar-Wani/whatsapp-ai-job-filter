import logging
import os
import sys

from app.core.constants import DATA_DIR, LOG_DIR, LOG_FILE


def setup_logging() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()

    file_handler = logging.FileHandler(str(LOG_FILE))
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    log_to_stdout = (os.getenv("LOG_TO_STDOUT", "true") or "").strip().lower()
    if log_to_stdout in {"1", "true", "yes"}:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        root.addHandler(console_handler)
