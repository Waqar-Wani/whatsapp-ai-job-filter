import logging
import os
import subprocess
import sys

from app.core.constants import OUTREACH_SCRIPT


def run_outreach_task() -> None:
    enabled = (os.getenv("RUN_OUTREACH_ON_MAIN", "true") or "").strip().lower()
    if enabled not in {"1", "true", "yes"}:
        logging.info("Step: Outreach task skipped (RUN_OUTREACH_ON_MAIN=%s).", enabled)
        return

    if not OUTREACH_SCRIPT.exists():
        logging.warning("Step: Outreach script not found at %s. Skipping outreach.", OUTREACH_SCRIPT)
        return

    logging.info("Step: Running outreach task via %s", OUTREACH_SCRIPT)
    result = subprocess.run(
        [sys.executable, str(OUTREACH_SCRIPT)],
        capture_output=True,
        text=True,
    )
    if result.stdout.strip():
        logging.info("Outreach stdout: %s", result.stdout.strip())
    if result.stderr.strip():
        logging.warning("Outreach stderr: %s", result.stderr.strip())
    logging.info("Step: Outreach task completed with return code %s.", result.returncode)
