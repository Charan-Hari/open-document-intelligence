from open_document_intelligence.extraction import extract_fields, needs_review, overall_confidence
from open_document_intelligence.models import DocumentType, FieldStatus
from open_document_intelligence.parsing import parse_document


def test_extract_fields_contract_finds_parties_and_dates() -> None:
    text = (
        "This Agreement is made between Acme Corp and Globex LLC.\n"
        "Effective Date: 2024-05-01\n"
        "This Agreement may be terminated upon 60 days notice.\n"
        "This Agreement is governed by the laws of California.\n"
    )
    parsed = parse_document("contract.txt", text.encode())

    fields, evidence = extract_fields(parsed, DocumentType.contract)

    values = {field.key: field.value for field in fields}
    assert values["parties"] == "Acme Corp and Globex LLC"
    assert values["effective_date"] == "2024-05-01"
    assert values["termination_notice"] == "60"
    assert values["governing_law"] == "California"
    statuses = {field.key: field.status for field in fields}
    # High-confidence, unambiguous fields are auto-accepted...
    assert statuses["parties"] == FieldStatus.extracted
    assert statuses["effective_date"] == FieldStatus.extracted
    # ...while looser, context-based inferences are routed for human review.
    assert statuses["termination_notice"] == FieldStatus.needs_review
    assert statuses["governing_law"] == FieldStatus.needs_review
    assert len(evidence) == len(fields)
    assert overall_confidence(fields) > 0.8
    assert needs_review(fields) is True


def test_extract_fields_marks_missing_fields_for_review() -> None:
    parsed = parse_document("invoice.txt", b"Invoice Number: INV-1\n")

    fields, _ = extract_fields(parsed, DocumentType.invoice)

    statuses = {field.key: field.status for field in fields}
    assert statuses["invoice_number"] == FieldStatus.extracted
    assert statuses["total_due"] == FieldStatus.missing
    assert needs_review(fields) is True


def test_evidence_references_correct_page_and_line() -> None:
    parsed = parse_document("policy.txt", b"line one\nPolicy Owner: Legal Team\nline three\n")

    fields, evidence = extract_fields(parsed, DocumentType.policy)

    owner_evidence = next(e for e in evidence if e.field == "policy_owner")
    assert owner_evidence.page == 1
    assert owner_evidence.line == 2
    assert "Policy Owner" in owner_evidence.snippet
