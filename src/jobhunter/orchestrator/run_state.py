"""Tiny JSON bookkeeping for 'when did each source last run' — separate from the
tracker DB because it's scheduler mechanics, not application data.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def last_run(path: Path, source: str) -> datetime | None:
    data = _load(path)
    raw = data.get(source)
    return datetime.fromisoformat(raw) if raw else None


def mark_run(path: Path, source: str) -> None:
    data = _load(path)
    data[source] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _save(path, data)
