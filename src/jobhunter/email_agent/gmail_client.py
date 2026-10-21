"""Thin Gmail API wrapper. Scopes are deliberately read + send only — never
modify/delete — so the agent can never alter your mailbox, only observe and notify.
"""

from __future__ import annotations

import base64
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from .attachment import Attachment

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]


class GmailNotConfigured(RuntimeError):
    pass


def get_credentials(credentials_path: Path, token_path: Path) -> Credentials:
    creds: Credentials | None = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())

    if not creds or not creds.valid:
        if not credentials_path.exists():
            raise GmailNotConfigured(
                f"No Gmail OAuth client secret at {credentials_path}. "
                "Download it from Google Cloud Console (APIs & Services > Credentials) "
                "and save it there before running the email agent."
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
        creds = flow.run_local_server(port=0)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json(), encoding="utf-8")

    return creds


class GmailClient:
    def __init__(self, credentials_path: Path, token_path: Path):
        creds = get_credentials(credentials_path, token_path)
        self._service = build("gmail", "v1", credentials=creds)

    def my_email_address(self) -> str:
        profile = self._service.users().getProfile(userId="me").execute()
        return profile["emailAddress"]

    def send(
        self,
        to: str,
        subject: str,
        body_text: str,
        *,
        attachments: list[Attachment] | None = None,
    ) -> None:
        if attachments:
            message = MIMEMultipart()
            message.attach(MIMEText(body_text))
            for att in attachments:
                part = MIMEApplication(att.content, _subtype=att.subtype)
                part.add_header("Content-Disposition", "attachment", filename=att.filename)
                message.attach(part)
        else:
            message = MIMEText(body_text)
        message["to"] = to
        message["subject"] = subject
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        self._service.users().messages().send(userId="me", body={"raw": raw}).execute()

    def list_recent_threads(self, query: str = "newer_than:3d", max_results: int = 25) -> list[dict]:
        """query uses Gmail search syntax, e.g. 'newer_than:3d in:inbox'."""
        resp = (
            self._service.users()
            .threads()
            .list(userId="me", q=query, maxResults=max_results)
            .execute()
        )
        return resp.get("threads", [])

    def get_thread(self, thread_id: str) -> dict:
        return self._service.users().threads().get(userId="me", id=thread_id, format="full").execute()

    @staticmethod
    def thread_plain_text(thread: dict) -> tuple[str, str]:
        """Returns (subject, concatenated plain-text body) for a thread."""
        messages = thread.get("messages", [])
        subject = ""
        parts_text: list[str] = []
        for msg in messages:
            headers = {h["name"]: h["value"] for h in msg["payload"].get("headers", [])}
            if not subject:
                subject = headers.get("Subject", "")
            parts_text.append(GmailClient._extract_plain_text(msg["payload"]))
        return subject, "\n---\n".join(p for p in parts_text if p)

    @staticmethod
    def _extract_plain_text(payload: dict) -> str:
        if payload.get("mimeType") == "text/plain" and "data" in payload.get("body", {}):
            return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="ignore")
        for part in payload.get("parts", []):
            text = GmailClient._extract_plain_text(part)
            if text:
                return text
        return ""
