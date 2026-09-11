"""Tests for the local extraction/retrieval evaluation harness."""

from __future__ import annotations

from open_document_intelligence.evaluation import (
    evaluate_extraction,
    evaluate_retrieval,
    run_evaluation,
)


def test_evaluate_extraction_matches_golden_expectations() -> None:
    accuracy, cases = evaluate_extraction()

    assert cases, "expected at least one extraction golden case"
    assert accuracy == 1.0
    assert all(case.correct for case in cases)


def test_evaluate_retrieval_matches_golden_expectations() -> None:
    hit_rate, cases = evaluate_retrieval()

    assert cases, "expected at least one retrieval golden case"
    assert hit_rate == 1.0
    assert all(case.found for case in cases)


def test_run_evaluation_returns_aggregate_report() -> None:
    report = run_evaluation()

    assert report.extraction_accuracy == 1.0
    assert report.retrieval_hit_rate == 1.0
    assert len(report.extraction_cases) > 0
    assert len(report.retrieval_cases) > 0


def test_evaluation_endpoint_returns_report(client) -> None:
    response = client.get("/v1/evaluation")

    assert response.status_code == 200
    body = response.json()
    assert body["extraction_accuracy"] == 1.0
    assert body["retrieval_hit_rate"] == 1.0
