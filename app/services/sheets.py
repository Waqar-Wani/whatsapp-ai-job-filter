import logging
import time
from typing import Any, Dict, List

import gspread
from google.oauth2.service_account import Credentials

from app.core.constants import SPREADSHEET_TITLE, WORKSHEET_TITLE


SHEET_HEADERS = [
    "Date",
    "Company",
    "Role",
    "Location",
    "Experience",
    "Skills",
    "Contact Email",
    "Outreach Status",
    "Outreach Sent At",
]


def get_gspread_client(service_account_file: str, retries: int = 3, initial_delay: float = 2.0) -> gspread.Client:
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    for attempt in range(1, retries + 1):
        try:
            creds = Credentials.from_service_account_file(service_account_file, scopes=scopes)
            client = gspread.authorize(creds)
            # quick check - fetch drive root metadata by opening a worksheet (cheap no-op in most cases)
            return client

        except Exception as exc:
            logging.warning("Google Sheets auth failed (attempt %s/%s): %s", attempt, retries, exc)
            if attempt == retries:
                raise
            time.sleep(initial_delay * (2 ** (attempt - 1)))

    raise RuntimeError("Could not authenticate Google Sheets client after retries")


def ensure_sheet(client: gspread.Client, owner_email: str, spreadsheet_url: str):
    try:
        spreadsheet = client.open_by_url(spreadsheet_url)
        logging.info("Opened spreadsheet by URL.")
    except gspread.SpreadsheetNotFound:
        logging.warning("Spreadsheet URL not found or inaccessible. Creating a new one.")
        spreadsheet = client.create(SPREADSHEET_TITLE)
        try:
            spreadsheet.share(owner_email, perm_type="user", role="owner", notify=False)
            logging.info(
                "Created spreadsheet '%s' and transferred ownership to %s",
                SPREADSHEET_TITLE,
                owner_email,
            )
        except Exception:
            spreadsheet.share(owner_email, perm_type="user", role="writer", notify=False)
            logging.info(
                "Created spreadsheet '%s' and shared with %s as writer",
                SPREADSHEET_TITLE,
                owner_email,
            )
            logging.info(
                "If strict ownership is required, create the sheet from owner account and share with service account."
            )

    try:
        worksheet = spreadsheet.worksheet(WORKSHEET_TITLE)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(title=WORKSHEET_TITLE, rows=1000, cols=12)

    current_header = worksheet.row_values(1)
    if current_header[: len(SHEET_HEADERS)] != SHEET_HEADERS:
        worksheet.update(f"A1:{gspread.utils.rowcol_to_a1(1, len(SHEET_HEADERS))}", [SHEET_HEADERS])

    return worksheet


def append_relevant_jobs(worksheet, jobs: List[Dict[str, Any]]) -> None:
    rows = []
    for job in jobs:
        rows.append(
            [
                job["date"],
                job["company"],
                job["role"],
                job["location"],
                job["experience"],
                job["skills"],
                job["contact_email"],
                "",
                "",
            ]
        )
    if rows:
        worksheet.append_rows(rows, value_input_option="RAW")


def normalize_key_part(value: str) -> str:
    text = (value or "").strip().lower()
    text = text.replace("\u00a0", " ").replace("\u202f", " ").replace("\u2013", "-").replace("\u2014", "-")
    return " ".join(text.split())


def canonical_job_identity(values: Dict[str, Any]) -> str:
    date_value = normalize_key_part(str(values.get("date", "")))
    company = normalize_key_part(str(values.get("company", "")))
    role = normalize_key_part(str(values.get("role", "")))
    contact_email = normalize_key_part(str(values.get("contact_email", "")))
    location = normalize_key_part(str(values.get("location", "")))

    if contact_email:
        return f"job|{date_value}|{company}|{role}|{contact_email}"
    return f"job|{date_value}|{company}|{role}|{location}"


def deduplicate_jobs_for_sheet(worksheet, jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not jobs:
        return []

    headers = [header.strip().lower().replace(" ", "_") for header in worksheet.row_values(1)]
    existing_rows = worksheet.get_all_values()
    existing_keys = set()
    for row in existing_rows[1:]:
        if len(row) < 7:
            continue
        row_map = {headers[idx]: row[idx] if idx < len(row) else "" for idx in range(len(headers))}
        existing_keys.add(canonical_job_identity(row_map))

    unique_jobs: List[Dict[str, Any]] = []
    batch_seen = set()
    source_seen = set()
    for job in jobs:
        source_key = normalize_key_part(str(job.get("source_key", "")))
        if source_key and source_key in source_seen:
            continue

        key = canonical_job_identity(job)
        if key in existing_keys or key in batch_seen:
            continue

        if source_key:
            source_seen.add(source_key)
        batch_seen.add(key)
        unique_jobs.append(job)

    return unique_jobs
