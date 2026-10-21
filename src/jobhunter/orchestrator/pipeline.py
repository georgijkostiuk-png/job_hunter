"""Wires every module together into the two pipeline passes described in
architecture.html: the one-time Extraction setup pass, and the recurring Loop
(scrape -> match -> track -> notify -> triage inbox -> update track).
"""

from __future__ import annotations

import contextlib
import logging
import os
import smtplib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

from ..config import Settings
from ..email_agent.attachment import Attachment
from ..email_agent.gmail_client import GmailClient, GmailNotConfigured
from ..email_agent.notifier import send_digest
from ..email_agent.smtp_client import SmtpClient
from ..email_agent.triage import triage_thread
from ..extraction.profile_extractor import extract_profile, load_profile, save_profile
from ..ingestion.loader import combined_text, load_inbox
from ..llm.ollama_client import OllamaError
from ..matching.matcher import score_posting
from ..models import ApplicationStatus
from ..reporting.dashboard import render_dashboard_html
from ..scraping.registry import LINKEDIN_MIN_INTERVAL_HOURS, get_adapters
from ..tracker.db import Tracker
from .run_state import last_run, mark_run

logger = logging.getLogger(__name__)


def run_extraction(settings: Settings, dry_run: bool = False) -> int:
    """Setup pass: documents in inbox -> profile.json. Returns number of docs processed."""
    inbox = settings.resolve(settings.paths.inbox_dir)
    docs = load_inbox(inbox)
    if not docs:
        logger.info("No documents found in %s", inbox)
        return 0

    if dry_run:
        logger.info("[dry-run] Would extract profile from %d document(s)", len(docs))
        return len(docs)

    profile_path = settings.resolve(settings.paths.profile_path)
    existing = load_profile(profile_path)
    profile = extract_profile(
        combined_text(docs),
        host=settings.llm.host,
        model=settings.llm.model,
        temperature=settings.llm.extraction_temperature,
        existing=existing,
    )
    save_profile(profile, profile_path)
    logger.info("Profile written to %s (version %d)", profile_path, profile.version)
    return len(docs)


def _should_run_source(settings: Settings, source: str) -> bool:
    if source != "linkedin":
        return True
    state_path = settings.resolve("data/scheduler_state.json")
    prev = last_run(state_path, source)
    if prev is None:
        return True
    return datetime.now(timezone.utc) - prev >= timedelta(hours=LINKEDIN_MIN_INTERVAL_HOURS)


def _group_by_theme(query_groups: dict[str, list[str]], by_query: dict[str, list[dict]]) -> dict[str, dict]:
    """Clusters near-duplicate queries under one label (settings.search.query_groups),
    deduplicating postings by URL within each cluster. Each entry keeps a
    "queries" list naming which member query(ies) surfaced it."""
    grouped: dict[str, dict] = {}
    for group_name, member_queries in query_groups.items():
        seen: dict[str, dict] = {}
        raw_count = 0
        for query in member_queries:
            for entry in by_query.get(query, []):
                raw_count += 1
                key = entry["url"] or f"{entry['source']}|{entry['title']}"
                if key in seen:
                    if query not in seen[key]["queries"]:
                        seen[key]["queries"].append(query)
                else:
                    merged = dict(entry)
                    merged["queries"] = [query]
                    seen[key] = merged
        grouped[group_name] = {
            "entries": list(seen.values()),
            "raw_count": raw_count,
            "member_queries": member_queries,
        }
    return grouped


