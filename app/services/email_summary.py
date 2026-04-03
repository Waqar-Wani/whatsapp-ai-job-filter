from typing import Any, Dict, List

import pandas as pd

from app.services.gmail_api import send_email_via_gmail_api


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
    gmail_sender_email: str,
    gmail_oauth_client_secret_file: str,
    gmail_token_file: str,
    gmail_reply_to: str,
    recipient: str,
    jobs: List[Dict[str, Any]],
) -> None:
    text_body = build_email_body(jobs)
    html_body = "<html><body><pre>" + text_body + "</pre></body></html>"
    send_email_via_gmail_api(
        client_secret_file=gmail_oauth_client_secret_file,
        token_file=gmail_token_file,
        sender_email=gmail_sender_email,
        to_email=recipient,
        subject="New Filtered Jobs - Qa Paid Experience",
        html_body=html_body,
        text_body=text_body,
        reply_to=gmail_reply_to or None,
    )
