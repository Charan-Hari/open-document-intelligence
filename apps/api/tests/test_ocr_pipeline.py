"""Pipeline-level tests for OCR status surfaced on the processed document."""

from __future__ import annotations

from importlib import resources
from uuid import uuid4

import pytest

from open_document_intelligence.models import DocumentSource, DocumentType, OcrStatus
from open_document_intelligence.pipeline import process_document


def _scanned_notice_bytes() -> bytes:
    return (
        resources.files("open_document_intelligence.sample_data")
        .joinpath("sample_scanned_notice.pdf")
        .read_bytes()
    )


def test_text_document_reports_ocr_not_needed() -> None:
    document = process_document(
        document_id=uuid4(),
        filename="policy.txt",
        content=b"Policy Owner: Security Team\nReview Cycle: Quarterly\n",
        document_type=DocumentType.policy,
        source=DocumentSource.upload,
    )

    assert document.ocr_status == OcrStatus.not_needed
    assert document.pages_ocr_used == 0
    assert document.pages_needing_ocr == 0
    assert document.ocr_detail is None


def test_scanned_pdf_reports_ocr_unavailable_when_no_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import open_document_intelligence.parsing as parsing_module
    from open_document_intelligence.ocr import OcrAvailability

    monkeypatch.setattr(
        parsing_module,
        "check_ocr_availability",
        lambda: OcrAvailability(False, "pytesseract is not installed"),
    )

    document = process_document(
        document_id=uuid4(),
        filename="sample_scanned_notice.pdf",
        content=_scanned_notice_bytes(),
        document_type=DocumentType.generic,
        source=DocumentSource.upload,
    )

    assert document.ocr_status == OcrStatus.unavailable
    assert document.pages_needing_ocr == 1
    assert "pytesseract is not installed" in document.ocr_detail
    # No processing step is allowed to silently succeed when OCR is needed but missing.
    assert document.status.value == "needs_review"
    parsing_stage = next(s for s in document.stages if s.stage.value == "parsing")
    assert "OCR" in parsing_stage.detail


def test_scanned_pdf_uses_ocr_when_locally_available() -> None:
    pytest.importorskip("pytesseract")
    pytest.importorskip("PIL")
    from open_document_intelligence.ocr import check_ocr_availability

    availability = check_ocr_availability()
    if not availability.available:
        pytest.skip(f"local tesseract binary not available here: {availability.reason}")

    document = process_document(
        document_id=uuid4(),
        filename="sample_scanned_notice.pdf",
        content=_scanned_notice_bytes(),
        document_type=DocumentType.generic,
        source=DocumentSource.upload,
    )

    assert document.ocr_status == OcrStatus.used
    assert document.pages_ocr_used == 1
    assert document.pages_needing_ocr == 0
    field_values = {field.key: field.value for field in document.fields}
    assert field_values["contact_email"] == "facilities@example.org"
