#!/usr/bin/env python3
"""Test Gmail API email send functionality."""

import sys
from pathlib import Path

# Add project root to path
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
from app.services.gmail_api import send_email_via_gmail_api

def main():
    load_dotenv(PROJECT_ROOT / ".env")
    
    # Get config from environment
    import os
    sender_email = os.getenv("GMAIL_SENDER_EMAIL")
    client_secret_file = os.getenv("GMAIL_OAUTH_CLIENT_SECRET_FILE")
    token_file = os.getenv("GMAIL_TOKEN_FILE")
    
    print(f"Sender: {sender_email}")
    print(f"Client Secret: {client_secret_file}")
    print(f"Token File: {token_file}")
    print()
    
    # Send test email
    try:
        print("Sending test email to waqar@yopmail.com...")
        send_email_via_gmail_api(
            client_secret_file=client_secret_file,
            token_file=token_file,
            sender_email=sender_email,
            to_email="waqar@yopmail.com",
            subject="Gmail API Test - WhatsApp Job Filter",
            text_body="This is a test email to confirm Gmail API is working correctly.",
            html_body="<html><body><p>This is a test email to confirm Gmail API is working correctly.</p></body></html>",
            reply_to=None,
        )
        print("✅ Test email sent successfully!")
        print("Check waqar@yopmail.com to confirm delivery.")
        return 0
    except Exception as exc:
        print(f"❌ Failed to send test email: {exc}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())
