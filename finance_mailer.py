import base64
import html
import logging
import mimetypes
import re
import socket
import sys
import time
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import gspread
import requests
from google.auth.exceptions import RefreshError, TransportError
from google.auth.transport.requests import AuthorizedSession, Request
from google.oauth2.credentials import Credentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from google_auth_oauthlib.flow import InstalledAppFlow
from requests.adapters import HTTPAdapter
from urllib3.util import Retry
import urllib3.util.connection as urllib3_connection

from finance_config import (
    DATA_DIR,
    FINANCE_CV_FILE,
    FINANCE_GMAIL_OAUTH_CLIENT_SECRET_FILE,
    FINANCE_GMAIL_TOKEN_FILE,
    FINANCE_LOG_FILE,
    FINANCE_MAX_EMAILS_PER_RUN,
    FINANCE_MAX_CONSECUTIVE_RATE_LIMITS,
    FINANCE_MAX_SEND_RETRIES,
    FINANCE_RATE_LIMIT_COOLDOWN_SECONDS,
    FINANCE_REPLY_TO,
    FINANCE_SECONDS_BETWEEN_EMAILS,
    FINANCE_SENDER_EMAIL,
    FINANCE_SUBJECT_TEMPLATE,
    FINANCE_TEMPLATE_FILE,
    GOOGLE_SERVICE_ACCOUNT_FILE,
    LOG_DIR,
    SOURCE_SHEET_URL,
    SOURCE_WORKSHEET_NAME,
    TRACKING_HEADERS,
    TRACKING_SPREADSHEET_TITLE,
    TRACKING_SPREADSHEET_URL,
    TRACKING_WORKSHEET_TITLE,
)


LOGGER = logging.getLogger(__name__)
GMAIL_SEND_SCOPE = ["https://www.googleapis.com/auth/gmail.send"]
GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
SHEETS_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
CONNECT_TIMEOUT_SECONDS = 8
READ_TIMEOUT_SECONDS = 8
MAX_RETRIES = 3
EMAIL_PATTERN = re.compile(r"^[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}$", re.IGNORECASE)

_IPV4_FORCED = False


class DefaultTimeoutSession(requests.Session):
    def __init__(self, timeout: Tuple[int, int]) -> None:
        super().__init__()
        self._default_timeout = timeout

    def request(self, *args, **kwargs):  # type: ignore[override]
        kwargs.setdefault("timeout", self._default_timeout)
        return super().request(*args, **kwargs)


class FinanceRateLimitError(RuntimeError):
    pass


def setup_logging() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()

    file_handler = logging.FileHandler(str(FINANCE_LOG_FILE))
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)


def _force_ipv4() -> None:
    global _IPV4_FORCED
    if _IPV4_FORCED:
        return

    urllib3_connection.allowed_gai_family = lambda: socket.AF_INET
    _IPV4_FORCED = True