def run_scrape_and_match(settings: Settings, dry_run: bool = False) -> dict:
    profile_path = settings.resolve(settings.paths.profile_path)
    profile = load_profile(profile_path)

    db_path = settings.resolve(settings.paths.db_path)
    state_path = settings.resolve("data/scheduler_state.json")
    sources = [s for s in settings.search.sources if _should_run_source(settings, s)]
    adapters = get_adapters(sources)

    stats = {"scraped": 0, "new": 0, "matched_above_threshold": 0, "match_errors": 0}
    by_query: dict[str, list[dict]] = {q: [] for q in settings.search.queries}

    if dry_run:
        logger.info(
            "[dry-run] Scraping sources=%s queries=%s locations=%s "
            "(real requests to job sites, but no LLM matching, no tracker writes, no email)",
            sources, settings.search.queries, settings.search.locations,
        )
        if profile is None:
            logger.info("[dry-run] No profile.json yet - matching would be skipped on a real run too.")
    elif profile is None:
        raise RuntimeError(
            "No profile.json yet — run `jobhunter extract` first so there's something to match against."
        )

    total_searches = len(adapters) * len(settings.search.queries) * len(settings.search.locations)
    search_num = 0

    tracker_cm = Tracker(db_path) if not dry_run else contextlib.nullcontext(None)
    with tracker_cm as tracker:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                for adapter in adapters:
                    for query in settings.search.queries:
                        for location in settings.search.locations:
                            search_num += 1
                            postings = adapter.safe_fetch(
                                browser, query, location,
                                max_postings=settings.search.max_postings_per_search,
                            )
                            stats["scraped"] += len(postings)
                            logger.info(
                                "[%d/%d] %s @ %s (%s): %d posting(s) — %d total so far",
                                search_num, total_searches, adapter.source, query, location,
                                len(postings), stats["scraped"],
                            )
                            for posting in postings:
                                by_query[query].append(
                                    {
                                        "source": posting.source.value,
                                        "title": posting.title,
                                        "company": posting.company,
                                        "location": posting.location,
                                        "url": posting.url,
                                    }
                                )
                                if dry_run:
                                    continue
                                job_id = posting.dedupe_id
                                if tracker.seen(job_id):
                                    continue
                                stats["new"] += 1
                                try:
                                    match = score_posting(
                                        profile, posting,
                                        host=settings.llm.host,
                                        target_domains=settings.search.target_domains,
                                        model=settings.llm.model,
                                        temperature=settings.llm.matching_temperature,
                                    )
                                except OllamaError as e:
                                    stats["match_errors"] += 1
                                    logger.warning(
                                        "Skipping match for %r (%s) after LLM error: %s — "
                                        "it stays unseen and will be retried next run.",
                                        posting.title, posting.dedupe_id, e,
                                    )
                                    continue
                                tracker.record_match(posting, match)
                                if match.score >= settings.matching.score_threshold:
                                    stats["matched_above_threshold"] += 1
                    if not dry_run:
                        mark_run(state_path, adapter.source)
            finally:
                browser.close()

        if not dry_run:
            _send_notifications(settings, tracker, total_scraped=stats["scraped"])

    stats["by_query"] = by_query
    if settings.search.query_groups:
        by_group = _group_by_theme(settings.search.query_groups, by_query)
        stats["by_group"] = by_group
        stats["dashboard_path"] = str(save_dashboard(settings, by_group, dry_run=dry_run))
    return stats


def _resolve_email_client(settings: Settings) -> SmtpClient | GmailClient | None:
    """Same client-selection rule everywhere: SMTP app password if set in
    .env, else Gmail OAuth. Returns None (with a logged warning) if neither
    is configured, so callers can skip sending instead of crashing a run."""
    gmail_address = os.environ.get("GMAIL_ADDRESS")
    gmail_app_password = os.environ.get("GMAIL_APP_PASSWORD")
    if gmail_address and gmail_app_password:
        return SmtpClient(gmail_address, gmail_app_password)
    try:
        return GmailClient(
            settings.resolve(settings.paths.google_credentials),
            settings.resolve(settings.paths.google_token),
        )
    except GmailNotConfigured as e:
        logger.warning("No email client configured: %s", e)
        return None


def _send_notifications(settings: Settings, tracker: Tracker, *, total_scraped: int = 0) -> None:
    rows = tracker.unnotified_matches(settings.matching.score_threshold)
    if not rows:
        return

    client = _resolve_email_client(settings)
    if client is None:
        logger.warning("Skipping notification: no email client configured")
        return

    matches = [dict(row) for row in rows]
    new_ids = {m["job_id"] for m in matches}
    all_rows = tracker.all_matches(settings.matching.score_threshold)
    remaining_matches = [dict(row) for row in all_rows if row["job_id"] not in new_ids]
    total_matches = len(matches) + len(remaining_matches)
    try:
        send_digest(
            client, settings.email.notify_to, matches, settings.matching.score_threshold,
            total_scraped, total_matches, remaining_matches,
        )
    except (smtplib.SMTPException, OSError) as e:
        logger.warning(
            "Skipping digest send after email error: %s — matches stay unnotified "
            "and the digest will be retried next run.", e,
        )
        return
    tracker.mark_notified([m["job_id"] for m in matches])
    logger.info("Sent digest for %d new match(es) + %d remaining (%d total all-time)",
                len(matches), len(remaining_matches), total_matches)


