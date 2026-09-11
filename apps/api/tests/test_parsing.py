import pytest

from open_document_intelligence.parsing import ParsingError, parse_document


def test_parse_text_counts_characters_and_lines() -> None:
    content = b"first line\nsecond line\n"

    parsed = parse_document("notes.txt", content)

    assert parsed.page_count == 1
    assert parsed.char_count == len(content.decode())
    assert parsed.pages[0].lines == ["first line", "second line"]


def test_parse_document_rejects_unsupported_extension() -> None:
    with pytest.raises(ParsingError):
        parse_document("archive.zip", b"data")


def test_parse_pdf_extracts_text_from_generated_pdf() -> None:
    pypdf = pytest.importorskip("pypdf")
    from io import BytesIO

    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = BytesIO()
    writer.write(buffer)

    parsed = parse_document("blank.pdf", buffer.getvalue())

    assert parsed.page_count == 1


def test_preview_truncates_long_text() -> None:
    content = ("a" * 1000).encode()

    parsed = parse_document("long.txt", content)

    preview = parsed.preview(limit=50)
    assert len(preview) <= 51
    assert preview.endswith("…")


def _scanned_notice_bytes() -> bytes:
    from importlib import resources

    return (
        resources.files("open_document_intelligence.sample_data")
        .joinpath("sample_scanned_notice.pdf")
        .read_bytes()
    )


def test_parse_pdf_blank_page_reports_no_text() -> None:
    pypdf = pytest.importorskip("pypdf")
    from io import BytesIO

    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = BytesIO()
    writer.write(buffer)

    parsed = parse_document("blank.pdf", buffer.getvalue())

    page = parsed.pages[0]
    assert page.source.value == "no_text"
    assert page.text == ""
    assert parsed.needs_ocr is False
    assert parsed.pages_ocr_used == 0


def test_parse_pdf_reports_ocr_unavailable_when_no_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    import open_document_intelligence.parsing as parsing_module
    from open_document_intelligence.ocr import OcrAvailability

    monkeypatch.setattr(
        parsing_module,
        "check_ocr_availability",
        lambda: OcrAvailability(False, "no engine available in this test"),
    )

    parsed = parse_document("sample_scanned_notice.pdf", _scanned_notice_bytes())

    assert parsed.page_count == 1
    page = parsed.pages[0]
    assert page.text == ""
    assert page.source.value == "ocr_unavailable"
    assert "no engine available in this test" in page.ocr_detail
    assert parsed.needs_ocr is True
    assert parsed.pages_needing_ocr == 1
    assert parsed.pages_ocr_used == 0
    assert "no engine available in this test" in parsed.ocr_availability_reason


def test_parse_pdf_reports_ocr_failed_when_ocr_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    import open_document_intelligence.parsing as parsing_module
    from open_document_intelligence.ocr import OcrAvailability, OcrError

    monkeypatch.setattr(
        parsing_module, "check_ocr_availability", lambda: OcrAvailability(True, None)
    )

    def _boom(image: object) -> str:
        raise OcrError("synthetic OCR failure for testing")

    monkeypatch.setattr(parsing_module, "ocr_image", _boom)

    parsed = parse_document("sample_scanned_notice.pdf", _scanned_notice_bytes())

    page = parsed.pages[0]
    assert page.source.value == "ocr_failed"
    assert "synthetic OCR failure" in page.ocr_detail
    assert parsed.pages_ocr_failed == 1
    assert parsed.pages_needing_ocr == 0


def test_parse_pdf_uses_ocr_when_locally_available() -> None:
    pytest.importorskip("pytesseract")
    pytest.importorskip("PIL")
    from open_document_intelligence.ocr import check_ocr_availability

    availability = check_ocr_availability()
    if not availability.available:
        pytest.skip(f"local tesseract binary not available here: {availability.reason}")

    parsed = parse_document("sample_scanned_notice.pdf", _scanned_notice_bytes())

    assert parsed.pages_ocr_used == 1
    assert parsed.pages_needing_ocr == 0
    assert parsed.pages_ocr_failed == 0
    page = parsed.pages[0]
    assert page.source.value == "ocr"
    assert "NOTC-2024-004" in page.text
