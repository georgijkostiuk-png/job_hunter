"""Builds one digest email per run — never one email per job (see architecture.html)."""

from __future__ import annotations

from .gmail_client import GmailClient


def _section(title: str, rows: list[dict]) -> list[str]:
    lines = [f"=== {title} ({len(rows)}) ===", ""]
    for m in rows:
        lines.append(f"[{m['score']}] {m['title']} — {m['company']} ({m['location']})")
        lines.append(f"    {m['url']}")
        lines.append("")
    return lines


def build_digest(
    matches: list[dict],
    threshold: int,
    total_scraped: int = 0,
    total_matches: int = 0,
    remaining_matches: list[dict] | None = None,
) -> tuple[str, str]:
    """matches: this batch's new-since-last-time rows (already sorted, highest
    score first, from Tracker.unnotified_matches). remaining_matches: every
    other all-time match not in `matches` (from Tracker.all_matches minus
    `matches`), also sorted highest score first — previously-notified
    postings that are still valid matches.

    total_scraped: everything found in this scan (new + already-seen, all
    sources/queries). total_matches: all-time count of postings at/above
    threshold (len(matches) + len(remaining_matches)). Shown alongside the
    new-match count so the email is self-explanatory about scope: this
    digest is "what's new since last time" plus "everything else that still
    matches", not "everything currently listed" (that's the dashboard email).
    """
    remaining_matches = remaining_matches or []
    subject = f"Job matches — {total_matches} total, {len(matches)} new"
    lines = [
        f"What's new since last time: {len(matches)} posting(s) scored at or above {threshold}/100.",
        f"Total matches all-time: {total_matches} posting(s) have ever scored at or above {threshold}/100.",
        f"Everything currently listed this scan: {total_scraped} posting(s) found overall "
        f"(see the dashboard email for the full list, including previously-seen ones).",
        "",
    ]
    lines += _section("New matches", matches)
    if remaining_matches:
        lines += _section("All other matches", remaining_matches)
    return subject, "\n".join(lines)


def send_digest(
    client: GmailClient,
    to: str,
    matches: list[dict],
    threshold: int,
    total_scraped: int = 0,
    total_matches: int = 0,
    remaining_matches: list[dict] | None = None,
) -> None:
    if not matches:
        return
    subject, body = build_digest(matches, threshold, total_scraped, total_matches, remaining_matches)
    recipient = to or client.my_email_address()
    client.send(to=recipient, subject=subject, body_text=body)
