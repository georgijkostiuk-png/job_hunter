"""A local LLM classifies inbound email threads: is this a recruiter reply tied to a
tracked application, and if so what's the new status?
"""

from __future__ import annotations

from ..llm.ollama_client import DEFAULT_HOST, DEFAULT_MODEL, generate_structured
from ..models import ApplicationStatus

SYSTEM_PROMPT = (
    "You triage one email thread to determine whether it relates to a job "
    "application and, if so, what status it implies. Be conservative: if the "
    "thread is unrelated to a job search (newsletters, unrelated personal "
    "email), set is_job_related to false. Reply with JSON only, matching the "
    "given schema."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "is_job_related": {"type": "boolean"},
        "company_guess": {"type": "string"},
        "status": {
            "type": "string",
            "enum": [s.value for s in ApplicationStatus],
        },
        "summary": {"type": "string", "description": "One sentence, plain language."},
    },
    "required": ["is_job_related", "status", "summary"],
}


def _validate(data: dict) -> dict:
    ApplicationStatus(data["status"])  # raises ValueError -> triggers a retry turn
    return dict(data)


def triage_thread(
    subject: str,
    body: str,
    *,
    host: str = DEFAULT_HOST,
    model: str = DEFAULT_MODEL,
) -> dict:
    prompt = f"Subject: {subject}\n\nBody:\n{body[:6000]}"

    return generate_structured(
        system=SYSTEM_PROMPT,
        prompt=prompt,
        schema=SCHEMA,
        validate=_validate,
        host=host,
        model=model,
        temperature=0.1,
        max_attempts=3,
    )
