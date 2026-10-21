"""Shared attachment type for GmailClient/SmtpClient.send()."""

from __future__ import annotations

from typing import NamedTuple


class Attachment(NamedTuple):
    filename: str
    content: bytes
    maintype: str = "text"
    subtype: str = "plain"