def save_dashboard(settings: Settings, by_group: dict, *, dry_run: bool) -> Path:
    """Renders the grouped results as a self-contained HTML dashboard and
    saves it locally (project root). Separate from _send_notifications,
    which only fires on a real run and only for postings at/above the score
    threshold — this captures every run (dry-run included), so you get the
    full picture, not just what cleared the bar."""
    html = render_dashboard_html(by_group, dry_run=dry_run)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dashboard_path = settings.root / f"jobhunter_dashboard_{timestamp}.html"
    dashboard_path.write_text(html, encoding="utf-8")
    logger.info("Dashboard written to %s", dashboard_path)
    return dashboard_path


def send_results_email(
    settings: Settings,
    by_group: dict,
    dashboard_path: Path,
    *,
    dry_run: bool,
    extra_attachments: list[Attachment] | None = None,
) -> bool:
    """Emails the dashboard (plus any extra_attachments, e.g. a console log)
    to settings.email.notify_to. Returns whether it actually sent."""
    client = _resolve_email_client(settings)
    if client is None:
        logger.warning("Skipping results email: no email client configured")
        return False

    total = sum(len(g["entries"]) for g in by_group.values())
    to = settings.email.notify_to or client.my_email_address()
    mode = "dry-run" if dry_run else "run"
    subject = f"jobhunter dashboard — {total} unique posting(s) ({mode})"
    group_summary = ", ".join(f"{name} ({len(g['entries'])})" for name, g in by_group.items())
    body = (
        f"Everything currently listed this scan: {total} unique posting(s) found across "
        f"{len(by_group)} group(s): {group_summary}.\n"
        "(For just what's new since last time, see the separate match-digest email — "
        "this one includes previously-seen postings too.)\n\n"
        "Full results attached (open the dashboard in a browser — filter by source, search, "
        "hide \"similar listings\" noise)."
    )

    attachments = [
        Attachment(
            filename=dashboard_path.name,
            content=dashboard_path.read_bytes(),
            maintype="text",
            subtype="html",
        )
    ]
    attachments.extend(extra_attachments or [])

    client.send(to=to, subject=subject, body_text=body, attachments=attachments)
    logger.info("Sent results email to %s (%d attachment(s))", to, len(attachments))
    return True


def run_email_triage(settings: Settings, dry_run: bool = False) -> int:
    """Polls the inbox, classifies new threads, updates tracker state for matches."""
    if not settings.email.triage_enabled:
        logger.info("Skipping inbox triage: email.triage_enabled is false in config.yaml")
        return 0

    if dry_run:
        logger.info("[dry-run] Would poll inbox for recruiter replies")
        return 0

    try:
        client = GmailClient(
            settings.resolve(settings.paths.google_credentials),
            settings.resolve(settings.paths.google_token),
        )
    except GmailNotConfigured as e:
        logger.warning("Skipping email triage: %s", e)
        return 0

    db_path = settings.resolve(settings.paths.db_path)
    processed = 0
    with Tracker(db_path) as tracker:
        threads = client.list_recent_threads()
        for thread_meta in threads:
            thread = client.get_thread(thread_meta["id"])
            subject, body = client.thread_plain_text(thread)
            if not body:
                continue
            result = triage_thread(subject, body, host=settings.llm.host, model=settings.llm.model)
            if not result.get("is_job_related"):
                continue

            job_id = _match_company_to_job(tracker, result.get("company_guess", ""))
            tracker.upsert_email_thread(
                thread_id=thread_meta["id"],
                job_id=job_id,
                subject=subject,
                summary=result.get("summary", ""),
                status=result.get("status", ApplicationStatus.RESPONDED.value),
            )
            if job_id:
                tracker.set_status(job_id, ApplicationStatus(result.get("status", ApplicationStatus.RESPONDED.value)))
            processed += 1
    return processed


def _match_company_to_job(tracker: Tracker, company_guess: str) -> str | None:
    if not company_guess:
        return None
    row = tracker._conn.execute(
        "SELECT job_id FROM applications WHERE company LIKE ? ORDER BY last_updated DESC LIMIT 1",
        (f"%{company_guess}%",),
    ).fetchone()
    return row["job_id"] if row else None


def run_once(settings: Settings, dry_run: bool = False) -> dict:
    scrape_stats = run_scrape_and_match(settings, dry_run=dry_run)
    triaged = run_email_triage(settings, dry_run=dry_run)
    return {**scrape_stats, "threads_triaged": triaged}
