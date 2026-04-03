import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import validate_env
from app.pipeline import build_relevant_jobs
from app.services.sheets import (
    append_relevant_jobs,
    deduplicate_jobs_for_sheet,
    ensure_sheet,
    get_gspread_client,
)
from app.services.whatsapp import deduplicate_messages


SCRAPED_FILE = PROJECT_ROOT / "data" / "whatsapp_scraped_temp.json"


def load_scraped_messages() -> List[Dict[str, Any]]:
    if not SCRAPED_FILE.exists():
        raise FileNotFoundError(f"Scraped messages file not found: {SCRAPED_FILE}")

    payload = json.loads(SCRAPED_FILE.read_text(encoding="utf-8"))
    messages = payload.get("messages", [])
    parsed_messages: List[Dict[str, Any]] = []

    for message in messages:
        timestamp = message.get("timestamp", "")
        parsed_messages.append(
            {
                "sender": message.get("sender", ""),
                "timestamp": datetime.fromisoformat(timestamp),
                "text": message.get("text", ""),
            }
        )

    return deduplicate_messages(parsed_messages)


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    config = validate_env()
    messages = load_scraped_messages()
    relevant_jobs = build_relevant_jobs(messages, config)

    if not relevant_jobs:
        print("Relevant jobs found: 0")
        print("Rows appended: 0")
        return

    sheets_client = get_gspread_client(config["service_account_file"])
    worksheet = ensure_sheet(
        sheets_client,
        config["gmail_reply_to"] or config["gmail_sender_email"],
        config["google_sheet_url"],
    )

    unique_jobs = deduplicate_jobs_for_sheet(worksheet, relevant_jobs)
    if unique_jobs:
        append_relevant_jobs(worksheet, unique_jobs)

    print(f"Scraped messages loaded: {len(messages)}")
    print(f"Relevant jobs found: {len(relevant_jobs)}")
    print(f"Rows appended to Filtered Jobs: {len(unique_jobs)}")


if __name__ == "__main__":
    main()
