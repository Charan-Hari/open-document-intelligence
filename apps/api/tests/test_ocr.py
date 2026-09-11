"""Tests for the optional local OCR adapter.

These tests never assume Tesseract/pytesseract are installed on the machine
running the suite: availability-dependent assertions use
``pytest.importorskip``/``pytest.skip`` so the suite stays green with or
without the optional ``ocr`` extra, while unavailability itself is always
tested via monkeypatching so the "no silent fallback" contract is checked
unconditionally.
"""

from __future__ import annotations

import sys

import pytest

from open_document_intelligence.ocr import OcrError, check_ocr_availability, ocr_image


def test_check_ocr_availability_reports_missing_pytesseract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "pytesseract", None)

    availability = check_ocr_availability()

    assert availability.available is False
    assert "pytesseract" in availability.reason


def test_check_ocr_availability_reports_missing_pillow(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("pytesseract")
    monkeypatch.setitem(sys.modules, "PIL", None)

    availability = check_ocr_availability()

    assert availability.available is False
    assert "Pillow" in availability.reason


def test_check_ocr_availability_reports_missing_tesseract_binary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytesseract = pytest.importorskip("pytesseract")
    pytest.importorskip("PIL")

    def _boom() -> None:
        raise OSError("tesseract is not installed or it's not in your PATH")

    monkeypatch.setattr(pytesseract, "get_tesseract_version", _boom)

    availability = check_ocr_availability()

    assert availability.available is False
    assert "tesseract" in availability.reason.lower()


def test_check_ocr_availability_when_fully_available() -> None:
    pytest.importorskip("pytesseract")
    pytest.importorskip("PIL")

    availability = check_ocr_availability()

    if not availability.available:
        pytest.skip(f"local tesseract binary not available here: {availability.reason}")
    assert availability.reason is None


def test_ocr_image_raises_when_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    import open_document_intelligence.ocr as ocr_module
    from open_document_intelligence.ocr import OcrAvailability

    monkeypatch.setattr(
        ocr_module, "check_ocr_availability", lambda: OcrAvailability(False, "no engine here")
    )

    with pytest.raises(OcrError, match="no engine here"):
        ocr_image(object())


def test_ocr_image_recognizes_rendered_text() -> None:
    pytest.importorskip("PIL")
    pytest.importorskip("pytesseract")
    from PIL import Image, ImageDraw

    availability = check_ocr_availability()
    if not availability.available:
        pytest.skip(f"local tesseract binary not available here: {availability.reason}")

    image = Image.new("RGB", (400, 120), "white")
    draw = ImageDraw.Draw(image)
    draw.text((10, 40), "HELLO WORLD", fill="black")

    text = ocr_image(image)

    assert "HELLO" in text.upper()
