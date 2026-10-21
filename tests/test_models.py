from jobhunter.models import CandidateProfile, JobPosting, JobSource, MatchResult, Recommendation


def test_job_posting_dedupe_id_ignores_url_and_whitespace_case():
    a = JobPosting(source=JobSource.STEPSTONE, title="Data  Scientist", company="Acme GmbH",
                    location="Berlin", url="https://x.test/job/1?utm=abc")
    b = JobPosting(source=JobSource.INDEED, title="data scientist", company="acme gmbh",
                    location="berlin", url="https://x.test/job/1-reposted")
    assert a.dedupe_id == b.dedupe_id


def test_job_posting_dedupe_id_differs_for_different_jobs():
    a = JobPosting(source=JobSource.STEPSTONE, title="Data Scientist", company="Acme", location="Berlin")
    b = JobPosting(source=JobSource.STEPSTONE, title="QC Analyst", company="Acme", location="Berlin")
    assert a.dedupe_id != b.dedupe_id


def test_candidate_profile_defaults_to_empty_collections():
    profile = CandidateProfile()
    assert profile.skills == []
    assert profile.experience == []


def test_match_result_score_bounds_enforced():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        MatchResult(job_id="x", score=101, recommendation=Recommendation.NOTIFY)
    with pytest.raises(ValidationError):
        MatchResult(job_id="x", score=-1, recommendation=Recommendation.NOTIFY)

    ok = MatchResult(job_id="x", score=85, recommendation=Recommendation.NOTIFY)
    assert ok.score == 85
