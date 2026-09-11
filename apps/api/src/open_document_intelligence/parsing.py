"""Turn raw uploaded bytes into page-oriented plain text.

Only local, dependency-light parsers are used so the pipeline works fully
offline: plain text/markdown is decoded directly and PDF pages are read with
``pypdf``. Unsupported formats raise :class:`ParsingError` so the pipeline can
surface a clear, local error instead of guessing.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

TEXT_EXTENSIONS = {".txt", ".md", ".csv"}
PDF_EXTENSIONS = {".pdf"}
SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | PDF_EXTENSIONS


class ParsingError(Exception):
    """Raised when a document cannot be parsed into text."""


@dataclass
class Page:
    number: int
    text: str
    lines: list[str]


@dataclass
class ParsedDocument:
    pages: list[Page]
    char_count: int

    @property
    def page_count(self) -> int:
        return len(self.pages)

    def preview(self, limit: int = 400) -> str:
        joined = "\n".join(page.text for page in self.pages).strip()
        if len(joined) <= limit:
            return joined
        return joined[:limit].rstrip() + "…"


def parse_document(filename: str, content: bytes) -> ParsedDocument:
    extension = Path(filename).suffix.lower()
    if extension in PDF_EXTENSIONS:
        return _parse_pdf(content)
    if extension in TEXT_EXTENSIONS:
        return _parse_text(content)
    raise ParsingError(f"Unsupported file type '{extension}'.")


def _parse_text(content: bytes) -> ParsedDocument:
    text = content.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    lines = text.splitlines() or [""]
    page = Page(number=1, text=text, lines=lines)
    return ParsedDocument(pages=[page], char_count=len(text))


def _parse_pdf(content: bytes) -> ParsedDocument:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise ParsingError("PDF parsing requires the 'pypdf' package.") from exc
    from io import BytesIO

    try:
        reader = PdfReader(BytesIO(content))
    except Exception as exc:  # noqa: BLE001 - surface as a parsing error
        raise ParsingError(f"Could not read PDF: {exc}") from exc

    pages: list[Page] = []
    char_count = 0
    for index, pdf_page in enumerate(reader.pages, start=1):
        try:
            text = pdf_page.extract_text() or ""
        except Exception:  # noqa: BLE001 - keep parsing remaining pages
            text = ""
        lines = text.splitlines() or [""]
        pages.append(Page(number=index, text=text, lines=lines))
        char_count += len(text)

    if not pages:
        raise ParsingError("PDF document contains no readable pages.")
    return ParsedDocument(pages=pages, char_count=char_count)
