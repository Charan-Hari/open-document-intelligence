"""Deterministic, regex-based field extraction.

Real document-intelligence products eventually plug in trained models or LLMs.
This module stays entirely local and deterministic: every document type has a
small set of named fields with a compiled pattern and a base confidence. Each
match is tied back to the exact page/line it came from so the UI can show
citations instead of unexplained answers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .models import DocumentType, Evidence, ExtractedField, FieldStatus
from .parsing import ParsedDocument

#: Fields with confidence at or above this threshold are auto-accepted.
CONFIDENCE_THRESHOLD = 0.8

_DATE_PATTERN = r"(?:\d{4}-\d{2}-\d{2}|[A-Z][a-z]+ \d{1,2},? \d{4})"


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    pattern: re.Pattern[str]
    base_confidence: float


def _spec(key: str, label: str, pattern: str, confidence: float) -> FieldSpec:
    return FieldSpec(
        key=key,
        label=label,
        pattern=re.compile(pattern, re.IGNORECASE),
        base_confidence=confidence,
    )


FIELD_SPECS: dict[DocumentType, list[FieldSpec]] = {
    DocumentType.contract: [
        _spec(
            "parties",
            "Contracting Parties",
            r"between\s+([^.,\n]+?)\s+and\s+([^.,\n]+)",
            0.86,
        ),
        _spec(
            "effective_date",
            "Effective Date",
            rf"effective\s+(?:date|as of)[:\s]+({_DATE_PATTERN})",
            0.9,
        ),
        _spec(
            "termination_notice",
            "Termination Notice",
            r"terminat\w*[^.\n]{0,80}?(\d+)\s+days",
            0.72,
        ),
        _spec(
            "governing_law",
            "Governing Law",
            r"governed by the laws of\s+([^.,\n]+)",
            0.78,
        ),
    ],
    DocumentType.invoice: [
        _spec(
            "invoice_number",
            "Invoice Number",
            r"invoice\s*(?:no\.?|number|#)[:\s]*([A-Z0-9\-]+)",
            0.92,
        ),
        _spec("invoice_date", "Invoice Date", rf"invoice date[:\s]+({_DATE_PATTERN})", 0.88),
        _spec("due_date", "Due Date", rf"due date[:\s]+({_DATE_PATTERN})", 0.88),
        _spec(
            "total_due",
            "Total Due",
            r"\btotal\s*(?:due|amount due)?[:\s]*\$?([\d,]+\.\d{2})",
            0.9,
        ),
    ],
    DocumentType.policy: [
        _spec("policy_owner", "Policy Owner", r"policy owner[:\s]+([^.,\n]+)", 0.85),
        _spec("review_cycle", "Review Cycle", r"review cycle[:\s]+([^.,\n]+)", 0.82),
        _spec("effective_date", "Effective Date", rf"effective date[:\s]+({_DATE_PATTERN})", 0.88),
    ],
    DocumentType.form: [
        _spec(
            "applicant_name",
            "Applicant Name",
            r"(?:applicant|full) name[:\s]+([^.,\n]+)",
            0.8,
        ),
        _spec(
            "submission_date",
            "Submission Date",
            rf"(?:submission|date submitted)[:\s]+({_DATE_PATTERN})",
            0.8,
        ),
        _spec("contact_email", "Contact Email", r"([\w.+-]+@[\w\-]+\.[\w.\-]+)", 0.75),
    ],
    DocumentType.generic: [
        _spec("contact_email", "Contact Email", r"([\w.+-]+@[\w\-]+\.[\w.\-]+)", 0.7),
        _spec("date_mentioned", "Date Mentioned", rf"({_DATE_PATTERN})", 0.6),
    ],
}


def extract_fields(
    parsed: ParsedDocument, document_type: DocumentType
) -> tuple[list[ExtractedField], list[Evidence]]:
    specs = FIELD_SPECS.get(document_type, FIELD_SPECS[DocumentType.generic])
    fields: list[ExtractedField] = []
    evidence: list[Evidence] = []
    evidence_counter = 0

    for spec in specs:
        match_found = False
        for page in parsed.pages:
            for line_number, line in enumerate(page.lines, start=1):
                match = spec.pattern.search(line)
                if not match:
                    continue
                value = _clean(match.group(1) if match.groups() else match.group(0))
                if spec.key == "parties" and len(match.groups()) >= 2:
                    value = f"{_clean(match.group(1))} and {_clean(match.group(2))}"

                evidence_counter += 1
                evidence_id = f"ev-{evidence_counter}"
                confidence = spec.base_confidence
                evidence.append(
                    Evidence(
                        id=evidence_id,
                        field=spec.key,
                        snippet=line.strip()[:280],
                        page=page.number,
                        line=line_number,
                        confidence=confidence,
                    )
                )
                status = (
                    FieldStatus.extracted
                    if confidence >= CONFIDENCE_THRESHOLD
                    else FieldStatus.needs_review
                )
                fields.append(
                    ExtractedField(
                        key=spec.key,
                        label=spec.label,
                        value=value,
                        confidence=confidence,
                        status=status,
                        evidence_id=evidence_id,
                    )
                )
                match_found = True
                break
            if match_found:
                break
        if not match_found:
            fields.append(
                ExtractedField(
                    key=spec.key,
                    label=spec.label,
                    value=None,
                    confidence=0.0,
                    status=FieldStatus.missing,
                    evidence_id=None,
                )
            )

    return fields, evidence


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().strip(",.")


def overall_confidence(fields: list[ExtractedField]) -> float:
    found = [field.confidence for field in fields if field.status != FieldStatus.missing]
    if not found:
        return 0.0
    return round(sum(found) / len(found), 4)


def needs_review(fields: list[ExtractedField]) -> bool:
    return any(field.status in (FieldStatus.needs_review, FieldStatus.missing) for field in fields)