def build_retrying_session() -> requests.Session:
    _force_ipv4()
    retry = Retry(
        total=MAX_RETRIES,
        connect=MAX_RETRIES,
        read=MAX_RETRIES,
        status=MAX_RETRIES,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "POST"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = DefaultTimeoutSession(timeout=(CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS))
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({"Connection": "keep-alive"})
    return session


def validate_configuration() -> None:
    required_paths = [
        GOOGLE_SERVICE_ACCOUNT_FILE,
        FINANCE_GMAIL_OAUTH_CLIENT_SECRET_FILE,
        FINANCE_TEMPLATE_FILE,
        FINANCE_CV_FILE,
    ]
    missing_paths = [str(path) for path in required_paths if not Path(path).exists()]
    if missing_paths:
        raise FileNotFoundError(f"Missing required finance mailer files: {', '.join(missing_paths)}")

    if not SOURCE_SHEET_URL.strip():
        raise ValueError("SOURCE_SHEET_URL is required in finance_config.py")
    if not FINANCE_SENDER_EMAIL.strip():
        raise ValueError("FINANCE_SENDER_EMAIL is required in finance_config.py")


def get_sheets_client() -> gspread.Client:
    credentials = ServiceAccountCredentials.from_service_account_file(
        str(GOOGLE_SERVICE_ACCOUNT_FILE),
        scopes=SHEETS_SCOPES,
    )
    return gspread.authorize(credentials)


def get_gmail_credentials() -> Credentials:
    token_path = Path(FINANCE_GMAIL_TOKEN_FILE)
    client_secret_path = Path(FINANCE_GMAIL_OAUTH_CLIENT_SECRET_FILE)
    request_session = build_retrying_session()
    auth_request = Request(session=request_session)
    credentials: Optional[Credentials] = None

    if token_path.exists():
        credentials = Credentials.from_authorized_user_file(str(token_path), GMAIL_SEND_SCOPE)

    if credentials and credentials.expired and credentials.refresh_token:
        try:
            credentials.refresh(auth_request)
            token_path.parent.mkdir(parents=True, exist_ok=True)
            token_path.write_text(credentials.to_json(), encoding="utf-8")
        except (RefreshError, TransportError, requests.RequestException) as exc:
            if isinstance(exc, RefreshError) and "invalid_grant" in str(exc).lower():
                token_path.unlink(missing_ok=True)
                raise RuntimeError(
                    "Finance Gmail token expired or was revoked. "
                    "Run the finance mailer manually once to complete OAuth again."
                ) from exc
            raise RuntimeError("Failed to refresh finance Gmail credentials.") from exc
    elif not credentials or not credentials.valid:
        if not sys.stdin.isatty():
            raise RuntimeError(
                "Finance Gmail OAuth is required, but no valid token exists and this run is non-interactive. "
                "Run the finance mailer manually once to complete OAuth."
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_path), GMAIL_SEND_SCOPE)
        credentials = flow.run_local_server(port=0)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(credentials.to_json(), encoding="utf-8")

    return credentials


def build_gmail_message(
    sender_email: str,
    to_email: str,
    subject: str,
    html_body: str,
    text_body: str,
    attachment_path: Path,
    reply_to: str = "",
) -> Dict[str, str]:
    message = EmailMessage()
    message["To"] = to_email
    message["From"] = sender_email
    message["Subject"] = subject
    if reply_to.strip():
        message["Reply-To"] = reply_to

    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")

    mime_type, _ = mimetypes.guess_type(attachment_path.name)
    maintype, subtype = (mime_type or "application/octet-stream").split("/", 1)
    message.add_attachment(
        attachment_path.read_bytes(),
        maintype=maintype,
        subtype=subtype,
        filename=attachment_path.name,
    )

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    return {"raw": raw}


def send_email_via_gmail_api(
    credentials: Credentials,
    to_email: str,
    subject: str,
    html_body: str,
    text_body: str,
) -> None:
    session = build_retrying_session()
    auth_request = Request(session=session)
    authed_session = AuthorizedSession(credentials=credentials, auth_request=auth_request)
    authed_session.timeout = (CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS)

    message = build_gmail_message(
        sender_email=FINANCE_SENDER_EMAIL,
        to_email=to_email,
        subject=subject,
        html_body=html_body,
        text_body=text_body,
        attachment_path=Path(FINANCE_CV_FILE),
        reply_to=FINANCE_REPLY_TO,
    )

    for attempt in range(1, FINANCE_MAX_SEND_RETRIES + 1):
        response = authed_session.post(
            GMAIL_SEND_URL,
            json=message,
            timeout=(CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS),
        )
        if response.status_code < 400:
            return

        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "").strip()
            try:
                wait_seconds = max(float(retry_after), FINANCE_SECONDS_BETWEEN_EMAILS)
            except ValueError:
                wait_seconds = FINANCE_SECONDS_BETWEEN_EMAILS * (2 ** attempt)

            LOGGER.warning(
                "Gmail API rate limited send to %s on attempt %s/%s. Waiting %.1f seconds.",
                to_email,
                attempt,
                FINANCE_MAX_SEND_RETRIES,
                wait_seconds,
            )
            if attempt >= FINANCE_MAX_SEND_RETRIES:
                raise FinanceRateLimitError(
                    f"Gmail API rate limit persisted after {FINANCE_MAX_SEND_RETRIES} attempts."
                )
            time.sleep(wait_seconds)
            continue

        response.raise_for_status()

    raise FinanceRateLimitError("Gmail API rate limit persisted after retries.")


