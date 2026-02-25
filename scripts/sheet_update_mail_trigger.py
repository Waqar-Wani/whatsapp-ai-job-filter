import hashlib
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"
LOG_DIR = PROJECT_ROOT / "logs"

LOG_FILE = str(LOG_DIR / "automation.log")
STATE_FILE = DATA_DIR / "sheet_watch_state.json"


def setup_logging() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE),
            logging.StreamHandler(sys.stdout),
        ],
    )


def load_config() -> Dict[str, str]:
    load_dotenv(PROJECT_ROOT / ".env")
    required = [
        "GOOGLE_SERVICE_ACCOUNT_FILE",
        "GOOGLE_SHEET_URL",
    ]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        raise ValueError(f"Missing env variables: {', '.join(missing)}")

    return {
        "service_account_file": os.environ["GOOGLE_SERVICE_ACCOUNT_FILE"],
        "sheet_url": os.environ["GOOGLE_SHEET_URL"],
        "worksheet_name": os.getenv("OUTREACH_WORKSHEET", "Filtered Jobs"),
        "interval_seconds": str(os.getenv("SHEET_WATCH_INTERVAL_SECONDS", "60")),
        "send_on_start": str(os.getenv("SHEET_WATCH_SEND_ON_START", "false")).lower(),
    }
    sa_path = Path(cfg["service_account_file"])
    if not sa_path.is_absolute():
        cfg["service_account_file"] = str((PROJECT_ROOT / sa_path).resolve())
    return cfg


def gspread_client(service_account_file: str) -> gspread.Client:
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(service_account_file, scopes=scopes)
    return gspread.authorize(creds)


def load_state() -> Dict[str, str]:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(state: Dict[str, str]) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def sheet_snapshot(worksheet) -> Dict[str, str]:
    values: List[List[str]] = worksheet.get_all_values()
    data_rows = values[1:] if values else []
    encoded = json.dumps(data_rows, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return {
        "rows": str(len(data_rows)),
        "hash": digest,
    }


def run_outreach() -> int:
    cmd = [sys.executable, str(PROJECT_ROOT / "scripts" / "company_outreach.py")]
    logging.info("Running outreach automation: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stdout.strip():
        logging.info("Outreach stdout: %s", result.stdout.strip())
    if result.stderr.strip():
        logging.warning("Outreach stderr: %s", result.stderr.strip())
    return result.returncode


def main() -> None:
    setup_logging()
    cfg = load_config()
    interval = int(cfg["interval_seconds"])
    send_on_start = cfg["send_on_start"] in {"1", "true", "yes"}

    client = gspread_client(cfg["service_account_file"])
    spreadsheet = client.open_by_url(cfg["sheet_url"])
    worksheet = spreadsheet.worksheet(cfg["worksheet_name"])
    logging.info("Watching sheet '%s' / worksheet '%s'", spreadsheet.title, worksheet.title)

    state = load_state()
    first_loop = True

    while True:
        try:
            snap = sheet_snapshot(worksheet)
            prev_hash = state.get("hash", "")
            prev_rows = int(state.get("rows", "0") or 0)
            curr_rows = int(snap["rows"])

            changed = snap["hash"] != prev_hash
            has_new_rows = curr_rows > prev_rows

            if first_loop and not prev_hash:
                logging.info("Initialized watcher state. rows=%s", curr_rows)
                if send_on_start and curr_rows > 0:
                    rc = run_outreach()
                    logging.info("Initial outreach return code: %s", rc)
            elif changed and has_new_rows:
                logging.info(
                    "Detected sheet update with new rows (prev=%s, curr=%s). Triggering outreach.",
                    prev_rows,
                    curr_rows,
                )
                rc = run_outreach()
                logging.info("Outreach return code: %s", rc)
            elif changed:
                logging.info("Sheet changed but no new rows detected. Skipping outreach trigger.")
            else:
                logging.info("No sheet changes detected.")

            state.update(snap)
            save_state(state)
            first_loop = False
        except Exception as exc:
            logging.exception("Watcher loop error: %s", exc)

        time.sleep(interval)


if __name__ == "__main__":
    main()
