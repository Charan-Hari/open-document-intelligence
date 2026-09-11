def test_health(client) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_demo_document_exposes_processing_stages(client) -> None:
    response = client.post("/v1/documents/demo")

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "needs_review"
    assert [stage["stage"] for stage in body["stages"]] == [
        "upload",
        "parsing",
        "extraction",
        "evidence",
        "review",
    ]


def test_sample_catalog_is_listed(client) -> None:
    response = client.get("/v1/samples")

    assert response.status_code == 200
    body = response.json()
    ids = {entry["id"] for entry in body}
    assert {"sample-contract", "sample-invoice", "sample-policy", "sample-form"} <= ids


def test_sample_ingest_extracts_deterministic_fields(client) -> None:
    response = client.post("/v1/samples/sample-invoice/ingest")

    assert response.status_code == 201
    body = response.json()
    assert body["document_type"] == "invoice"
    assert body["source"] == "sample"
    field_values = {field["key"]: field["value"] for field in body["fields"]}
    assert field_values["invoice_number"] == "INV-20458"
    assert field_values["total_due"] == "820.80"
    assert body["status"] == "ready"
    assert body["evidence"], "expected citations linking fields back to source lines"


def test_sample_ingest_unknown_id_returns_404(client) -> None:
    response = client.post("/v1/samples/does-not-exist/ingest")

    assert response.status_code == 404


def test_upload_text_document_runs_full_pipeline(client) -> None:
    content = b"Policy Owner: Security Team\nReview Cycle: Quarterly\n"
    response = client.post(
        "/v1/documents",
        files={"file": ("policy.txt", content, "text/plain")},
        data={"document_type": "policy"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["filename"] == "policy.txt"
    assert body["page_count"] == 1
    assert body["char_count"] == len(content.decode())
    field_values = {field["key"]: field["value"] for field in body["fields"]}
    assert field_values["policy_owner"] == "Security Team"
    assert field_values["review_cycle"] == "Quarterly"
    # effective_date is absent from the content, so review is required.
    assert body["status"] == "needs_review"


def test_upload_rejects_unsupported_extension(client) -> None:
    response = client.post(
        "/v1/documents",
        files={"file": ("archive.zip", b"not-really-a-zip", "application/zip")},
    )

    assert response.status_code == 422
    assert "Unsupported file type" in response.json()["detail"]


def test_upload_rejects_empty_file(client) -> None:
    response = client.post(
        "/v1/documents",
        files={"file": ("empty.txt", b"", "text/plain")},
    )

    assert response.status_code == 422
    assert "empty" in response.json()["detail"]


def test_upload_corrupt_pdf_is_recorded_as_failed(client) -> None:
    response = client.post(
        "/v1/documents",
        files={"file": ("broken.pdf", b"not a real pdf", "application/pdf")},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "failed"
    parsing_stage = next(stage for stage in body["stages"] if stage["stage"] == "parsing")
    assert parsing_stage["status"] == "error"
    assert body["stages"][0]["status"] == "complete"  # upload itself succeeded


def test_document_list_and_detail_round_trip(client) -> None:
    upload = client.post(
        "/v1/documents",
        files={"file": ("notes.txt", b"Contact Email: person@example.com\n", "text/plain")},
    )
    document_id = upload.json()["id"]

    listing = client.get("/v1/documents")
    assert listing.status_code == 200
    assert any(doc["id"] == document_id for doc in listing.json())

    detail = client.get(f"/v1/documents/{document_id}")
    assert detail.status_code == 200
    assert detail.json()["id"] == document_id
    assert "fields" in detail.json()


def test_document_not_found_returns_404(client) -> None:
    response = client.get("/v1/documents/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404


def test_review_approve_resolves_flagged_field(client) -> None:
    ingest = client.post("/v1/samples/sample-policy/ingest")
    document_id = ingest.json()["id"]
    assert ingest.json()["status"] == "needs_review"

    response = client.post(
        f"/v1/documents/{document_id}/review",
        json={"field_key": "effective_date", "decision": "approve"},
    )

    assert response.status_code == 200
    body = response.json()
    field = next(f for f in body["fields"] if f["key"] == "effective_date")
    assert field["status"] == "confirmed"
    assert body["status"] == "ready"


def test_review_correct_updates_value(client) -> None:
    ingest = client.post("/v1/samples/sample-policy/ingest")
    document_id = ingest.json()["id"]

    response = client.post(
        f"/v1/documents/{document_id}/review",
        json={
            "field_key": "effective_date",
            "decision": "correct",
            "corrected_value": "2024-06-01",
        },
    )

    assert response.status_code == 200
    field = next(f for f in response.json()["fields"] if f["key"] == "effective_date")
    assert field["value"] == "2024-06-01"
    assert field["status"] == "corrected"


def test_review_missing_corrected_value_is_rejected(client) -> None:
    ingest = client.post("/v1/samples/sample-policy/ingest")
    document_id = ingest.json()["id"]

    response = client.post(
        f"/v1/documents/{document_id}/review",
        json={"field_key": "effective_date", "decision": "correct"},
    )

    assert response.status_code == 422


def test_documents_persist_across_app_restarts(tmp_path) -> None:
    from fastapi.testclient import TestClient

    from open_document_intelligence.main import create_app

    data_dir = tmp_path / "data"
    first_app = create_app(data_dir=data_dir)
    created = TestClient(first_app).post("/v1/samples/sample-form/ingest")
    document_id = created.json()["id"]

    second_app = create_app(data_dir=data_dir)
    response = TestClient(second_app).get(f"/v1/documents/{document_id}")

    assert response.status_code == 200
    assert response.json()["id"] == document_id