def get_source_worksheet(client: gspread.Client):
    spreadsheet = client.open_by_url(SOURCE_SHEET_URL)
    return spreadsheet.worksheet(SOURCE_WORKSHEET_NAME)


def get_tracking_worksheet(client: gspread.Client):
    if TRACKING_SPREADSHEET_URL.strip():
        spreadsheet = client.open_by_url(TRACKING_SPREADSHEET_URL.strip())
    else:
        try:
            spreadsheet = client.open(TRACKING_SPREADSHEET_TITLE)
        except gspread.SpreadsheetNotFound:
            try:
                spreadsheet = client.create(TRACKING_SPREADSHEET_TITLE)
                try:
                    spreadsheet.share(FINANCE_SENDER_EMAIL, perm_type="user", role="writer", notify=False)
                except Exception:
                    LOGGER.warning("Could not share Finance Jobs spreadsheet with %s", FINANCE_SENDER_EMAIL)
            except gspread.exceptions.APIError as exc:
                raise RuntimeError(
                    "Could not create the 'Finance Jobs' spreadsheet because Google Drive returned a quota error. "
                    "Create the sheet manually, share it with the service account, and set TRACKING_SPREADSHEET_URL "
                    "in finance_config.py."
                ) from exc

    try:
        worksheet = spreadsheet.worksheet(TRACKING_WORKSHEET_TITLE)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(title=TRACKING_WORKSHEET_TITLE, rows=1000, cols=len(TRACKING_HEADERS))

    current_header = worksheet.row_values(1)
    if current_header[: len(TRACKING_HEADERS)] != list(TRACKING_HEADERS):
        end_cell = gspread.utils.rowcol_to_a1(1, len(TRACKING_HEADERS))
        worksheet.update(range_name=f"A1:{end_cell}", values=[list(TRACKING_HEADERS)])
    return worksheet


def normalize_header(value: str) -> str:
    return value.strip().lower().replace(" ", "_")


def get_records(worksheet) -> List[Dict[str, str]]:
    values = worksheet.get_all_values()
    if not values:
        return []

    headers = [normalize_header(item) for item in values[0]]
    records: List[Dict[str, str]] = []
    for row in values[1:]:
        record: Dict[str, str] = {}
        for index, header in enumerate(headers):
            record[header] = row[index] if index < len(row) else ""
        records.append(record)
    return records


def get_records_with_row_numbers(worksheet) -> List[Dict[str, str]]:
    values = worksheet.get_all_values()
    if not values:
        return []

    headers = [normalize_header(item) for item in values[0]]
    records: List[Dict[str, str]] = []
    for row_index, row in enumerate(values[1:], start=2):
        record: Dict[str, str] = {"_row_number": str(row_index)}
        for index, header in enumerate(headers):
            record[header] = row[index] if index < len(row) else ""
        records.append(record)
    return records


def text_to_bodies(body: str) -> Tuple[str, str]:
    has_html = bool(re.search(r"<[^>]+>", body))
    if has_html:
        plain_body = re.sub(r"(?i)<br\s*/?>", "\n", body)
        plain_body = re.sub(r"(?i)</p>", "\n", plain_body)
        plain_body = re.sub(r"<[^>]+>", "", plain_body)
        plain_body = html.unescape(plain_body).strip()
        html_body = body.replace("\r\n", "\n").replace("\n", "<br>\n")
    else:
        plain_body = body
        html_body = "<html><body>" + html.escape(body).replace("\n", "<br>\n") + "</body></html>"
    return plain_body, html_body


