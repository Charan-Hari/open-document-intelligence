"""Tests for the persisted audit trail: recorded on processing and review."""

from __future__ import annotations


def test_audit_trail_records_processing_event(client) -> None:
    ingest = client.post("/v1/samples/sample-policy/ingest")
    document_id = ingest.json()["id"]

    response = client.get(f"/v1/documents/{document_id}/audit")

    assert response.status_code == 200
    events = response.json()
    assert len(events) == 1
    assert events[0]["event_type"] == "document_processed"
    assert events[0]["actor"] == "system"
    assert events[0]["document_id"] == document_id


def test_audit_trail_records_review_event(client) -> None:
    ingest = client.post("/v1/samples/sample-policy/ingest")
    document_id = ingest.json()["id"]

    client.post(
        f"/v1/documents/{document_id}/review",
        json={"field_key": "effective_date", "decision": "approve"},
    )

    events = client.get(f"/v1/documents/{document_id}/audit").json()

    assert [e["event_type"] for e in events] == ["document_processed", "field_reviewed"]
    review_event = events[1]
    assert review_event["actor"] == "reviewer"
    assert "effective_date" in review_event["detail"]


def test_audit_trail_unknown_document_returns_404(client) -> None:
    response = client.get("/v1/documents/00000000-0000-0000-0000-000000000000/audit")

    assert response.status_code == 404


def test_audit_trail_persists_across_app_restarts(tmp_path) -> None:
    from fastapi.testclient import TestClient

    from open_document_intelligence.main import create_app

    data_dir = tmp_path / "data"
    first_app = create_app(data_dir=data_dir)
    created = TestClient(first_app).post("/v1/samples/sample-form/ingest")
    document_id = created.json()["id"]

    second_app = create_app(data_dir=data_dir)
    response = TestClient(second_app).get(f"/v1/documents/{document_id}/audit")

    assert response.status_code == 200
    assert len(response.json()) == 1
