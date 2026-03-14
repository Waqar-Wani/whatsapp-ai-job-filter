import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, List

import pandas as pd


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