def format_email_body(template: str, row: Dict[str, str]) -> Tuple[str, str]:
    body = template.format(
        company=row.get("company", "").strip() or "Company",
        role=row.get("role", "").strip() or "Role",
        location=row.get("location", "").strip() or "Location",
        contact_email=row.get("contact_email", "").strip(),
    )
    return text_to_bodies(body)


def successful_contacts(records: Sequence[Dict[str, str]]) -> set[str]:
    contacts = set()
    for record in records:
        contact_email = record.get("contact_email", "").strip().lower()
        status = record.get("outreach_status", "").strip().lower()
        if contact_email and status == "sent":
            contacts.add(contact_email)
    return contacts


def get_tracking_column_indexes(worksheet) -> Dict[str, int]:
    headers = [normalize_header(value) for value in worksheet.row_values(1)]
    return {header: index + 1 for index, header in enumerate(headers)}


def sync_source_to_tracking(worksheet, source_records: Sequence[Dict[str, str]]) -> int:
    existing_records = get_records(worksheet)
    existing_contacts = {
        record.get("contact_email", "").strip().lower()
        for record in existing_records
        if record.get("contact_email", "").strip()
    }

    rows_to_add: List[List[str]] = []
    batch_seen = set()
    for record in source_records:
        contact_email = record.get("contact_email", "").strip().lower()
        if not contact_email or not is_valid_email(contact_email):
            continue
        if contact_email in existing_contacts or contact_email in batch_seen:
            continue

        batch_seen.add(contact_email)
        rows_to_add.append(
            [
                record.get("date", "").strip(),
                record.get("company", "").strip(),
                record.get("location", "").strip(),
                contact_email,
                "",
                "",
            ]
        )

    if rows_to_add:
        worksheet.append_rows(rows_to_add, value_input_option="RAW")
    return len(rows_to_add)


def update_tracking_row_status(
    worksheet,
    row_number: int,
    column_indexes: Dict[str, int],
    status: str,
    attempted_at: datetime,
) -> None:
    status_cell = gspread.utils.rowcol_to_a1(row_number, column_indexes["outreach_status"])
    sent_at_cell = gspread.utils.rowcol_to_a1(row_number, column_indexes["sent_at"])
    worksheet.update_acell(status_cell, status)
    worksheet.update_acell(sent_at_cell, attempted_at.strftime("%Y-%m-%d %H:%M:%S"))


def load_template() -> str:
    return Path(FINANCE_TEMPLATE_FILE).read_text(encoding="utf-8")


def is_valid_email(value: str) -> bool:
    return bool(EMAIL_PATTERN.match((value or "").strip()))


def eligible_source_rows(source_records: Sequence[Dict[str, str]], sent_contacts: set[str]) -> List[Dict[str, str]]:
    candidates: List[Dict[str, str]] = []
    batch_seen = set()
    invalid_contacts = 0

    for row in source_records:
        contact_email = row.get("contact_email", "").strip().lower()
        if not contact_email:
            continue
        if not is_valid_email(contact_email):
            invalid_contacts += 1
            continue
        if contact_email in sent_contacts or contact_email in batch_seen:
            continue
        batch_seen.add(contact_email)
        candidates.append(row)

    if invalid_contacts:
        LOGGER.warning("Skipped %s source row(s) with invalid contact email values.", invalid_contacts)
    return candidates


def pending_tracking_rows(tracking_records: Sequence[Dict[str, str]]) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for record in tracking_records:
        contact_email = record.get("contact_email", "").strip().lower()
        if not contact_email or not is_valid_email(contact_email):
            continue
        if record.get("outreach_status", "").strip().lower() == "sent":
            continue
        rows.append(record)
    return rows


def build_source_lookup(source_records: Sequence[Dict[str, str]]) -> Dict[str, Dict[str, str]]:
    lookup: Dict[str, Dict[str, str]] = {}
    for record in source_records:
        contact_email = record.get("contact_email", "").strip().lower()
        if not contact_email or not is_valid_email(contact_email):
            continue
        lookup.setdefault(contact_email, record)
    return lookup


