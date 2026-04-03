import logging
import os
import subprocess
from pathlib import Path

from google.auth.exceptions import GoogleAuthError

from app.core.logging_utils import setup_logging
from app.pipeline import run_pipeline


def clear_browser_cache_before_run() -> None:
    run_cache = (os.getenv("CLEAR_BROWSER_CACHE_BEFORE_RUN", "true") or "").strip().lower()
    if run_cache not in {"1", "true", "yes"}:
        logging.info("Skipping browser cache clear (CLEAR_BROWSER_CACHE_BEFORE_RUN=%s).", run_cache)
        return

    script_path = Path(__file__).resolve().parent / "scripts" / "clear_browser_cache.ps1"
    if not script_path.exists():
        logging.warning("Clear cache script not found: %s", script_path)
        return

    if os.name != "nt":
        logging.warning("Skipping PowerShell cache clear on non-Windows platform: %s", os.name)
        return

    try:
        logging.info("Clearing browser cache before run using %s", script_path)
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script_path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        logging.info("Browser cache cleared successfully.")
    except subprocess.CalledProcessError as exc:
        logging.warning("Failed to clear browser cache (returncode=%s): %s", exc.returncode, exc.stderr)
    except Exception as exc:
        logging.warning("Unexpected error clearing browser cache: %s", exc)


def main() -> None:
    setup_logging()
    clear_browser_cache_before_run()
    run_pipeline()


if __name__ == "__main__":
    try:
        main()
    except (ValueError, FileNotFoundError, GoogleAuthError) as exc:
        logging.exception("Configuration/authentication error: %s", exc)
        raise
    except Exception as exc:
        logging.exception("Unhandled fatal error: %s", exc)
        raise
