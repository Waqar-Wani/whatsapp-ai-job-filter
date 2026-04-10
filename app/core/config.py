import os
from typing import Dict

from dotenv import load_dotenv

from app.core.constants import DEFAULT_SHEET_URL


def validate_env() -> Dict[str, str]:
    load_dotenv()
    required_vars = [
        "GMAIL_SENDER_EMAIL",
        "GMAIL_OAUTH_CLIENT_SECRET_FILE",
        "GOOGLE_SERVICE_ACCOUNT_FILE",
    ]
    missing = [var for var in required_vars if not os.getenv(var)]
    if not os.getenv("OPENROUTER_API_KEY") and not os.getenv("GROQ_API_KEY"):
        missing.append("OPENROUTER_API_KEY or GROQ_API_KEY")
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
        "groq_api_key": os.getenv("GROQ_API_KEY", ""),
        "groq_model": os.getenv("GROQ_MODEL", "llama3-8b-8192"),
        "ai_request_delay_seconds": float(os.getenv("AI_REQUEST_DELAY_SECONDS", "2.0")),
        "gmail_sender_email": os.environ["GMAIL_SENDER_EMAIL"],
        "gmail_oauth_client_secret_file": os.environ["GMAIL_OAUTH_CLIENT_SECRET_FILE"],
        "gmail_token_file": os.getenv("GMAIL_TOKEN_FILE", "data/gmail_token.json"),
        "gmail_reply_to": os.getenv("GMAIL_REPLY_TO", ""),
        "service_account_file": os.environ["GOOGLE_SERVICE_ACCOUNT_FILE"],
        "google_sheet_url": os.getenv("GOOGLE_SHEET_URL", DEFAULT_SHEET_URL),
    }
