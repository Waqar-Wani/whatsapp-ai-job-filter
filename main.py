import json
import logging
import os
import re
import smtplib
import subprocess
import sys
import time
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Dict, List, Optional

import gspread
import httpx
import pandas as pd
from dotenv import load_dotenv
from google.auth.exceptions import GoogleAuthError
from google.oauth2.service_account import Credentials
from playwright.sync_api import BrowserContext, Page, TimeoutError, sync_playwright


GROUP_NAME = "Qa Paid Experience"
SPREADSHEET_TITLE = "Filtered Jobs"
WORKSHEET_TITLE = "Filtered Jobs"
PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
LOG_DIR = PROJECT_ROOT / "logs"
SESSION_DIR = str(DATA_DIR / "whatsapp_session")
LAST_PROCESSED_FILE = DATA_DIR / "last_processed.json"
TEMP_SCRAPED_FILE = DATA_DIR / "whatsapp_scraped_temp.json"
LOG_FILE = str(LOG_DIR / "automation.log")
SUMMARY_RECIPIENT = "vickywaqar111@gmail.com"
DEFAULT_SHEET_URL = "https://docs.google.com/spreadsheets/d/1R5HHz-q7XYZ-AhVpO_Rv-40W7XiJYelBXKHQH3omAhc/edit?gid=0#gid=0"
OUTREACH_SCRIPT = str(PROJECT_ROOT / "scripts" / "company_outreach.py")

# Update these based on your real CV profile.
CV_KEYWORDS = [
    "qa",
    "quality assurance",
    "software testing",
    "automation testing",
    "playwright",
    "selenium",
    "api testing",
    "python",
    "manual testing",
    "test engineer",
]


def setup_logging() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()

    file_handler = logging.FileHandler(LOG_FILE)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)


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


def wait_for_whatsapp_login(page: Page) -> None:
    logging.info("Step: Waiting for WhatsApp login/session.")
    try:
        page.wait_for_selector("div[aria-label='Chat list']", timeout=120000)
        logging.info("Step: WhatsApp session is active.")
        return
    except TimeoutError:
        logging.info("WhatsApp chat list not found yet. Waiting for manual QR login.")

    # Extra wait for first-time QR scan.
    page.wait_for_selector("div[aria-label='Chat list']", timeout=300000)
    logging.info("Step: Manual QR login completed.")


def find_search_input(page: Page):
    selectors = [
        "div[role='textbox'][aria-label='Search input textbox']",
        "div[contenteditable='true'][data-tab='3']",
        "div[contenteditable='true'][data-tab='10']",
    ]
    for selector in selectors:
        locator = page.locator(selector).first
        if locator.count() > 0:
            return locator
    raise RuntimeError("Could not find WhatsApp search input.")


def open_target_group(page: Page, group_name: str) -> None:
    logging.info("Step: Searching for WhatsApp group '%s'.", group_name)
    search_input = find_search_input(page)
    search_input.click()
    search_input.fill("")
    search_input.type(group_name, delay=50)
    page.keyboard.press("Enter")
    page.wait_for_timeout(2500)
    logging.info("Step: Group '%s' opened.", group_name)


def parse_pre_plain_text(pre_plain_text: str) -> Optional[Dict[str, Any]]:
    # Typical format: [12:34 PM, 2/25/2026] Sender Name:
    match = re.match(
        r"^\[(?P<time>[^,\]]+),\s(?P<date>[^\]]+)\]\s(?P<sender>.*?):\s?$",
        pre_plain_text.strip(),
    )
    if not match:
        return None

    time_part = match.group("time").strip()
    date_part = match.group("date").strip()
    sender = match.group("sender").strip()
    combined = f"{date_part} {time_part}"

    date_formats = [
        "%m/%d/%Y %I:%M %p",
        "%d/%m/%Y %I:%M %p",
        "%m/%d/%y %I:%M %p",
        "%d/%m/%y %I:%M %p",
        "%m/%d/%Y %H:%M",
        "%d/%m/%Y %H:%M",
        "%m/%d/%y %H:%M",
        "%d/%m/%y %H:%M",
    ]
    parsed_dt = None
    for fmt in date_formats:
        try:
            parsed_dt = datetime.strptime(combined, fmt)
            break
        except ValueError:
            continue

    if not parsed_dt:
        return None

    return {"sender": sender, "timestamp": parsed_dt}


