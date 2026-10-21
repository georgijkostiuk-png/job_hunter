"""Command-line entrypoint: jobhunter <command>."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from .config import load_settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jobhunter")
    parser.add_argument("--config", default=None, help="Path to config.yaml")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("check", help="Validate config/credentials without calling any API")

    p_extract = sub.add_parser("extract", help="Setup pass: documents in inbox -> profile.json")
    p_extract.add_argument("--dry-run", action="store_true")

    p_run = sub.add_parser("run", help="One pass of scrape -> match -> notify -> triage inbox")
    p_run.add_argument("--dry-run", action="store_true")

    sub.add_parser("schedule", help="Run the scheduler loop (blocks; Ctrl+C to stop)")

    return parser


def cmd_check(settings) -> int:
    from .llm.ollama_client import check_available

    print(f"Project root:     {settings.root}")
    print(f"Inbox dir:        {settings.resolve(settings.paths.inbox_dir)}")
    print(f"Profile path:     {settings.resolve(settings.paths.profile_path)}")
    print(f"DB path:          {settings.resolve(settings.paths.db_path)}")
    ok, msg = check_available(settings.llm.host, settings.llm.model)
    print(f"Local LLM:        {'OK' if ok else 'NOT READY'} — {msg}")
    google_creds = settings.resolve(settings.paths.google_credentials)
    print(f"Google creds:     {'found' if google_creds.exists() else 'MISSING (' + str(google_creds) + ')'}")
    smtp_configured = bool(os.environ.get("GMAIL_ADDRESS") and os.environ.get("GMAIL_APP_PASSWORD"))
    if smtp_configured:
        print(f"Notify via:       SMTP app password ({os.environ['GMAIL_ADDRESS']})")
    else:
        print("Notify via:       Gmail OAuth (set GMAIL_ADDRESS + GMAIL_APP_PASSWORD in .env to use SMTP instead)")
    print(f"Sources:          {settings.search.sources}")
    print(f"Queries:          {settings.search.queries}")
    print(f"Locations:        {settings.search.locations}")
    print(f"Score threshold:  {settings.matching.score_threshold}")
    print(f"Run hours:        {settings.scheduler.run_hours}")
    return 0


class _Tee:
    """Duplicates writes across multiple streams (used to mirror stdout/stderr
    into jobhunter_console_RESULTS_<timestamp>.txt / _INFO_<timestamp>.txt
    while still printing normally)."""

    def __init__(self, *streams):
        self._streams = streams

    def write(self, data):
        for s in self._streams:
            s.write(data)

    def flush(self):
        for s in self._streams:
            s.flush()


def cmd_run(settings, *, dry_run: bool) -> int:
    from .email_agent.attachment import Attachment
    from .orchestrator.pipeline import run_once, send_results_email

    run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Split by stream: RESULTS captures stdout (the printed job listing,
    # stats, save/email confirmations); INFO captures stderr (logger.info
    # progress lines, warnings). Two files instead of one interleaved log.
    results_path = settings.root / f"jobhunter_console_RESULTS_{run_timestamp}.txt"
    info_path = settings.root / f"jobhunter_console_INFO_{run_timestamp}.txt"
    results_file = results_path.open("w", encoding="utf-8")
    info_file = info_path.open("w", encoding="utf-8")
    real_stdout, real_stderr = sys.stdout, sys.stderr
    sys.stdout = _Tee(real_stdout, results_file)
    sys.stderr = _Tee(real_stderr, info_file)
    # Re-bind the logging handler to the just-installed Tee — basicConfig()
    # in main() ran before this and captured the *original* sys.stderr, so
    # without this, logger.info() progress lines would print live but never
    # land in jobhunter_console_INFO_<timestamp>.txt.
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", force=True
    )

    try:
        stats = run_once(settings, dry_run=dry_run)
        by_query = stats.pop("by_query", None)
        by_group = stats.pop("by_group", None)
        dashboard_path_str = stats.pop("dashboard_path", None)

        if by_group:
            total_unique = 0
            for group_name, group in by_group.items():
                entries = group["entries"]
                total_unique += len(entries)
                raw_note = f" · {group['raw_count']} raw matches" if len(entries) != group["raw_count"] else ""
                print(f"\n=== {group_name} ({len(entries)} unique{raw_note}) ===")
                print(f"    queries: {', '.join(group['member_queries'])}")
                for p in entries:
                    via = ", ".join(p["queries"])
                    print(f"  [{p['source']}] {p['title']} — {p['company']} ({p['location']})  [via: {via}]")
                    if p["url"]:
                        print(f"      {p['url']}")
            print(f"\nTotal unique postings: {total_unique}")
        elif by_query:
            total = 0
            for query, postings in by_query.items():
                print(f"\n=== {query} ({len(postings)}) ===")
                for p in postings:
                    print(f"  [{p['source']}] {p['title']} — {p['company']} ({p['location']})")
                    if p["url"]:
                        print(f"      {p['url']}")
                total += len(postings)
            print(f"\nTotal found: {total}")

        if by_query or by_group:
            out_path = settings.root / "jobhunter_results.json"
            out_path.write_text(
                json.dumps(
                    {
                        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "dry_run": dry_run,
                        "by_query": by_query,
                        "by_group": by_group,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            print(f"\nSaved results to {out_path}")

        print(stats)

        if by_group and dashboard_path_str:
            sys.stdout.flush()
            sys.stderr.flush()
            results_bytes = results_path.read_bytes()
            info_bytes = info_path.read_bytes()
            sent = send_results_email(
                settings,
                by_group,
                Path(dashboard_path_str),
                dry_run=dry_run,
                extra_attachments=[
                    Attachment(
                        filename=results_path.name,
                        content=results_bytes,
                        maintype="text",
                        subtype="plain",
                    ),
                    Attachment(
                        filename=info_path.name,
                        content=info_bytes,
                        maintype="text",
                        subtype="plain",
                    ),
                ],
            )
            print(f"Emailed dashboard + console logs: {'sent' if sent else 'skipped (no email client configured)'}")

        return 0
    finally:
        sys.stdout, sys.stderr = real_stdout, real_stderr
        results_file.close()
        info_file.close()


def main(argv: list[str] | None = None) -> int:
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = load_settings(config_path=args.config)

    if args.command == "check":
        return cmd_check(settings)

    if args.command == "extract":
        from .orchestrator.pipeline import run_extraction
        n = run_extraction(settings, dry_run=args.dry_run)
        print(f"Processed {n} document(s).")
        return 0

    if args.command == "run":
        return cmd_run(settings, dry_run=args.dry_run)

    if args.command == "schedule":
        from .orchestrator.scheduler import start
        start(settings)
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
