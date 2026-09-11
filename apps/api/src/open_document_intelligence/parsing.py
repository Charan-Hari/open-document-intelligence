"""Turn raw uploaded bytes into page-oriented plain text.

Only local, dependency-light parsers are used so the pipeline works fully
offline: plain text/markdown is decoded directly and PDF pages are read with
``pypdf``. Unsupported formats raise :class:`ParsingError` so the pipeline can
surface a clear, local error instead of guessing.

Scanned (image-only) PDF pages have no text layer for ``pypdf`` to extract.
Rather than silently returning empty text for those pages, each page records
*how* its text was obtained (:class:`TextSource`) so callers can distinguish
"this page had a text layer", "this page was OCR'd successfully", and "this
page needs OCR but it isn't available locally" instead of treating all three
as the same blank result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from .ocr import OcrError, check_ocr_availability, ocr_image

TEXT_EXTENSIONS = {".txt", ".md", ".csv"}
PDF_EXTENSIONS = {".pdf"}
SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | PDF_EXTENSIONS


class ParsingError(Exception):
    """Raised when a document cannot be parsed into text."""


class TextSource(StrEnum):
    """How a page's text was obtained."""

    #: The PDF (or text file) already had an extractable text layer.
    native_text = "native_text"
    #: No text layer was present; local OCR ran and produced text.
    ocr = "ocr"
    #: No text layer was present and the page has no image either, so there
    #: is nothing to OCR (e.g. a genuinely blank page).
    no_text = "no_text"
    #: No text layer was present and the page has an embedded image (looks
    #: like a scan), but local OCR is not available on this machine.
    ocr_unavailable = "ocr_unavailable"
    #: No text layer was present, OCR was available and attempted, but it
    #: raised an error instead of returning usable text.
    ocr_failed = "ocr_failed"


@dataclass
class Page:
    number: int
    text: str
    lines: list[str]
    source: TextSource = TextSource.native_text
    ocr_detail: str | None = None


@dataclass
class ParsedDocument:
    pages: list[Page]
    char_count: int
    ocr_availability_reason: str | None = field(default=None)

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def pages_ocr_used(self) -> int:
        return sum(1 for page in self.pages if page.source == TextSource.ocr)

    @property
    def pages_needing_ocr(self) -> int:
        """Pages that look scanned but could not be OCR'd on this machine."""
        return sum(1 for page in self.pages if page.source == TextSource.ocr_unavailable)

    @property
    def pages_ocr_failed(self) -> int:
        return sum(1 for page in self.pages if page.source == TextSource.ocr_failed)

    @property
    def needs_ocr(self) -> bool:
        return self.pages_needing_ocr > 0

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
    ocr_availability_reason: str | None = None
    for index, pdf_page in enumerate(reader.pages, start=1):
        try:
            text = pdf_page.extract_text() or ""
        except Exception:  # noqa: BLE001 - keep parsing remaining pages
            text = ""

        source = TextSource.native_text
        ocr_detail: str | None = None
        if not text.strip():
            text, source, ocr_detail = _resolve_missing_text(pdf_page)
            if source == TextSource.ocr_unavailable:
                ocr_availability_reason = ocr_detail

        lines = text.splitlines() or [""]
        pages.append(
            Page(number=index, text=text, lines=lines, source=source, ocr_detail=ocr_detail)
        )
        char_count += len(text)

    if not pages:
        raise ParsingError("PDF document contains no readable pages.")
    return ParsedDocument(
        pages=pages, char_count=char_count, ocr_availability_reason=ocr_availability_reason
    )


def _resolve_missing_text(pdf_page: object) -> tuple[str, TextSource, str | None]:
    """Handle a page with no native text layer.

    Checks whether the page carries an embedded image (typical of a scanned
    page) and, if so, attempts local OCR. Never guesses: a page that truly
    has no image is reported as ``no_text``, one with an image but no local
    OCR capability is reported as ``ocr_unavailable`` (with the exact
    reason), and a failed OCR attempt is reported as ``ocr_failed`` rather
    than silently falling back to empty text.
    """
    try:
        has_image = len(pdf_page.images) > 0  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - treat as "no image" if it can't be inspected
        has_image = False

    if not has_image:
        return "", TextSource.no_text, None

    availability = check_ocr_availability()
    if not availability.available:
        return "", TextSource.ocr_unavailable, availability.reason

    try:
        text = ocr_image(pdf_page.images[0])
    except OcrError as exc:
        return "", TextSource.ocr_failed, str(exc)
    except Exception as exc:  # noqa: BLE001 - e.g. Pillow couldn't decode the image
        return "", TextSource.ocr_failed, f"Could not read the page image for OCR: {exc}"

    if not text.strip():
        return "", TextSource.ocr_failed, "OCR ran but produced no recognizable text."
    return text, TextSource.ocr, None