def main() -> None:
    setup_logging()
    validate_configuration()
    template = load_template()

    sheets_client = get_sheets_client()
    source_worksheet = get_source_worksheet(sheets_client)
    tracking_worksheet = get_tracking_worksheet(sheets_client)

    source_records = get_records(source_worksheet)
    synced_count = sync_source_to_tracking(tracking_worksheet, source_records)
    tracking_records = get_records_with_row_numbers(tracking_worksheet)
    pending_rows = pending_tracking_rows(tracking_records)
    source_lookup = build_source_lookup(source_records)
    tracking_column_indexes = get_tracking_column_indexes(tracking_worksheet)
    gmail_credentials = get_gmail_credentials()
    if FINANCE_MAX_EMAILS_PER_RUN > 0:
        pending_rows = pending_rows[:FINANCE_MAX_EMAILS_PER_RUN]

    LOGGER.info("Finance mailer loaded %s source rows.", len(source_records))
    LOGGER.info("Finance mailer synced %s new row(s) into Finance Jobs.", synced_count)
    LOGGER.info("Finance mailer will attempt %s email(s).", len(pending_rows))

    sent_count = 0
    failed_count = 0
    consecutive_rate_limits = 0
    for row in pending_rows:
        row_number = int(row["_row_number"])
        company = row.get("company", "").strip()
        location = row.get("location", "").strip()
        contact_email = row.get("contact_email", "").strip().lower()
        source_row = source_lookup.get(contact_email, {})
        role = source_row.get("role", "").strip() or "Role"
        attempted_at = datetime.now()

        try:
            template_row = {
                "company": company,
                "location": location,
                "contact_email": contact_email,
                "role": role,
            }
            text_body, html_body = format_email_body(template, template_row)
            subject = FINANCE_SUBJECT_TEMPLATE.format(
                company=company or "Company",
                role=role,
            )
            send_email_via_gmail_api(
                credentials=gmail_credentials,
                to_email=contact_email,
                subject=subject,
                html_body=html_body,
                text_body=text_body,
            )
            update_tracking_row_status(
                tracking_worksheet,
                row_number=row_number,
                column_indexes=tracking_column_indexes,
                status="Sent",
                attempted_at=attempted_at,
            )
            sent_count += 1
            consecutive_rate_limits = 0
            LOGGER.info("Sent finance email to %s (%s).", contact_email, company or role)
            if FINANCE_SECONDS_BETWEEN_EMAILS > 0:
                time.sleep(FINANCE_SECONDS_BETWEEN_EMAILS)
        except FinanceRateLimitError as exc:
            update_tracking_row_status(
                tracking_worksheet,
                row_number=row_number,
                column_indexes=tracking_column_indexes,
                status="Failed",
                attempted_at=attempted_at,
            )
            failed_count += 1
            consecutive_rate_limits += 1
            LOGGER.error(
                "Gmail rate limited %s. Marked as Failed and continuing. Consecutive rate limits=%s. Error: %s",
                contact_email,
                consecutive_rate_limits,
                exc,
            )
            if consecutive_rate_limits >= FINANCE_MAX_CONSECUTIVE_RATE_LIMITS:
                LOGGER.error(
                    "Stopping finance mailer after %s consecutive Gmail rate limits.",
                    consecutive_rate_limits,
                )
                break
            if FINANCE_RATE_LIMIT_COOLDOWN_SECONDS > 0:
                time.sleep(FINANCE_RATE_LIMIT_COOLDOWN_SECONDS)
        except Exception as exc:
            update_tracking_row_status(
                tracking_worksheet,
                row_number=row_number,
                column_indexes=tracking_column_indexes,
                status="Failed",
                attempted_at=attempted_at,
            )
            failed_count += 1
            LOGGER.exception("Failed finance email to %s: %s", contact_email, exc)

    LOGGER.info("Finance mailer completed. Sent=%s Failed=%s", sent_count, failed_count)
    print(f"Finance mailer completed. Sent={sent_count}, Failed={failed_count}, Attempted={len(pending_rows)}")


if __name__ == "__main__":
    main()
