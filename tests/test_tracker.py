from pathlib import Path

from jobhunter.models import ApplicationStatus, JobPosting, JobSource, MatchResult, Recommendation
from jobhunter.tracker.db import Tracker


def _posting(title="Data Scientist", company="Acme", score=80):
    return JobPosting(source=JobSource.STEPSTONE, title=title, company=company, location="Berlin", url="https://x/1")


def test_record_match_then_seen(tmp_path: Path):
    with Tracker(tmp_path / "state.db") as t:
        posting = _posting()
        match = MatchResult(job_id=posting.dedupe_id, score=85, recommendation=Recommendation.NOTIFY)

        assert not t.seen(posting.dedupe_id)
        t.record_match(posting, match)
        assert t.seen(posting.dedupe_id)


def test_unnotified_matches_respects_threshold(tmp_path: Path):
    with Tracker(tmp_path / "state.db") as t:
        low = _posting(title="Junior QC", score=40)
        high = _posting(title="Senior QC", score=90)

        t.record_match(low, MatchResult(job_id=low.dedupe_id, score=40, recommendation=Recommendation.SKIP))
        t.record_match(high, MatchResult(job_id=high.dedupe_id, score=90, recommendation=Recommendation.NOTIFY))

        results = t.unnotified_matches(score_threshold=70)
        job_ids = {r["job_id"] for r in results}
        assert high.dedupe_id in job_ids
        assert low.dedupe_id not in job_ids


def test_mark_notified_removes_from_unnotified(tmp_path: Path):
    with Tracker(tmp_path / "state.db") as t:
        posting = _posting()
        t.record_match(posting, MatchResult(job_id=posting.dedupe_id, score=90, recommendation=Recommendation.NOTIFY))
        assert len(t.unnotified_matches(70)) == 1

        t.mark_notified([posting.dedupe_id])
        assert len(t.unnotified_matches(70)) == 0


def test_set_status_progresses_lifecycle(tmp_path: Path):
    with Tracker(tmp_path / "state.db") as t:
        posting = _posting()
        t.record_match(posting, MatchResult(job_id=posting.dedupe_id, score=90, recommendation=Recommendation.NOTIFY))
        t.set_status(posting.dedupe_id, ApplicationStatus.APPLIED)

        row = t._conn.execute("SELECT status, applied_at FROM applications WHERE job_id = ?", (posting.dedupe_id,)).fetchone()
        assert row["status"] == ApplicationStatus.APPLIED.value
        assert row["applied_at"] is not None


def test_record_match_upserts_without_duplicating(tmp_path: Path):
    with Tracker(tmp_path / "state.db") as t:
        posting = _posting()
        t.record_match(posting, MatchResult(job_id=posting.dedupe_id, score=60, recommendation=Recommendation.WATCH))
        t.record_match(posting, MatchResult(job_id=posting.dedupe_id, score=75, recommendation=Recommendation.NOTIFY))

        count = t._conn.execute("SELECT COUNT(*) c FROM applications").fetchone()["c"]
        assert count == 1
        row = t._conn.execute("SELECT score FROM applications WHERE job_id = ?", (posting.dedupe_id,)).fetchone()
        assert row["score"] == 75
