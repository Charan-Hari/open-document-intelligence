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
