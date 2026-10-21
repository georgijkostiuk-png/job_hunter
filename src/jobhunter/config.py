"""Loads config.yaml + .env into a single typed Settings object."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field


class PathsConfig(BaseModel):
    inbox_dir: str = "data/inbox"
    profile_path: str = "data/profile/profile.json"
    db_path: str = "data/state.db"
    google_credentials: str = "data/google_credentials.json"
    google_token: str = "data/google_token.json"


class SearchConfig(BaseModel):
    target_domains: list[str] = Field(default_factory=list)
    queries: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    # Optional: cluster near-duplicate/related queries under one label for
    # reporting (dry-run and run output). Purely presentational — every query
    # in `queries` still gets searched individually; this only affects how
    # results are grouped/deduped when printed or exported.
    query_groups: dict[str, list[str]] = Field(default_factory=dict)
    # None (default) = no cap, every adapter keeps paginating until the
    # listing runs out (see scraping/base.py's paginate_search). Set an
    # integer to stop each (query, location) search early once that many
    # postings have been collected from a source.
    max_postings_per_search: int | None = None


class MatchingConfig(BaseModel):
    score_threshold: int = 70


class SchedulerConfig(BaseModel):
    run_hours: list[int] = Field(default_factory=lambda: [9, 18])


class EmailConfig(BaseModel):
    notify_to: str = ""
    digest_subject: str = "Job matches — {count} new"
    # Reading the inbox (recruiter-reply triage) always needs Gmail OAuth,
    # even when sending is configured via SMTP app password. The first real
    # run blocks on the one-time browser consent screen until it's completed
    # end-to-end — set this false to skip triage entirely until you're ready
    # to finish that step, so `run` stops waiting on it.
    triage_enabled: bool = True


class LLMConfig(BaseModel):
    host: str = "http://localhost:11434"
    model: str = "qwen2.5:1.5b"
    extraction_temperature: float = 0.2
    matching_temperature: float = 0.2


class Settings(BaseModel):
    root: Path
    paths: PathsConfig = Field(default_factory=PathsConfig)
    search: SearchConfig = Field(default_factory=SearchConfig)
    matching: MatchingConfig = Field(default_factory=MatchingConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    email: EmailConfig = Field(default_factory=EmailConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)

    def resolve(self, relative: str) -> Path:
        return (self.root / relative).resolve()


def load_settings(config_path: str | Path | None = None, root: str | Path | None = None) -> Settings:
    project_root = Path(root) if root else Path.cwd()
    load_dotenv(project_root / ".env")

    cfg_file = Path(config_path or os.environ.get("JOBHUNTER_CONFIG", "config.yaml"))
    if not cfg_file.is_absolute():
        cfg_file = project_root / cfg_file

    raw: dict = {}
    if cfg_file.exists():
        raw = yaml.safe_load(cfg_file.read_text(encoding="utf-8")) or {}

    llm_conf = dict(raw.get("llm", {}))
    # OLLAMA_HOST is the standard env var Ollama itself uses; honor it here too
    # so a non-default host doesn't need to be duplicated into config.yaml.
    if os.environ.get("OLLAMA_HOST"):
        llm_conf["host"] = os.environ["OLLAMA_HOST"]

    settings = Settings(
        root=project_root,
        paths=PathsConfig(**raw.get("paths", {})),
        search=SearchConfig(**raw.get("search", {})),
        matching=MatchingConfig(**raw.get("matching", {})),
        scheduler=SchedulerConfig(**raw.get("scheduler", {})),
        email=EmailConfig(**raw.get("email", {})),
        llm=LLMConfig(**llm_conf),
    )
    return settings
