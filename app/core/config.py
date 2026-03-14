import os
from typing import Dict

from dotenv import load_dotenv

from app.core.constants import DEFAULT_SHEET_URL


def validate_env() -> Dict[str, str]:
    load_dotenv()
    required_vars = [
        "GMAIL_USER",
        "GMAIL_APP_PASSWORD",
        "GOOGLE_SERVICE_ACCOUNT_FILE",
        "OPENROUTER_API_KEY",
    ]
    missing = [var for var in required_vars if not os.getenv(var)]
    if missing:
        raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

    return {
        "openrouter_api_key": os.getenv("OPENROUTER_API_KEY", ""),
        "openrouter_model": os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini"),
        "openrouter_site_url": os.getenv("OPENROUTER_SITE_URL", ""),
        "openrouter_site_name": os.getenv(
            "OPENROUTER_SITE_NAME",
            "Job Scrapping - Whatsapp",
        ),
        "gmail_user": os.environ["GMAIL_USER"],
        "gmail_app_password": os.environ["GMAIL_APP_PASSWORD"],
        "service_account_file": os.environ["GOOGLE_SERVICE_ACCOUNT_FILE"],
        "google_sheet_url": os.getenv("GOOGLE_SHEET_URL", DEFAULT_SHEET_URL),
    }
