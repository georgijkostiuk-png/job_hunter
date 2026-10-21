"""Turns raw document text into a CandidateProfile via a local, schema-constrained LLM call.

The request's `format` *is* CandidateProfile's JSON schema, so a change to the
model is the only place a schema change has to happen.
"""

from __future__ import annotations

import json

from ..llm.ollama_client import DEFAULT_HOST, DEFAULT_MODEL, generate_structured
from ..models import CandidateProfile

SYSTEM_PROMPT = (
    "You extract structured career/education data from personal documents "
    "(CVs, diplomas, certificates, reference letters). Only record what the "
    "source text actually states — never invent dates, employers, or "
    "qualifications. If a field is not present in the text, leave it empty "
    "rather than guessing. Every certificate or course-completion document in "
    "the sources must become its own entry in 'certifications', even if an "
    "existing profile lacks it. Reply with JSON only, matching the given schema."
)


def _schema() -> dict:
    schema = CandidateProfile.model_json_schema()
    # version/updated_at are set by this module, not the model.
    schema["properties"].pop("version", None)
    schema["properties"].pop("updated_at", None)
    required = schema.get("required")
    if required:
        schema["required"] = [f for f in required if f not in ("version", "updated_at")]
    return schema


def extract_profile(
    raw_text: str,
    *,
    host: str = DEFAULT_HOST,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.2,
    existing: CandidateProfile | None = None,
) -> CandidateProfile:
    if not raw_text.strip():
        raise ValueError("No text to extract from — inbox produced no readable documents.")

    user_prompt = (
        "Extract a candidate profile from the documents below. Merge information "
        "across all sources into one coherent profile.\n\n" + raw_text
    )
    if existing is not None:
        user_prompt += (
            "\n\n--- EXISTING PROFILE (update/extend this, don't discard confirmed facts) ---\n"
            + existing.model_dump_json(indent=2)
        )

    def _validate(data: dict) -> CandidateProfile:
        profile = CandidateProfile.model_validate(data)
        if existing is not None:
            profile.version = existing.version + 1
        return profile

    return generate_structured(
        system=SYSTEM_PROMPT,
        prompt=user_prompt,
        schema=_schema(),
        validate=_validate,
        host=host,
        model=model,
        temperature=temperature,
        max_attempts=3,
    )


def save_profile(profile: CandidateProfile, path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8")


def load_profile(path) -> CandidateProfile | None:
    if not path.exists():
        return None
    return CandidateProfile.model_validate_json(path.read_text(encoding="utf-8"))
