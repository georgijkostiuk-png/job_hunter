"""Exercises the real extraction/matching code paths (schema building, response
parsing, pydantic validation, retry-on-bad-output) against a fake Ollama HTTP
client — no network, no Ollama server, no API key required. This is what "the
structured-output plumbing actually works" looks like without spending a real
model call.
"""

from __future__ import annotations

import json

import jobhunter.extraction.profile_extractor as extractor_mod
import jobhunter.matching.matcher as matcher_mod
from jobhunter.llm import ollama_client
from jobhunter.models import CandidateProfile, JobPosting, JobSource


class FakeResponse:
    def __init__(self, content: str, status_code: int = 200):
        self._content = content
        self.status_code = status_code

    def raise_for_status(self):
        pass

    def json(self):
        return {"message": {"content": self._content}}


class FakePost:
    """Drop-in replacement for requests.post; queues one reply per call, or
    repeats the last one if more calls come in than replies were queued."""

    def __init__(self, replies: list[str]):
        self.replies = replies
        self.calls: list[dict] = []

    def __call__(self, url, json=None, timeout=None):
        self.calls.append({"url": url, "json": json, "timeout": timeout})
        idx = min(len(self.calls) - 1, len(self.replies) - 1)
        return FakeResponse(self.replies[idx])


def test_extract_profile_uses_schema_format_and_validates_result(monkeypatch):
    tool_output = {
        "contact": {"name": "Jane Doe", "email": "jane@example.com"},
        "education": [{"institution": "TU Munich", "degree": "BSc", "field": "Chemistry", "graduated": "2018"}],
        "certifications": [],
        "experience": [],
        "skills": ["HPLC", "GMP"],
        "languages": ["English", "German"],
    }
    fake_post = FakePost([json.dumps(tool_output)])
    monkeypatch.setattr(ollama_client.requests, "post", fake_post)

    profile = extractor_mod.extract_profile("some CV text", host="http://fake:11434", model="qwen2.5:1.5b")

    assert isinstance(profile, CandidateProfile)
    assert profile.contact.name == "Jane Doe"
    assert "HPLC" in profile.skills

    payload = fake_post.calls[0]["json"]
    assert payload["model"] == "qwen2.5:1.5b"
    assert "properties" in payload["format"]
    assert "version" not in payload["format"]["properties"]


def test_extract_profile_bumps_version_when_updating_existing(monkeypatch):
    tool_output = {"skills": ["Python"]}
    fake_post = FakePost([json.dumps(tool_output)])
    monkeypatch.setattr(ollama_client.requests, "post", fake_post)

    existing = CandidateProfile(version=3)
    profile = extractor_mod.extract_profile("text", host="http://fake:11434", existing=existing)

    assert profile.version == 4


def test_extract_profile_retries_on_invalid_json_then_succeeds(monkeypatch):
    tool_output = {"skills": ["Python"]}
    fake_post = FakePost(["not json at all", json.dumps(tool_output)])
    monkeypatch.setattr(ollama_client.requests, "post", fake_post)

    profile = extractor_mod.extract_profile("text", host="http://fake:11434")

    assert profile.skills == ["Python"]
    assert len(fake_post.calls) == 2


def test_extract_profile_requires_nonempty_text():
    import pytest

    with pytest.raises(ValueError, match="No text"):
        extractor_mod.extract_profile("   ")


def test_score_posting_attaches_job_id_and_validates(monkeypatch):
    tool_output = {
        "score": 88,
        "reasons": ["Strong QC background", "GMP certified"],
        "missing_requirements": [],
        "recommendation": "notify",
    }
    fake_post = FakePost([json.dumps(tool_output)])
    monkeypatch.setattr(ollama_client.requests, "post", fake_post)

    profile = CandidateProfile(skills=["GMP", "HPLC"])
    posting = JobPosting(source=JobSource.STEPSTONE, title="QC Analyst", company="Acme", location="Berlin")

    result = matcher_mod.score_posting(
        profile, posting, host="http://fake:11434", target_domains=["Life Science & Quality Control"]
    )

    assert result.job_id == posting.dedupe_id
    assert result.score == 88
    assert result.recommendation.value == "notify"

    prompt = fake_post.calls[0]["json"]["messages"][-1]["content"]
    assert "Life Science & Quality Control" in prompt


def test_score_posting_retries_on_semantically_invalid_output(monkeypatch):
    bad_output = {
        "score": 88,
        "reasons": [],
        "missing_requirements": [],
        "recommendation": "maybe",  # not a valid Recommendation enum value
    }
    good_output = {**bad_output, "recommendation": "watch"}
    fake_post = FakePost([json.dumps(bad_output), json.dumps(good_output)])
    monkeypatch.setattr(ollama_client.requests, "post", fake_post)

    profile = CandidateProfile(skills=["GMP"])
    posting = JobPosting(source=JobSource.STEPSTONE, title="QC Analyst", company="Acme", location="Berlin")

    result = matcher_mod.score_posting(profile, posting, host="http://fake:11434")

    assert result.recommendation.value == "watch"
    assert len(fake_post.calls) == 2
