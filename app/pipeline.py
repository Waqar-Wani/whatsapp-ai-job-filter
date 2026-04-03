import logging
import os
import re
from typing import Any, Dict, List

from app.core.config import validate_env
from app.core.constants import GROUP_NAME, SUMMARY_RECIPIENT, TEMP_SCRAPED_FILE
from app.core.formatting import format_sheet_datetime
from app.services.ai_filter import analyze_job_post, ensure_internet_connectivity
from app.services.email_summary import send_email_summary
from app.services.outreach import run_outreach_task
from app.services.sheets import (
    append_relevant_jobs,
    deduplicate_jobs_for_sheet,
    ensure_sheet,
    get_gspread_client,
)
from app.services.whatsapp import deduplicate_messages, get_all_messages
from app.storage.state import (
    load_last_processed_timestamp,
    save_last_processed_timestamp,
    save_temp_scraped_messages,
)


def build_source_key(message: Dict[str, Any]) -> str:
    normalized_text = re.sub(r"\s+", " ", message["text"].strip().lower())
    return f"{message['sender'].strip().lower()}|{message['timestamp'].isoformat()}|{normalized_text}"


def build_relevant_jobs(messages_to_analyze: List[Dict[str, Any]], config: Dict[str, str]) -> List[Dict[str, Any]]:
    relevant_jobs: List[Dict[str, Any]] = []
    for message in messages_to_analyze:
        ai_result = analyze_job_post(
            text=message["text"],
            openrouter_key=config["openrouter_api_key"],
            openrouter_model=config["openrouter_model"],
            openrouter_site_url=config["openrouter_site_url"],
            openrouter_site_name=config["openrouter_site_name"],
        )
        if not ai_result.get("relevant"):
            continue

        skills_value = ai_result.get("skills", "")
        if isinstance(skills_value, list):
            skills_value = ", ".join(str(item) for item in skills_value if str(item).strip())

        relevant_jobs.append(
            {
                "date": format_sheet_datetime(message["timestamp"]),
                "sender": message["sender"],
                "company": ai_result.get("company", ""),
                "role": ai_result.get("role", ""),
                "location": ai_result.get("location", ""),
                "experience": ai_result.get("experience", ""),
                "skills": str(skills_value).strip(),
                "contact_email": ai_result.get("contact_email", ""),
                "source_key": build_source_key(message),
            }
        )
    return relevant_jobs


def run_pipeline() -> None:
    run_source = (os.getenv("RUN_SOURCE", "manual") or "manual").strip().lower()
    logging.info("==============================================")
    logging.info("Starting WhatsApp job automation run. source=%s", run_source)
    logging.info("Step 1/9: Validating environment configuration.")

    config = validate_env()
    logging.info("Step 1.5/9: Checking internet connectivity.")
    try:
        ensure_internet_connectivity()
    except RuntimeError as exc:
        logging.warning("Run skipped: %s", exc)
        return

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
        messages_to_analyze = [message for message in deduped_messages if message["timestamp"] > last_processed]
    else:
        messages_to_analyze = deduped_messages

    if not messages_to_analyze:
        logging.info("No new messages after last processed timestamp.")
        run_outreach_task()
        return

    logging.info("Step 5/9: Running AI filtering for %s message(s).", len(messages_to_analyze))
    relevant_jobs = build_relevant_jobs(messages_to_analyze, config)

    if relevant_jobs:
        logging.info("Step 6/9: Connecting to Google Sheets.")
        worksheet = None
        unique_jobs = []
        try:
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

        except Exception as exc:
            logging.warning(
                "Step 6/9+: Google Sheets/summary failed (network/auth). Continuing with state update and outreach. Error: %s",
                exc,
            )
            # fallback: keep processing, do not stop entire pipeline

    else:
        logging.info("No relevant jobs detected from scraped messages.")

    latest_timestamp = max(message["timestamp"] for message in messages_to_analyze)
    save_last_processed_timestamp(latest_timestamp)
    logging.info("Updated last processed timestamp to %s", latest_timestamp.isoformat())
    run_outreach_task()
    logging.info("Run completed.")
