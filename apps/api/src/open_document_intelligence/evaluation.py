"""Local, dependency-free evaluation harness for extraction and retrieval.

This is intentionally the smallest useful thing that lets us catch
regressions in the deterministic extraction rules and the retrieval
fallback: a small, hand-labeled "golden" set of expected field values and
expected retrieval keywords, checked against the bundled synthetic sample
documents. No network call, no paid API, and no external eval framework —
just re-running the real pipeline/retrieval code against known-good
documents and diffing the result.

Runnable three ways:

* Imported and called directly (``run_evaluation()``), e.g. from tests.
* As a CLI: ``python -m open_document_intelligence.evaluation`` — prints a
  JSON report and exits non-zero if any case regressed.
* Via the API: ``GET /v1/evaluation``.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from uuid import uuid4

from .models import (
    DocumentSource,
    DocumentType,
    EvaluationFieldCase,
    EvaluationReport,
    EvaluationRetrievalCase,
)
from .pipeline import process_document
from .retrieval import retrieve_evidence
from .samples import get_sample, read_sample_bytes


@dataclass(frozen=True)
class FieldExpectation:
    sample_id: str
    document_type: DocumentType
    field_key: str
    expected_value: str | None


@dataclass(frozen=True)
class RetrievalExpectation:
    sample_id: str
    document_type: DocumentType
    question: str
    expected_keyword: str


#: Hand-labeled expected extraction results for the bundled sample documents.
#: ``expected_value=None`` entries are known current gaps (e.g. fields whose
#: regex pattern doesn't span the line-wrapped source text) that are kept
#: here deliberately so a *change* in that behavior is still caught.
FIELD_EXPECTATIONS: list[FieldExpectation] = [
    FieldExpectation("sample-contract", DocumentType.contract, "effective_date", "2024-01-15"),
    FieldExpectation("sample-contract", DocumentType.contract, "parties", None),
    FieldExpectation("sample-invoice", DocumentType.invoice, "invoice_number", "INV-20458"),
    FieldExpectation("sample-invoice", DocumentType.invoice, "invoice_date", "2024-03-01"),
    FieldExpectation("sample-invoice", DocumentType.invoice, "due_date", "2024-03-31"),
    FieldExpectation("sample-invoice", DocumentType.invoice, "total_due", "820.80"),
    FieldExpectation(
        "sample-policy", DocumentType.policy, "policy_owner", "Information Governance Office"
    ),
    FieldExpectation("sample-policy", DocumentType.policy, "review_cycle", "Annual"),
    FieldExpectation("sample-form", DocumentType.form, "applicant_name", "Priya Natarajan"),
    FieldExpectation(
        "sample-form", DocumentType.form, "contact_email", "priya.natarajan@example.org"
    ),
]

#: Hand-labeled expected retrieval results: for each question, the expected
#: keyword/phrase must appear somewhere in the retrieved evidence text.
RETRIEVAL_EXPECTATIONS: list[RetrievalExpectation] = [
    RetrievalExpectation(
        "sample-policy",
        DocumentType.policy,
        "Who owns this policy?",
        "Information Governance Office",
    ),
    RetrievalExpectation(
        "sample-invoice", DocumentType.invoice, "What is the total due?", "820.80"
    ),
    RetrievalExpectation(
        "sample-contract", DocumentType.contract, "What is the effective date?", "2024-01-15"
    ),
    RetrievalExpectation(
        "sample-form", DocumentType.form, "Who is the applicant?", "Priya Natarajan"
    ),
]


def _process_sample(sample_id: str, document_type: DocumentType):
    entry = get_sample(sample_id)
    if entry is None:
        raise ValueError(f"Unknown sample id: {sample_id}")
    content = read_sample_bytes(entry)
    return process_document(
        document_id=uuid4(),
        filename=entry.filename,
        content=content,
        document_type=document_type,
        source=DocumentSource.sample,
    )


def evaluate_extraction() -> tuple[float, list[EvaluationFieldCase]]:
    """Re-run extraction on the golden samples and score against expectations."""
    cache: dict[str, object] = {}
    cases: list[EvaluationFieldCase] = []
    for expectation in FIELD_EXPECTATIONS:
        document = cache.get(expectation.sample_id)
        if document is None:
            document = _process_sample(expectation.sample_id, expectation.document_type)
            cache[expectation.sample_id] = document
        actual = next(
            (f.value for f in document.fields if f.key == expectation.field_key), None
        )
        cases.append(
            EvaluationFieldCase(
                sample_id=expectation.sample_id,
                field_key=expectation.field_key,
                expected_value=expectation.expected_value,
                actual_value=actual,
                correct=actual == expectation.expected_value,
            )
        )
    accuracy = (sum(1 for c in cases if c.correct) / len(cases)) if cases else 0.0
    return round(accuracy, 4), cases


def evaluate_retrieval() -> tuple[float, list[EvaluationRetrievalCase]]:
    """Re-run retrieval on the golden samples and score against expectations."""
    cache: dict[str, object] = {}
    cases: list[EvaluationRetrievalCase] = []
    for expectation in RETRIEVAL_EXPECTATIONS:
        document = cache.get(expectation.sample_id)
        if document is None:
            document = _process_sample(expectation.sample_id, expectation.document_type)
            cache[expectation.sample_id] = document
        evidence = retrieve_evidence(expectation.question, document.chunks)
        found = any(expectation.expected_keyword in item.text for item in evidence)
        cases.append(
            EvaluationRetrievalCase(
                sample_id=expectation.sample_id,
                question=expectation.question,
                expected_keyword=expectation.expected_keyword,
                found=found,
                top_score=evidence[0].score if evidence else None,
            )
        )
    hit_rate = (sum(1 for c in cases if c.found) / len(cases)) if cases else 0.0
    return round(hit_rate, 4), cases


def run_evaluation() -> EvaluationReport:
    """Run the full local evaluation harness and return the aggregate report."""
    extraction_accuracy, extraction_cases = evaluate_extraction()
    retrieval_hit_rate, retrieval_cases = evaluate_retrieval()
    return EvaluationReport(
        extraction_accuracy=extraction_accuracy,
        extraction_cases=extraction_cases,
        retrieval_hit_rate=retrieval_hit_rate,
        retrieval_cases=retrieval_cases,
    )


def main() -> int:
    """CLI entry point: print the JSON report, exit non-zero on any regression."""
    report = run_evaluation()
    print(json.dumps(report.model_dump(mode="json"), indent=2))
    regressions = [c for c in report.extraction_cases if not c.correct]
    regressions += [c for c in report.retrieval_cases if not c.found]
    return 1 if regressions else 0


if __name__ == "__main__":
    sys.exit(main())