def scrape_messages(page: Page) -> List[Dict[str, Any]]:
    logging.info("Step: Scraping currently loaded WhatsApp messages from chat view.")
    # Extract all currently loaded message bubbles with sender/time metadata.
    raw_messages = page.evaluate(
        """
        () => {
          const items = [];
          const nodes = document.querySelectorAll("div[data-pre-plain-text]");
          nodes.forEach((node) => {
            const pre = node.getAttribute("data-pre-plain-text") || "";
            const textParts = [];
            const spans = node.querySelectorAll("span.selectable-text span");
            spans.forEach((s) => {
              const txt = (s.innerText || "").trim();
              if (txt) textParts.push(txt);
            });
            if (!textParts.length) {
              const fallback = (node.innerText || "").trim();
              if (fallback) textParts.push(fallback);
            }
            items.push({
              pre_plain_text: pre,
              text: textParts.join("\\n").trim(),
            });
          });
          return items;
        }
        """
    )

    parsed_messages: List[Dict[str, Any]] = []
    for item in raw_messages:
        parsed = parse_pre_plain_text(item.get("pre_plain_text", ""))
        text = (item.get("text") or "").strip()
        if not parsed or not text:
            continue
        parsed_messages.append(
            {
                "sender": parsed["sender"],
                "timestamp": parsed["timestamp"],
                "text": text,
            }
        )

    parsed_messages.sort(key=lambda m: m["timestamp"])
    logging.info("Step: Scraped %s messages from current viewport.", len(parsed_messages))
    return parsed_messages


def expand_truncated_messages(page: Page) -> int:
    # Click "Read more" controls so long WhatsApp messages are fully expanded.
    expanded = page.evaluate(
        """
        () => {
          const candidates = Array.from(document.querySelectorAll("button, div[role='button'], span"));
          let clicked = 0;

          for (const el of candidates) {
            const txt = (el.textContent || "").trim().toLowerCase();
            if (!txt) continue;

            const isReadMore =
              txt === "read more" ||
              txt.endsWith("read more") ||
              txt.includes("...read more");

            if (!isReadMore) continue;
            if (!(el instanceof HTMLElement)) continue;

            const style = window.getComputedStyle(el);
            if (style.display === "none" || style.visibility === "hidden") continue;

            el.click();
            clicked += 1;
          }
          return clicked;
        }
        """
    )
    return int(expanded or 0)


def scroll_chat_up(page: Page) -> Dict[str, Any]:
    return page.evaluate(
        """
        () => {
          const all = Array.from(document.querySelectorAll("div"));
          const candidates = all.filter((el) => {
            const style = window.getComputedStyle(el);
            const overflowY = style.overflowY;
            const canScroll = (overflowY === "auto" || overflowY === "scroll");
            const hasMessages = !!el.querySelector("div[data-pre-plain-text]");
            return canScroll && el.scrollHeight > el.clientHeight && hasMessages;
          });

          if (!candidates.length) {
            return { found: false };
          }

          // Pick the largest scrollable container that contains message bubbles.
          const container = candidates.sort((a, b) => b.scrollHeight - a.scrollHeight)[0];
          const before = container.scrollTop;
          const step = Math.max(300, Math.floor(container.clientHeight * 0.9));
          container.scrollTop = Math.max(0, before - step);
          const after = container.scrollTop;

          return {
            found: true,
            before,
            after,
            at_top: after <= 0,
            scroll_height: container.scrollHeight,
            client_height: container.clientHeight,
          };
        }
        """
    )


