"""Bundled sample documents so the workbench is useful before any upload.

Every sample is synthetic, written for this project, and ships as a plain
text file inside the package so the catalog works fully offline.
"""

from __future__ import annotations

from importlib import resources

from .models import DocumentType, SampleCatalogEntry

SAMPLE_CATALOG: list[SampleCatalogEntry] = [
    SampleCatalogEntry(
        id="sample-contract",
        title="Master Services Agreement",
        description=(
            "A two-party services contract with term, termination, and governing law clauses."
        ),
        document_type=DocumentType.contract,
        filename="sample_contract.txt",
    ),
    SampleCatalogEntry(
        id="sample-invoice",
        title="Medical Supply Invoice",
        description="A vendor invoice with line items, totals, and payment terms.",
        document_type=DocumentType.invoice,
        filename="sample_invoice.txt",
    ),
    SampleCatalogEntry(
        id="sample-policy",
        title="Data Retention Policy",
        description="An internal governance policy defining ownership and review cadence.",
        document_type=DocumentType.policy,
        filename="sample_policy.txt",
    ),
    SampleCatalogEntry(
        id="sample-form",
        title="Grant Application Form",
        description="A community grant application with applicant and project details.",
        document_type=DocumentType.form,
        filename="sample_form.txt",
    ),
]

_CATALOG_BY_ID = {entry.id: entry for entry in SAMPLE_CATALOG}


def get_sample(sample_id: str) -> SampleCatalogEntry | None:
    return _CATALOG_BY_ID.get(sample_id)


def read_sample_bytes(entry: SampleCatalogEntry) -> bytes:
    package = f"{__package__}.sample_data"
    return resources.files(package).joinpath(entry.filename).read_bytes()
