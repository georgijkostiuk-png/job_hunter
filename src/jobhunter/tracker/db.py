"""SQLite-backed state: what's been seen, what's been notified, application lifecycle.

This is what stops the same posting from emailing you twice, and turns raw
matches into a lifecycle (discovered -> notified -> applied -> responded -> closed).
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from ..models import ApplicationStatus, JobPosting, MatchResult, utcnow_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS applications (
    job_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT,
    url TEXT,
    description TEXT,
    score INTEGER,
    recommendation TEXT,
    status TEXT NOT NULL DEFAULT 'discovered',
    first_seen TEXT NOT NULL,
    last_updated TEXT NOT NULL,
    notified_at TEXT,
    applied_at TEXT
);

CREATE TABLE IF NOT EXISTS email_threads (
    thread_id TEXT PRIMARY KEY,
    job_id TEXT REFERENCES applications(job_id),
    subject TEXT,
    summary TEXT,
    status TEXT,
    last_updated TEXT NOT NULL
);
"""


class Tracker:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Tracker":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def seen(self, job_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM applications WHERE job_id = ?", (job_id,)
        ).fetchone()
        return row is not None

    def record_match(self, posting: JobPosting, match: MatchResult) -> None:
        """Insert if new, otherwise refresh the score/description but never
        regress a status that's already progressed past 'discovered'."""
        now = utcnow_iso()
        existing = self._conn.execute(
            "SELECT status FROM applications WHERE job_id = ?", (match.job_id,)
        ).fetchone()

        if existing is None:
            self._conn.execute(
                """INSERT INTO applications
                   (job_id, source, title, company, location, url, description,
                    score, recommendation, status, first_seen, last_updated)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    match.job_id, posting.source.value, posting.title, posting.company,
                    posting.location, posting.url, posting.description,
                    match.score, match.recommendation.value,
                    ApplicationStatus.DISCOVERED.value, now, now,
                ),
            )
        else:
            self._conn.execute(
                "UPDATE applications SET score = ?, recommendation = ?, last_updated = ? WHERE job_id = ?",
                (match.score, match.recommendation.value, now, match.job_id),
            )
        self._conn.commit()

    def mark_notified(self, job_ids: list[str]) -> None:
        now = utcnow_iso()
        self._conn.executemany(
            "UPDATE applications SET status = ?, notified_at = ?, last_updated = ? WHERE job_id = ?",
            [(ApplicationStatus.NOTIFIED.value, now, now, jid) for jid in job_ids],
        )
        self._conn.commit()

    def set_status(self, job_id: str, status: ApplicationStatus) -> None:
        now = utcnow_iso()
        extra = ", applied_at = ?" if status == ApplicationStatus.APPLIED else ""
        params = (status.value, now) + ((now,) if extra else ()) + (job_id,)
        self._conn.execute(
            f"UPDATE applications SET status = ?, last_updated = ?{extra} WHERE job_id = ?",
            params,
        )
        self._conn.commit()

    def unnotified_matches(self, score_threshold: int) -> list[sqlite3.Row]:
        return self._conn.execute(
            """SELECT * FROM applications
               WHERE status = ? AND score >= ?
               ORDER BY score DESC""",
            (ApplicationStatus.DISCOVERED.value, score_threshold),
        ).fetchall()

    def total_matches(self, score_threshold: int) -> int:
        """All-time count of postings scored at/above threshold, regardless of
        notified status — cumulative total across every run, not just this one."""
        row = self._conn.execute(
            "SELECT COUNT(*) AS c FROM applications WHERE score >= ?",
            (score_threshold,),
        ).fetchone()
        return row["c"] if row else 0

    def all_matches(self, score_threshold: int) -> list[sqlite3.Row]:
        """Every posting scored at/above threshold, regardless of notified
        status — the full all-time list (unlike unnotified_matches, which is
        just this batch's new ones), sorted highest score first."""
        return self._conn.execute(
            "SELECT * FROM applications WHERE score >= ? ORDER BY score DESC",
            (score_threshold,),
        ).fetchall()

    def upsert_email_thread(self, thread_id: str, job_id: str | None, subject: str, summary: str, status: str) -> None:
        now = utcnow_iso()
        self._conn.execute(
            """INSERT INTO email_threads (thread_id, job_id, subject, summary, status, last_updated)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(thread_id) DO UPDATE SET
                 job_id=excluded.job_id, subject=excluded.subject,
                 summary=excluded.summary, status=excluded.status, last_updated=excluded.last_updated""",
            (thread_id, job_id, subject, summary, status, now),
        )
        self._conn.commit()


@contextmanager
def open_tracker(db_path: Path):
    tracker = Tracker(db_path)
    try:
        yield tracker
    finally:
        tracker.close()