def scrape_all_loaded_messages(page: Page, scroll_duration_seconds: int = 30) -> List[Dict[str, Any]]:
    logging.info(
        "Step: Starting scroll-back to load older WhatsApp messages for %s seconds.",
        scroll_duration_seconds,
    )
    all_messages: List[Dict[str, Any]] = []
    previous_count = 0
    start_time = time.time()
    round_idx = 0

    while (time.time() - start_time) < scroll_duration_seconds:
        round_idx += 1
        expanded_now = expand_truncated_messages(page)
        if expanded_now:
            logging.info("Step: Expanded %s truncated message(s).", expanded_now)
            page.wait_for_timeout(250)
        batch = scrape_messages(page)
        all_messages.extend(batch)

        unique_count = len(deduplicate_messages(all_messages))
        previous_count = unique_count

        metrics = scroll_chat_up(page)
        elapsed = int(time.time() - start_time)
        logging.info(
            "Step: Scroll round %s | elapsed=%ss | unique_messages=%s | at_top=%s",
            round_idx,
            elapsed,
            unique_count,
            metrics.get("at_top"),
        )

        if not metrics.get("found"):
            logging.info("Step: Could not find chat scroll container. Stopping scroll loop.")
            break
        if metrics.get("at_top"):
            logging.info("Step: Reached top of chat history.")
            break

        page.wait_for_timeout(900)

    # Final expansion pass at current viewport before finishing.
    expanded_final = expand_truncated_messages(page)
    if expanded_final:
        logging.info("Step: Final expansion clicked %s message(s).", expanded_final)
        page.wait_for_timeout(250)

    deduped = deduplicate_messages(all_messages)
    deduped.sort(key=lambda m: m["timestamp"])
    logging.info("Step: Total unique messages after scroll-back: %s", len(deduped))
    return deduped


def get_all_messages(group_name: str) -> List[Dict[str, Any]]:
    logging.info("Step: Launching Playwright persistent context.")
    with sync_playwright() as playwright:
        context: BrowserContext = playwright.chromium.launch_persistent_context(
            user_data_dir=SESSION_DIR,
            headless=False,
        )
        page = context.pages[0] if context.pages else context.new_page()

        logging.info("Step: Opening https://web.whatsapp.com")
        page.goto("https://web.whatsapp.com", wait_until="domcontentloaded")
        wait_for_whatsapp_login(page)
        open_target_group(page, group_name)

        # Give WhatsApp time to hydrate message nodes.
        page.wait_for_timeout(2500)
        messages = scrape_all_loaded_messages(page)
        logging.info("Step: Closing Playwright browser context.")
        context.close()

    return messages


def clean_key(value: Optional[str]) -> str:
    key = (value or "").strip()
    if not key or key.lower() in {"replace_me", "none", "null"}:
        return ""
    return key


def call_openrouter_api(
    key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    site_url: str,
    site_name: str,
) -> str:
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if site_url:
        headers["HTTP-Referer"] = site_url
    if site_name:
        headers["X-OpenRouter-Title"] = site_name

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0,
    }
    with httpx.Client(timeout=30) as client:
        response = client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
    try:
        return data["choices"][0]["message"]["content"]
    except Exception:
        return json.dumps(data)


def analyze_job_post(
    text: str,
    openrouter_key: str,
    openrouter_model: str,
    openrouter_site_url: str,
    openrouter_site_name: str,
    retries: int = 3,
    initial_delay: float = 2.0,
) -> Dict[str, Any]:
    schema_template = {
        "relevant": False,
        "company": "",
        "role": "",
        "location": "",
        "experience": "",
        "skills": "",
        "contact_email": "",
    }

    system_prompt = "Return valid JSON only. No markdown. No extra keys."
    user_prompt = (
        "You are an assistant that filters WhatsApp job posts.\n"
        f"CV keywords: {CV_KEYWORDS}\n"
        "Return JSON ONLY with keys exactly as:\n"
        '{ "relevant": true/false, "company": "", "role": "", "location": "", '
        '"experience": "", "skills": "", "contact_email": "" }\n'
        "If not a job post or not relevant to keywords, set relevant=false.\n"
        f"Job post text:\n{text}"
    )

    or_key = clean_key(openrouter_key)
    if not or_key:
        raise RuntimeError("No LLM API key configured (OPENROUTER_API_KEY)")

    for attempt in range(1, retries + 1):
        try:
            logging.info("Step: AI analysis attempt %s via OpenRouter.", attempt)
            content = call_openrouter_api(
                key=or_key,
                model=openrouter_model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                site_url=openrouter_site_url,
                site_name=openrouter_site_name,
            )
            payload = json.loads(content)

            result = {**schema_template, **payload}
            result["relevant"] = bool(result.get("relevant", False))
            logging.info("Step: AI analysis completed. relevant=%s", result["relevant"])
            return result
        except Exception as exc:
            logging.exception("AI analysis failed on attempt %s: %s", attempt, exc)
            if attempt >= retries:
                return schema_template
            sleep_seconds = initial_delay * (2 ** (attempt - 1))
            time.sleep(sleep_seconds)

    return schema_template


