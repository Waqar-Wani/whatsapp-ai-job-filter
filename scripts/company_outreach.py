import json
import logging
import os
import smtplib
import argparse
import sys
import re
import html
from datetime import datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Dict, List, Tuple

import gspread
import httpx
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"
LOG_DIR = PROJECT_ROOT / "logs"
CONFIG_DIR = PROJECT_ROOT / "config"
TEMPLATE_DIR = PROJECT_ROOT / "templates"

LOG_FILE = str(LOG_DIR / "automation.log")
SENT_TRACKER_FILE = DATA_DIR / "sent_company_emails.json"
DEFAULT_WORKSHEET = "Filtered Jobs"
DEFAULT_TEMPLATE_FILE = str(TEMPLATE_DIR / "company_email_template.txt")
DEFAULT_SUBJECT_TEMPLATE = "Application for {role} - {company}"


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
        "GMAIL_USER",
        "GMAIL_APP_PASSWORD",
        "GOOGLE_SERVICE_ACCOUNT_FILE",
        "GOOGLE_SHEET_URL",
        "CV_FILE_PATH",
    ]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        raise ValueError(f"Missing env variables: {', '.join(missing)}")

    cfg = {
        "gmail_user": os.environ["GMAIL_USER"],
        "gmail_app_password": os.environ["GMAIL_APP_PASSWORD"],
        "service_account_file": os.environ["GOOGLE_SERVICE_ACCOUNT_FILE"],
        "sheet_url": os.environ["GOOGLE_SHEET_URL"],
        "worksheet_name": os.getenv("OUTREACH_WORKSHEET", DEFAULT_WORKSHEET),
        "template_file": os.getenv("OUTREACH_TEMPLATE_FILE", DEFAULT_TEMPLATE_FILE),
        "subject_template": os.getenv("OUTREACH_SUBJECT_TEMPLATE", DEFAULT_SUBJECT_TEMPLATE),
        "cv_file_path": os.environ["CV_FILE_PATH"],
    }
    # Resolve relative config/template/cv paths from project root.
    for key in ("service_account_file", "template_file", "cv_file_path"):
        p = Path(cfg[key])
        if not p.is_absolute():
            cfg[key] = str((PROJECT_ROOT / p).resolve())
    return cfg


def ensure_internet_connectivity(timeout_seconds: float = 8.0) -> None:
    test_urls = [
        "https://www.google.com/generate_204",
        "https://docs.google.com",
        "https://smtp.gmail.com",
    ]
    errors = []
    for url in test_urls:
        try:
            with httpx.Client(timeout=timeout_seconds, follow_redirects=True) as client:
                resp = client.get(url)
            if resp.status_code < 500:
                logging.info("Internet check passed via %s (status=%s)", url, resp.status_code)
                return
            errors.append(f"{url} -> HTTP {resp.status_code}")
        except Exception as exc:
            errors.append(f"{url} -> {exc}")

    raise RuntimeError(
        "Internet connectivity check failed for outreach flow. "
        f"Checks: {' | '.join(errors)}"
    )


def gspread_client(service_account_file: str) -> gspread.Client:
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(service_account_file, scopes=scopes)
    return gspread.authorize(creds)


def normalize_header(value: str) -> str:
    return value.strip().lower().replace(" ", "_")


def ensure_outreach_columns(worksheet) -> Dict[str, int]:
    headers = worksheet.row_values(1)
    normalized = [normalize_header(h) for h in headers]
    required = ["outreach_status", "outreach_sent_at", "outreach_error"]

    for col in required:
        if col not in normalized:
            headers.append(col.replace("_", " ").title())
            normalized.append(col)

    last_cell = gspread.utils.rowcol_to_a1(1, len(headers))
    worksheet.update(values=[headers], range_name=f"A1:{last_cell}")
    return {name: idx + 1 for idx, name in enumerate(normalized)}


def load_template(path: str) -> str:
    p = Path(path)
    if not p.exists():
        default = (
            "Hi Hiring Team,\n\n"
            "I am interested in the {role} opportunity at {company}.\n"
            "I have experience in QA, automation testing, API testing, and Playwright.\n\n"
            "Location preference: {location}\n"
            "Experience fit: {experience}\n"
            "Relevant skills: {skills}\n\n"
            "Please find my CV attached.\n\n"
            "Best regards,\n"
            "{sender_name}\n"
        )
        p.write_text(default, encoding="utf-8")
        return default
    return p.read_text(encoding="utf-8")


