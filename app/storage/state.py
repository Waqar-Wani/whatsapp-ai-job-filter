import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.core.constants import LAST_PROCESSED_FILE, TEMP_SCRAPED_FILE


def load_last_processed_timestamp() -> Optional[datetime]:
    if not LAST_PROCESSED_FILE.exists():
        return None

    try:
        payload = json.loads(LAST_PROCESSED_FILE.read_text(encoding="utf-8"))
        ts = payload.get("last_message_timestamp")
        if not ts:
            return None
        return datetime.fromisoformat(ts)
    except (json.JSONDecodeError, ValueError) as exc:
        logging.warning("Could not parse %s: %s", LAST_PROCESSED_FILE, exc)
        return None


def save_last_processed_timestamp(ts: datetime) -> None:
    payload = {"last_message_timestamp": ts.isoformat()}
    LAST_PROCESSED_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def save_temp_scraped_messages(messages: List[Dict[str, Any]]) -> None:
    payload = {
        "generated_at": datetime.now().isoformat(),
        "count": len(messages),
        "messages": [
            {
                "sender": m["sender"],
                "timestamp": m["timestamp"].isoformat(),
                "text": m["text"],
            }
            for m in messages
        ],
    }
    TEMP_SCRAPED_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