def get_gspread_client(service_account_file: str) -> gspread.Client:
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(service_account_file, scopes=scopes)
    return gspread.authorize(creds)


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
            # Common on personal Gmail + service accounts where ownership transfer is restricted.
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

    headers = [
        "Date",
        "Company",
        "Role",
        "Location",
        "Experience",
        "Skills",
        "Contact Email",
    ]
    current_header = worksheet.row_values(1)
    if current_header != headers:
        worksheet.update("A1:G1", [headers])

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
            ]
        )
    if rows:
        worksheet.append_rows(rows, value_input_option="USER_ENTERED")


def message_dedup_key(message: Dict[str, Any]) -> str:
    return (
        f"{message['sender']}|"
        f"{message['timestamp'].isoformat()}|"
        f"{message['text'].strip()}"
    )


def deduplicate_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    deduped: List[Dict[str, Any]] = []
    for message in messages:
        key = message_dedup_key(message)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(message)
    return deduped


def job_dedup_key(job: Dict[str, Any]) -> str:
    return (
        f"{job['date']}|{job['company']}|{job['role']}|"
        f"{job['location']}|{job['experience']}|{job['skills']}|{job['contact_email']}"
    ).strip().lower()


def deduplicate_jobs_for_sheet(worksheet, jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not jobs:
        return []

    existing_rows = worksheet.get_all_values()
    existing_keys = set()
    for row in existing_rows[1:]:
        if len(row) < 7:
            continue
        existing_keys.add(
            (f"{row[0]}|{row[1]}|{row[2]}|{row[3]}|{row[4]}|{row[5]}|{row[6]}").strip().lower()
        )

    unique_jobs: List[Dict[str, Any]] = []
    batch_seen = set()
    for job in jobs:
        key = job_dedup_key(job)
        if key in existing_keys or key in batch_seen:
            continue
        batch_seen.add(key)
        unique_jobs.append(job)

    return unique_jobs


def build_email_body(jobs: List[Dict[str, Any]]) -> str:
    df = pd.DataFrame(jobs)
    lines = [f"Total new relevant jobs: {len(df)}", ""]
    for idx, row in df.iterrows():
        lines.append(
            (
                f"{idx + 1}. {row['role']} at {row['company']}\n"
                f"   Date: {row['date']}\n"
                f"   Sender: {row['sender']}\n"
                f"   Location: {row['location']}\n"
                f"   Experience: {row['experience']}\n"
                f"   Skills: {row['skills']}\n"
                f"   Contact Email: {row['contact_email']}\n"
            )
        )
    return "\n".join(lines)


def send_email_summary(
    gmail_user: str,
    gmail_app_password: str,
    recipient: str,
    jobs: List[Dict[str, Any]],
) -> None:
    msg = MIMEMultipart()
    msg["From"] = gmail_user
    msg["To"] = recipient
    msg["Subject"] = "New Filtered Jobs - Qa Paid Experience"
    msg.attach(MIMEText(build_email_body(jobs), "plain"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(gmail_user, gmail_app_password)
        server.sendmail(gmail_user, recipient, msg.as_string())


def run_outreach_task() -> None:
    enabled = (os.getenv("RUN_OUTREACH_ON_MAIN", "true") or "").strip().lower()
    if enabled not in {"1", "true", "yes"}:
        logging.info("Step: Outreach task skipped (RUN_OUTREACH_ON_MAIN=%s).", enabled)
        return

    script_path = Path(OUTREACH_SCRIPT)
    if not script_path.exists():
        logging.warning("Step: Outreach script not found at %s. Skipping outreach.", script_path)
        return

    logging.info("Step: Running outreach task via %s", OUTREACH_SCRIPT)
    result = subprocess.run(
        [sys.executable, OUTREACH_SCRIPT],
        capture_output=True,
        text=True,
    )
    if result.stdout.strip():
        logging.info("Outreach stdout: %s", result.stdout.strip())
    if result.stderr.strip():
        logging.warning("Outreach stderr: %s", result.stderr.strip())
    logging.info("Step: Outreach task completed with return code %s.", result.returncode)


def main() -> None:
    setup_logging()
    logging.info("==============================================")
    logging.info("Starting WhatsApp job automation run.")
    logging.info("Step 1/9: Validating environment configuration.")

    config = validate_env()
    logging.info("Step 2/9: Loading last processed timestamp.")
    last_processed = load_last_processed_timestamp()
    logging.info("Last processed timestamp: %s", last_processed)

    logging.info("Step 3/9: Scraping WhatsApp messages.")
    all_messages = get_all_messages(GROUP_NAME)
    save_temp_scraped_messages(all_messages)
    logging.info("Saved %s scraped messages to %s", len(all_messages), TEMP_SCRAPED_FILE)
    if not all_messages:
        logging.info("No messages found.")
        run_outreach_task()
        return

    logging.info("Step 4/9: Deduplicating scraped messages.")
    deduped_messages = deduplicate_messages(all_messages)
    if last_processed:
        messages_to_analyze = [m for m in deduped_messages if m["timestamp"] > last_processed]
    else:
        messages_to_analyze = deduped_messages

    if not messages_to_analyze:
        logging.info("No new messages after last processed timestamp.")
        run_outreach_task()
        return

    logging.info(
        "Step 5/9: Running AI filtering for %s message(s).",
        len(messages_to_analyze),
    )
    relevant_jobs: List[Dict[str, Any]] = []

    for msg in messages_to_analyze:
        ai_result = analyze_job_post(
            text=msg["text"],
            openrouter_key=config["openrouter_api_key"],
            openrouter_model=config["openrouter_model"],
            openrouter_site_url=config["openrouter_site_url"],
            openrouter_site_name=config["openrouter_site_name"],
        )
        if not ai_result.get("relevant"):
            continue

        skills_value = ai_result.get("skills", "")
        if isinstance(skills_value, list):
            skills_value = ", ".join(str(x) for x in skills_value if str(x).strip())

        relevant_jobs.append(
            {
                "date": msg["timestamp"].strftime("%Y-%m-%d %H:%M"),
                "sender": msg["sender"],
                "company": ai_result.get("company", ""),
                "role": ai_result.get("role", ""),
                "location": ai_result.get("location", ""),
                "experience": ai_result.get("experience", ""),
                "skills": str(skills_value).strip(),
                "contact_email": ai_result.get("contact_email", ""),
            }
        )

    if relevant_jobs:
        logging.info("Step 6/9: Connecting to Google Sheets.")
        sheets_client = get_gspread_client(config["service_account_file"])
        worksheet = ensure_sheet(
            sheets_client,
            config["gmail_user"],
            config["google_sheet_url"],
        )
        logging.info("Step 7/9: Deduplicating jobs before sheet append.")
        unique_jobs = deduplicate_jobs_for_sheet(worksheet, relevant_jobs)
        if unique_jobs:
            logging.info("Step 8/9: Appending %s unique jobs to sheet.", len(unique_jobs))
            append_relevant_jobs(worksheet, unique_jobs)
            logging.info("Step 9/9: Sending email summary.")
            send_email_summary(
                gmail_user=config["gmail_user"],
                gmail_app_password=config["gmail_app_password"],
                recipient=SUMMARY_RECIPIENT,
                jobs=unique_jobs,
            )
            logging.info(
                "Saved %s unique relevant jobs and sent summary email.",
                len(unique_jobs),
            )
        else:
            logging.info("No unique relevant jobs to append after dedup check.")
    else:
        logging.info("No relevant jobs detected from scraped messages.")

    latest_timestamp = max(m["timestamp"] for m in messages_to_analyze)
    save_last_processed_timestamp(latest_timestamp)
    logging.info("Updated last processed timestamp to %s", latest_timestamp.isoformat())
    run_outreach_task()
    logging.info("Run completed.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, FileNotFoundError, GoogleAuthError) as exc:
        logging.exception("Configuration/authentication error: %s", exc)
        raise
    except Exception as exc:
        logging.exception("Unhandled fatal error: %s", exc)
        raise
