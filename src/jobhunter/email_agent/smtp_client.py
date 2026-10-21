"""Gmail SMTP client using an address + app password — no OAuth browser flow.

Send-only, used for the digest notification. Preferred over the Gmail API
client whenever GMAIL_ADDRESS and GMAIL_APP_PASSWORD are set in .env, since it
needs no Google Cloud Console setup. Inbox triage still needs the Gmail API
(GmailClient), so that path is untouched.
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

from .attachment import Attachment


class SmtpNotConfigured(RuntimeError):
    pass


class SmtpClient:
    def __init__(self, address: str, app_password: str):
        if not address or not app_password:
            raise SmtpNotConfigured(
                "GMAIL_ADDRESS and GMAIL_APP_PASSWORD must both be set in .env to send via SMTP."
            )
        self._address = address
        self._app_password = app_password

    def my_email_address(self) -> str:
        return self._address

    def send(
        self,
        to: str,
        subject: str,
        body_text: str,
        *,
        attachments: list[Attachment] | None = None,
    ) -> None:
        msg = EmailMessage()
        msg["From"] = self._address
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body_text)
        for att in attachments or []:
            msg.add_attachment(
                att.content, maintype=att.maintype, subtype=att.subtype, filename=att.filename
            )
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as srv:
            srv.login(self._address, self._app_password)
            srv.send_message(msg)
