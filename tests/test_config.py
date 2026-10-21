from pathlib import Path

from jobhunter.config import load_settings

FIXTURE_YAML = """
paths:
  inbox_dir: "custom_inbox"
search:
  target_domains: ["Life Science & Quality Control"]
  queries: ["QC Analyst"]
  locations: ["Berlin"]
  sources: ["stepstone"]
matching:
  score_threshold: 55
scheduler:
  run_hours: [8, 20]
"""


def test_load_settings_reads_yaml_overrides(tmp_path: Path, monkeypatch):
    (tmp_path / "config.yaml").write_text(FIXTURE_YAML, encoding="utf-8")
    monkeypatch.delenv("OLLAMA_HOST", raising=False)

    settings = load_settings(root=tmp_path)

    assert settings.paths.inbox_dir == "custom_inbox"
    assert settings.search.queries == ["QC Analyst"]
    assert settings.matching.score_threshold == 55
    assert settings.scheduler.run_hours == [8, 20]


def test_load_settings_falls_back_to_defaults_when_no_file(tmp_path: Path):
    settings = load_settings(root=tmp_path)
    assert settings.matching.score_threshold == 70
    assert settings.scheduler.run_hours == [9, 18]
    assert settings.llm.model == "qwen2.5:1.5b"
    assert settings.llm.host == "http://localhost:11434"


def test_resolve_joins_relative_to_root(tmp_path: Path):
    settings = load_settings(root=tmp_path)
    resolved = settings.resolve("data/inbox")
    assert resolved == (tmp_path / "data" / "inbox").resolve()


def test_ollama_host_env_override(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "http://gpu-box:11434")
    settings = load_settings(root=tmp_path)
    assert settings.llm.host == "http://gpu-box:11434"
