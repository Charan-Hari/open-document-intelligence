"""Tests for the explicit processing workflow/job model.

Processing is synchronous end-to-end: these tests assert the workflow
record honestly reports ``mode: "sync"`` (no fake async/job-polling), that
phases/stages are recorded for both successful and failed processing runs,
and that failures are visible on the job record.
"""


def test_workflow_reports_sync_mode_and_stages_for_successful_run(client) -> None:
    ingest = client.post("/v1/samples/sample-invoice/ingest")
    document_id = ingest.json()["id"]

    response = client.get(f"/v1/documents/{document_id}/workflow")

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "sync"
    assert body["document_id"] == document_id
    assert body["status"] == "ready"
    assert body["error"] is None
    assert body["started_at"] <= body["completed_at"]
    assert body["duration_ms"] >= 0
    stage_names = [stage["stage"] for stage in body["stages"]]
    assert stage_names == ["upload", "parsing", "extraction", "evidence", "indexing", "review"]
    indexing_stage = next(stage for stage in body["stages"] if stage["stage"] == "indexing")
    assert indexing_stage["status"] == "complete"


def test_workflow_records_failure_when_parsing_fails(client) -> None:
    upload = client.post(
        "/v1/documents",
        files={"file": ("broken.pdf", b"not a real pdf", "application/pdf")},
    )
    document_id = upload.json()["id"]

    response = client.get(f"/v1/documents/{document_id}/workflow")

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "sync"
    assert body["status"] == "failed"
    assert body["error"]
    skipped_stages = {
        stage["stage"] for stage in body["stages"] if stage["status"] == "skipped"
    }
    assert "indexing" in skipped_stages
    assert "review" in skipped_stages


def test_workflow_matches_embedded_document_workflow_field(client) -> None:
    ingest = client.post("/v1/samples/sample-form/ingest")
    document_id = ingest.json()["id"]

    document = client.get(f"/v1/documents/{document_id}").json()
    workflow = client.get(f"/v1/documents/{document_id}/workflow").json()

    assert document["workflow"] == workflow


def test_workflow_unknown_document_returns_404(client) -> None:
    response = client.get("/v1/documents/00000000-0000-0000-0000-000000000000/workflow")

    assert response.status_code == 404
