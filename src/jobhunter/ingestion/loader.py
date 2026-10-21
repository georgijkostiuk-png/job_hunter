"""Walks the inbox folder and turns every supported file into raw text."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .extract_text import UnsupportedDocumentError, extract_text

SUPPORTED_SUFFIXES = {".pdf", ".docx", ".txt", ".md", ".png", ".jpg", ".jpeg", ".tiff", ".bmp"}


@dataclass
class IngestedDocument:
    path: Path
    text: str


def load_inbox(inbox_dir: Path) -> list[IngestedDocument]:
    """Subfolders under inbox_dir are cosmetic — everything in the tree is processed."""
    if not inbox_dir.exists():
        return []

    documents: list[IngestedDocument] = []
    for path in sorted(inbox_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        try:
            text = extract_text(path)
        except UnsupportedDocumentError:
            continue
        if text.strip():
            documents.append(IngestedDocument(path=path, text=text))
    return documents


def combined_text(documents: list[IngestedDocument]) -> str:
    """One blob for the Extraction Engine, each source clearly marked for traceability."""
    blocks = [f"--- SOURCE: {d.path.name} ---\n{d.text}" for d in documents]
    return "\n\n".join(blocks)
