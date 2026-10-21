"""Scores one JobPosting against the CandidateProfile via a local, schema-constrained LLM call."""

from __future__ import annotations

from ..llm.ollama_client import DEFAULT_HOST, DEFAULT_MODEL, generate_structured
from ..models import CandidateProfile, JobPosting, MatchResult

SYSTEM_PROMPT = (
    "You score how well a job posting fits a candidate. Score 0-100. Only "
    "recommend 'notify' for genuinely strong fits — being generous with scores "
    "defeats the purpose of filtering. A posting outside the candidate's target "
    "domains should score low even if individual skills overlap. Reply with "
    "JSON only, matching the given schema."
)

MATCH_RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "integer", "minimum": 0, "maximum": 100},
        "reasons": {"type": "array", "items": {"type": "string"}},
        "missing_requirements": {"type": "array", "items": {"type": "string"}},
        "recommendation": {"type": "string", "enum": ["notify", "watch", "skip"]},
    },
    "required": ["score", "reasons", "missing_requirements", "recommendation"],
}


def score_posting(
    profile: CandidateProfile,
    posting: JobPosting,
    *,
    host: str = DEFAULT_HOST,
    target_domains: list[str] | None = None,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.2,
) -> MatchResult:
    domains = ", ".join(target_domains) if target_domains else "(none set — score on profile fit alone)"
    prompt = (
        f"CANDIDATE TARGET DOMAINS: {domains}\n\n"
        f"CANDIDATE PROFILE:\n{profile.model_dump_json(indent=2)}\n\n"
        f"JOB POSTING:\n"
        f"Title: {posting.title}\n"
        f"Company: {posting.company}\n"
        f"Location: {posting.location}\n"
        f"Source: {posting.source.value}\n"
        f"Description:\n{posting.description}\n"
    )

    def _validate(data: dict) -> MatchResult:
        data = dict(data)
        data["job_id"] = posting.dedupe_id
        return MatchResult.model_validate(data)

    return generate_structured(
        system=SYSTEM_PROMPT,
        prompt=prompt,
        schema=MATCH_RESULT_SCHEMA,
        validate=_validate,
        host=host,
        model=model,
        temperature=temperature,
        max_attempts=3,
    )