def load_sent_tracker() -> Dict[str, str]:
    if not SENT_TRACKER_FILE.exists():
        return {}
    try:
        return json.loads(SENT_TRACKER_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_sent_tracker(data: Dict[str, str]) -> None:
    SENT_TRACKER_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def row_unique_key(row: Dict[str, str]) -> str:
    return "|".join(
        [
            row.get("date", "").strip().lower(),
            row.get("company", "").strip().lower(),
            row.get("role", "").strip().lower(),
            row.get("contact_email", "").strip().lower(),
        ]
    )


def compose_email(
    sender_email: str,
    recipient_email: str,
    subject: str,
    body: str,
    cv_file_path: str,
) -> MIMEMultipart:
    msg = MIMEMultipart("mixed")
    msg["From"] = sender_email
    msg["To"] = recipient_email
    msg["Subject"] = subject

    def _looks_like_html(text: str) -> bool:
        return bool(re.search(r"<[^>]+>", text))

    def _html_to_plain(text: str) -> str:
        plain = re.sub(r"(?i)<br\s*/?>", "\n", text)
        plain = re.sub(r"(?i)</p>", "\n", plain)
        plain = re.sub(r"<[^>]+>", "", plain)
        return html.unescape(plain).strip()

    def _preserve_newlines_in_html(text: str) -> str:
        # Gmail collapses raw newlines in HTML, so convert template line breaks to <br>.
        return text.replace("\r\n", "\n").replace("\n", "<br>\n")

    if _looks_like_html(body):
        plain_body = _html_to_plain(body)
        html_body = _preserve_newlines_in_html(body)
    else:
        plain_body = body
        html_body = "<html><body>" + html.escape(body).replace("\n", "<br>\n") + "</body></html>"

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(plain_body, "plain", "utf-8"))
    alt.attach(MIMEText(html_body, "html", "utf-8"))
    msg.attach(alt)

    with open(cv_file_path, "rb") as f:
        attachment = MIMEApplication(f.read(), _subtype="pdf")
    attachment.add_header("Content-Disposition", "attachment", filename=Path(cv_file_path).name)
    msg.attach(attachment)
    return msg


def send_email(gmail_user: str, app_password: str, msg: MIMEMultipart) -> None:
    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(gmail_user, app_password)
        server.sendmail(gmail_user, [msg["To"]], msg.as_string())


def get_records_with_rows(worksheet) -> Tuple[List[Dict[str, str]], Dict[str, int]]:
    headers = worksheet.row_values(1)
    norm = [normalize_header(h) for h in headers]
    values = worksheet.get_all_values()
    records: List[Dict[str, str]] = []

    for idx, row in enumerate(values[1:], start=2):
        row_map: Dict[str, str] = {}
        for cidx, col in enumerate(norm):
            row_map[col] = row[cidx] if cidx < len(row) else ""
        row_map["_row_number"] = str(idx)
        records.append(row_map)
    return records, {name: i + 1 for i, name in enumerate(norm)}


def mark_row(worksheet, row_num: int, col_idx: int, value: str) -> None:
    cell = gspread.utils.rowcol_to_a1(row_num, col_idx)
    worksheet.update_acell(cell, value)


def main() -> None:
    parser = argparse.ArgumentParser(description="Send outreach emails from Google Sheet.")
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Maximum number of emails to send in this run (0 = no limit).",
    )
    args = parser.parse_args()

    setup_logging()
    cfg = load_config()
    ensure_internet_connectivity()

    client = gspread_client(cfg["service_account_file"])
    spreadsheet = client.open_by_url(cfg["sheet_url"])
    worksheet = spreadsheet.worksheet(cfg["worksheet_name"])
    col_idx = ensure_outreach_columns(worksheet)

    template = load_template(cfg["template_file"])
    sent_tracker = load_sent_tracker()

    records, sheet_cols = get_records_with_rows(worksheet)
    to_send = []
    for row in records:
        contact = row.get("contact_email", "").strip()
        if not contact:
            continue
        if row.get("outreach_sent_at", "").strip():
            continue
        key = row_unique_key(row)
        if key in sent_tracker:
            continue
        to_send.append(row)

    if args.limit and args.limit > 0:
        to_send = to_send[: args.limit]

    logging.info("Outreach candidates: %s", len(to_send))

    sent_count = 0
    for row in to_send:
        row_num = int(row["_row_number"])
        key = row_unique_key(row)
        company = row.get("company", "").strip() or "Company"
        role = row.get("role", "").strip() or "Role"
        location = row.get("location", "").strip() or "N/A"
        experience = row.get("experience", "").strip() or "N/A"
        skills = row.get("skills", "").strip() or "N/A"
        contact = row.get("contact_email", "").strip()

        try:
            subject = cfg["subject_template"].format(company=company, role=role)
            body = template.format(
                company=company,
                role=role,
                location=location,
                experience=experience,
                skills=skills,
                sender_name=cfg["gmail_user"].split("@")[0],
            )
            msg = compose_email(
                sender_email=cfg["gmail_user"],
                recipient_email=contact,
                subject=subject,
                body=body,
                cv_file_path=cfg["cv_file_path"],
            )
            send_email(cfg["gmail_user"], cfg["gmail_app_password"], msg)

            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            mark_row(worksheet, row_num, col_idx["outreach_status"], "SENT")
            mark_row(worksheet, row_num, col_idx["outreach_sent_at"], now)
            mark_row(worksheet, row_num, col_idx["outreach_error"], "")
            sent_tracker[key] = now
            sent_count += 1
            logging.info("Sent outreach email to %s (%s - %s)", contact, company, role)
        except Exception as exc:
            err = str(exc)[:450]
            mark_row(worksheet, row_num, col_idx["outreach_status"], "FAILED")
            mark_row(worksheet, row_num, col_idx["outreach_error"], err)
            logging.exception("Failed outreach to %s: %s", contact, exc)

    save_sent_tracker(sent_tracker)
    logging.info("Outreach completed. Sent=%s", sent_count)
    print(f"Outreach completed. Sent={sent_count}, Candidates={len(to_send)}")


if __name__ == "__main__":
    main()
