"""In-memory adapter for locally generated OCR text sidecars."""

from __future__ import annotations


class OCRTextPage:
    """Small pdfplumber-compatible page for text-only compliance parsers."""

    def __init__(self, text: str):
        self._text = text

    def extract_text(self) -> str:
        return self._text


class OCRTextPdf:
    """Expose OCR pages through the subset of pdfplumber used by simple forms."""

    def __init__(self, page_text: list[str]):
        self.pages = [OCRTextPage(text) for text in page_text]


def read_ocr_sidecar(pdf_path: str) -> list[str]:
    """Read the temporary browser OCR sidecar, splitting pages on form-feed."""
    try:
        with open(pdf_path + ".ocr.txt", encoding="utf-8") as handle:
            return [page.strip() for page in handle.read().split("\f") if page.strip()]
    except OSError:
        return []
