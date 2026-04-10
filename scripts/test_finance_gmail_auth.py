import sys
from pathlib import Path

from google.auth.transport.requests import Request


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from finance_config import FINANCE_SENDER_EMAIL
from finance_mailer import GMAIL_SEND_SCOPE, build_retrying_session, get_gmail_credentials


def main() -> None:
    print("Testing finance Gmail authentication...")
    print(f"Expected sender: {FINANCE_SENDER_EMAIL}")
    print(f"Scopes: {', '.join(GMAIL_SEND_SCOPE)}")

    credentials = get_gmail_credentials()
    request_session = build_retrying_session()
    auth_request = Request(session=request_session)
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(auth_request)

    token_value = credentials.token or ""
    token_preview = token_value[:16] + "..." if token_value else "(missing)"

    print("PASS: Gmail API authentication succeeded.")
    print(f"Configured sender: {FINANCE_SENDER_EMAIL}")
    print(f"Access token: {token_preview}")
    print(f"Token valid: {credentials.valid}")
    print(f"Has refresh token: {bool(credentials.refresh_token)}")
    print("Note: gmail.send scope allows sending only, so Gmail profile endpoints can return 403.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"FAIL: Gmail API authentication test failed: {exc}")
        raise
