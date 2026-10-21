"""Typed data contracts shared across every module in the pipeline."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, Field


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Education(BaseModel):
    institution: str
    degree: str = ""
    field: str = ""
    graduated: str = ""  # "YYYY-MM" or "YYYY", best-effort


class Certification(BaseModel):
    name: str
    issuer: str = ""
    issued: str = ""


class Experience(BaseModel):
    employer: str
    title: str
    start: str = ""
    end: str = ""  # empty string means "present"
    highlights: list[str] = Field(default_factory=list)


class Contact(BaseModel):
    name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""


class CandidateProfile(BaseModel):
    """The structured shape produced by the Extraction Engine (local LLM call).

    This is the single source of truth the Matcher scores every posting against.
    """

    contact: Contact = Field(default_factory=Contact)
    education: list[Education] = Field(default_factory=list)
    certifications: list[Certification] = Field(default_factory=list)
    experience: list[Experience] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    version: int = 1
    updated_at: str = Field(default_factory=utcnow_iso)


class JobSource(StrEnum):
    STEPSTONE = "stepstone"
    INDEED = "indeed"
    JOBVECTOR = "jobvector"
    LINKEDIN = "linkedin"


def normalize_for_hash(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


class JobPosting(BaseModel):
    source: JobSource
    title: str
    company: str
    location: str = ""
    url: str = ""
    description: str = ""
    posted_at: str = ""
    scraped_at: str = Field(default_factory=utcnow_iso)

    @property
    def dedupe_id(self) -> str:
        """sha256 of normalized (company, title, location).

        Deliberately NOT based on the URL: tracking params and re-listings
        change the URL without changing the underlying job.
        """
        key = "|".join(
            normalize_for_hash(v) for v in (self.company, self.title, self.location)
        )
        return hashlib.sha256(key.encode("utf-8")).hexdigest()


class Recommendation(StrEnum):
    NOTIFY = "notify"
    WATCH = "watch"
    SKIP = "skip"


class MatchResult(BaseModel):
    job_id: str
    score: int = Field(ge=0, le=100)
    reasons: list[str] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)
    recommendation: Recommendation
    scored_at: str = Field(default_factory=utcnow_iso)


class ApplicationStatus(StrEnum):
    DISCOVERED = "discovered"
    NOTIFIED = "notified"
    APPLIED = "applied"
    RESPONDED = "responded"
    INTERVIEW = "interview"
    CLOSED = "closed"
