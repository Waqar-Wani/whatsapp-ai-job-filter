import base64
import logging
import mimetypes
import socket
from email.message import EmailMessage
from pathlib import Path
from typing import Optional, Tuple

import requests
from google.auth.exceptions import RefreshError, TransportError
from google.auth.transport.requests import AuthorizedSession, Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from requests.adapters import HTTPAdapter
from urllib3.util import Retry
import urllib3.util.connection as urllib3_connection


LOGGER = logging.getLogger(__name__)
GMAIL_SEND_SCOPE = ["https://www.googleapis.com/auth/gmail.send"]
GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
CONNECT_TIMEOUT_SECONDS = 8
READ_TIMEOUT_SECONDS = 8
MAX_RETRIES = 3

_ORIGINAL_ALLOWED_GAI_FAMILY = urllib3_connection.allowed_gai_family
_IPV4_FORCED = False


class DefaultTimeoutSession(requests.Session):
    def __init__(self, timeout: Tuple[int, int]) -> None:
        super().__init__()
        self._default_timeout = timeout

    def request(self, *args, **kwargs):  # type: ignore[override]
        kwargs.setdefault("timeout", self._default_timeout)
        return super().request(*args, **kwargs)


def _force_ipv4() -> None:
    global _IPV4_FORCED
    if _IPV4_FORCED:
        return

    urllib3_connection.allowed_gai_family = lambda: socket.AF_INET
    _IPV4_FORCED = True
    LOGGER.info("Forced IPv4 for Gmail API HTTP transport")


def _build_retrying_session() -> requests.Session:
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


def get_gmail_credentials(client_secret_file: str, token_file: str) -> Credentials:
    creds = None
    token_path = Path(token_file)
    client_secret_path = Path(client_secret_file)
    request_session = _build_retrying_session()
    auth_request = Request(session=request_session)

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), GMAIL_SEND_SCOPE)

    if creds and creds.expired and creds.refresh_token:
        try:
            LOGGER.info("Refreshing Gmail API credentials")
            creds.refresh(auth_request)
            token_path.parent.mkdir(parents=True, exist_ok=True)
            token_path.write_text(creds.to_json(), encoding="utf-8")
            LOGGER.info("Gmail API credential refresh succeeded")
        except (RefreshError, TransportError, requests.RequestException) as exc:
            LOGGER.error("Gmail API credential refresh failed: %s", exc)
            raise RuntimeError(
                "Failed to refresh Gmail API credentials using the custom IPv4 transport"
            ) from exc
    elif not creds or not creds.valid:
        LOGGER.info("Launching Gmail OAuth consent flow")
        flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_path), GMAIL_SEND_SCOPE)
        creds = flow.run_local_server(port=0)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json(), encoding="utf-8")
        LOGGER.info("Saved Gmail API OAuth token to %s", token_path)

    return creds


def build_gmail_message(
    sender_email: str,
    to_email: str,
    subject: str,
    html_body: str,
    text_body: Optional[str] = None,
    attachment_path: Optional[str] = None,
    reply_to: Optional[str] = None,
) -> dict:
    message = EmailMessage()
    message["To"] = to_email
    message["From"] = sender_email
    message["Subject"] = subject
    if reply_to:
        message["Reply-To"] = reply_to

    if text_body and html_body:
        message.set_content(text_body)
        message.add_alternative(html_body, subtype="html")
    elif html_body:
        message.add_alternative(html_body, subtype="html")
    else:
        message.set_content(text_body or "")

    if attachment_path:
        path = Path(attachment_path)
        mime_type, _ = mimetypes.guess_type(path.name)
        maintype, subtype = (mime_type or "application/octet-stream").split("/", 1)
        message.add_attachment(
            path.read_bytes(),
            maintype=maintype,
            subtype=subtype,
            filename=path.name,
        )

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    return {"raw": raw}


def send_email_via_gmail_api(
    client_secret_file: str,
    token_file: str,
    sender_email: str,
    to_email: str,
    subject: str,
    html_body: str,
    text_body: Optional[str] = None,
    attachment_path: Optional[str] = None,
    reply_to: Optional[str] = None,
) -> None:
    creds = get_gmail_credentials(client_secret_file, token_file)
    session = _build_retrying_session()
    auth_request = Request(session=session)
    authed_session = AuthorizedSession(credentials=creds, auth_request=auth_request)
    authed_session.timeout = (CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS)

    message = build_gmail_message(
        sender_email=sender_email,
        to_email=to_email,
        subject=subject,
        html_body=html_body,
        text_body=text_body,
        attachment_path=attachment_path,
        reply_to=reply_to,
    )

    LOGGER.info("Sending Gmail API message to %s", to_email)
    response = authed_session.post(
        GMAIL_SEND_URL,
        json=message,
        timeout=(CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS),
    )
    if response.status_code >= 400:
        LOGGER.error("Gmail API send failed for %s: %s %s", to_email, response.status_code, response.text)
        response.raise_for_status()
    LOGGER.info("Gmail API send succeeded for %s", to_email)
