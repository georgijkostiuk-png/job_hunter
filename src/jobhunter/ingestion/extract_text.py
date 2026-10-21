"""Turns a document file into raw text. OCR is a fallback, not the default path."""

from __future__ import annotations

import shutil
from pathlib import Path

OCR_FALLBACK_THRESHOLD = 50  # chars; below this, native extraction is treated as "empty"

# winget/most Windows installers put tesseract.exe here but don't refresh PATH
# for already-running shells (this process included) — so `shutil.which` alone
# can report "missing" right after a fresh install. Check the usual spots too.
_WINDOWS_FALLBACK_PATHS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
]

_tesseract_configured = False


class UnsupportedDocumentError(ValueError):
    pass


class OcrEngineNotFoundError(RuntimeError):
    pass


def _ensure_tesseract_configured() -> None:
    global _tesseract_configured
    if _tesseract_configured:
        return

    import pytesseract

    if shutil.which("tesseract"):
        _tesseract_configured = True
        return

    for candidate in _WINDOWS_FALLBACK_PATHS:
        if Path(candidate).exists():
            pytesseract.pytesseract.tesseract_cmd = candidate
            _tesseract_configured = True
            return

    raise OcrEngineNotFoundError(
        "Tesseract OCR engine not found. Install it (e.g. `winget install "
        "--id UB-Mannheim.TesseractOCR -e`) — pytesseract is only a Python "
        "wrapper around the real binary."
    )


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _extract_pdf(path)
    if suffix == ".docx":
        return _extract_docx(path)
    if suffix in (".txt", ".md"):
        return path.read_text(encoding="utf-8", errors="ignore")
    if suffix in (".png", ".jpg", ".jpeg", ".tiff", ".bmp"):
        return _ocr_image(path)
    raise UnsupportedDocumentError(f"No extractor for {suffix!r} ({path.name})")


def _extract_pdf(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    has_images = any(page.images for page in reader.pages)

    if len(text) < OCR_FALLBACK_THRESHOLD or has_images:
        try:
            ocr_text = _ocr_pdf(path)
        except OcrEngineNotFoundError:
            import logging

            logging.getLogger(__name__).warning(
                "%s looks scanned (little/no text layer) but Tesseract isn't installed, "
                "so it will be skipped. Install it to include this document.",
                path.name,
            )
            return text
        if len(ocr_text) > len(text):
            return ocr_text
    return text


def _ocr_pdf(path: Path) -> str:
    """Fallback for scanned PDFs with no text layer: rasterize each page, then OCR it."""
    _ensure_tesseract_configured()
    import pypdfium2 as pdfium
    import pytesseract

    parts: list[str] = []
    pdf = pdfium.PdfDocument(str(path))
    try:
        for page in pdf:
            bitmap = page.render(scale=300 / 72)  # ~300 DPI
            img = bitmap.to_pil()
            parts.append(pytesseract.image_to_string(img))
    finally:
        pdf.close()
    return "\n".join(parts).strip()


def _extract_docx(path: Path) -> str:
    import docx

    doc = docx.Document(str(path))
    return "\n".join(p.text for p in doc.paragraphs).strip()


def _ocr_image(path: Path) -> str:
    _ensure_tesseract_configured()
    import pytesseract
    from PIL import Image

    with Image.open(path) as img:
        return pytesseract.image_to_string(img).strip()
