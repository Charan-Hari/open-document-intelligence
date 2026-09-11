"""Bundled sample documents so the workbench is useful before any upload.

Every sample is synthetic, written for this project, and ships as a plain
text (or, for the OCR demo, a rendered-then-flattened image-only PDF) file
inside the package so the catalog works fully offline. ``source``/``license``
are recorded on every catalog entry so it's always clear these are safe,
freely reusable synthetic examples rather than real third-party documents.
"""

from __future__ import annotations

from importlib import resources

from .models import DocumentType, SampleCatalogEntry

_SYNTHETIC_SOURCE = (
    "Synthetic example authored for this project; not derived from any real document."
)
_CC0_LICENSE = "CC0-1.0 (public domain dedication) — free to reuse without restriction."

SAMPLE_CATALOG: list[SampleCatalogEntry] = [
    SampleCatalogEntry(
        id="sample-contract",
        title="Master Services Agreement",
        description=(
            "A two-party services contract with term, termination, and governing law clauses."
        ),
        document_type=DocumentType.contract,
        filename="sample_contract.txt",
        source=_SYNTHETIC_SOURCE,
        license=_CC0_LICENSE,
    ),
    SampleCatalogEntry(
        id="sample-invoice",
        title="Medical Supply Invoice",
        description="A vendor invoice with line items, totals, and payment terms.",
        document_type=DocumentType.invoice,
        filename="sample_invoice.txt",
        source=_SYNTHETIC_SOURCE,
        license=_CC0_LICENSE,
    ),
    SampleCatalogEntry(
        id="sample-policy",
        title="Data Retention Policy",
        description="An internal governance policy defining ownership and review cadence.",
        document_type=DocumentType.policy,
        filename="sample_policy.txt",
        source=_SYNTHETIC_SOURCE,
        license=_CC0_LICENSE,
    ),
    SampleCatalogEntry(
        id="sample-form",
        title="Grant Application Form",
        description="A community grant application with applicant and project details.",
        document_type=DocumentType.form,
        filename="sample_form.txt",
        source=_SYNTHETIC_SOURCE,
        license=_CC0_LICENSE,
    ),
    SampleCatalogEntry(
        id="sample-scanned-notice",
        title="Scanned Facility Notice (OCR demo)",
        description=(
            "A synthetic image-only PDF (no text layer) that demonstrates the local OCR "
            "adapter: it is rendered from a generated image, the same way a scanned "
            "paper notice would be."
        ),
        document_type=DocumentType.generic,
        filename="sample_scanned_notice.pdf",
        source=(
            "Synthetic image rendered for this project with Pillow and flattened to a "
            "single-page, text-layer-free PDF; not derived from any real document or scan."
        ),
        license=_CC0_LICENSE,
    ),
]

_CATALOG_BY_ID = {entry.id: entry for entry in SAMPLE_CATALOG}


def get_sample(sample_id: str) -> SampleCatalogEntry | None:
    return _CATALOG_BY_ID.get(sample_id)


def read_sample_bytes(entry: SampleCatalogEntry) -> bytes:
    package = f"{__package__}.sample_data"
    return resources.files(package).joinpath(entry.filename).read_bytes()
