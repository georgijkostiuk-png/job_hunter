from __future__ import annotations

from .base import JobSiteAdapter
from .indeed import IndeedAdapter
from .jobvector import JobvectorAdapter
from .linkedin import LinkedInAdapter
from .stepstone import StepStoneAdapter

# Order matters: rising ToS/enforcement risk, see architecture.html compliance note.
ADAPTERS: dict[str, JobSiteAdapter] = {
    "stepstone": StepStoneAdapter(),
    "jobvector": JobvectorAdapter(),
    "indeed": IndeedAdapter(),
    "linkedin": LinkedInAdapter(),
}

LINKEDIN_MIN_INTERVAL_HOURS = 24  # LinkedIn adapter runs at most once per day


def get_adapters(source_names: list[str]) -> list[JobSiteAdapter]:
    return [ADAPTERS[name] for name in source_names if name in ADAPTERS]
