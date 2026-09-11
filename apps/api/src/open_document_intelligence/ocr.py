"""Optional, fully local OCR adapter for scanned/image-only PDF pages.

OCR is never a hard dependency of this project. Everything here is
exercised lazily, and every way OCR can be unavailable — the
``pytesseract``/``Pillow`` Python packages missing, or the local
``tesseract`` binary not being installed/discoverable — is reported through
:class:`OcrAvailability` with a precise, human-readable reason. Callers
*must* check ``OcrAvailability.available`` before assuming OCR ran; nothing
in this module silently treats "OCR unavailable" the same as "OCR ran and
found no text". Both pytesseract/Tesseract are local, free, open-source
tools — no network call or paid API is ever involved.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from io import BytesIO
from typing import Any

#: Common install locations checked when ``tesseract`` is not already on
#: ``PATH``. Only used as a fallback; ``ODI_TESSERACT_CMD`` always wins.
_WINDOWS_FALLBACK_PATHS = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
)


class OcrError(Exception):
    """Raised when an OCR pass is attempted but fails."""


@dataclass(frozen=True)
class OcrAvailability:
    """Whether OCR can run locally right now, and why not if it can't."""

    available: bool
    reason: str | None = None


def _configure_tesseract_cmd(pytesseract: Any) -> None:
    """Point pytesseract at a local tesseract binary if one can be found.

    Respects an explicit ``ODI_TESSERACT_CMD`` override first, then falls
    back to well-known Windows install paths when the binary is not already
    on ``PATH``. This never downloads or installs anything; it only looks
    at what is already present on the local machine.
    """
    override = os.environ.get("ODI_TESSERACT_CMD", "").strip()
    if override:
        pytesseract.pytesseract.tesseract_cmd = override
        return
    for candidate in _WINDOWS_FALLBACK_PATHS:
        if os.path.isfile(candidate):
            pytesseract.pytesseract.tesseract_cmd = candidate
            return


def check_ocr_availability() -> OcrAvailability:
    """Check whether local OCR can run, without ever raising.

    Returns an :class:`OcrAvailability` describing exactly which
    prerequisite is missing (the ``pytesseract`` package, the ``Pillow``
    package, or the ``tesseract`` binary itself) so the pipeline can surface
    a clear status instead of guessing.
    """
    try:
        import pytesseract
    except ImportError:
        return OcrAvailability(
            False, "The 'pytesseract' package is not installed (optional 'ocr' extra)."
        )
    try:
        import PIL  # noqa: F401
    except ImportError:
        return OcrAvailability(
            False, "The 'Pillow' package is not installed (optional 'ocr' extra)."
        )

    _configure_tesseract_cmd(pytesseract)
    try:
        pytesseract.get_tesseract_version()
    except Exception as exc:  # noqa: BLE001 - any failure means "not usable here"
        return OcrAvailability(
            False,
            "The local 'tesseract' binary was not found or failed to run "
            f"({exc}). Install Tesseract OCR, ensure it is on PATH, or set "
            "ODI_TESSERACT_CMD to its executable path.",
        )
    return OcrAvailability(True, None)


def ocr_image(image: Any) -> str:
    """Run local OCR on a PIL Image and return the recognized text.

    Raises :class:`OcrError` if OCR is unavailable or the OCR pass itself
    fails; never returns an empty string to mean "unavailable" so callers
    can distinguish a real (if empty) OCR result from a failed attempt.
    """
    availability = check_ocr_availability()
    if not availability.available:
        raise OcrError(f"OCR is not available: {availability.reason}")

    import pytesseract

    if hasattr(image, "data") and not hasattr(image, "save"):
        from PIL import Image

        image = Image.open(BytesIO(image.data))

    try:
        return pytesseract.image_to_string(image)
    except Exception as exc:  # noqa: BLE001 - surface as a clear OCR error
        raise OcrError(f"OCR failed: {exc}") from exc
