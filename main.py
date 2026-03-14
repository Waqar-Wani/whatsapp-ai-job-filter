import logging

from google.auth.exceptions import GoogleAuthError

from app.core.logging_utils import setup_logging
from app.pipeline import run_pipeline


def main() -> None:
    setup_logging()
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
