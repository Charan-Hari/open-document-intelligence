"""Tests for the RAG endpoint: retrieval evidence separated from generation,
vector retrieval with lexical fallback, and safe behavior when Ollama is
configured but unreachable.
"""

import pytest


def test_rag_endpoint_grounds_answer_with_vector_evidence(client) -> None:
    ingest = client.post("/v1/samples/sample-policy/ingest")
    document_id = ingest.json()["id"]

    response = client.post(
        f"/v1/documents/{document_id}/rag",
        json={"question": "Who owns this policy?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["grounded"] is True
    assert body["evidence"], "expected retrieval evidence"
    assert body["evidence"][0]["method"] == "vector"
    assert body["generation_method"] == "extractive"
    assert "Information Governance Office" in body["answer"]
    assert body["question"] == "Who owns this policy?"


def test_rag_endpoint_refuses_unsupported_question(client) -> None:
    ingest = client.post("/v1/samples/sample-policy/ingest")
    document_id = ingest.json()["id"]

    response = client.post(
        f"/v1/documents/{document_id}/rag",
        json={"question": "What is the average rainfall forecast in Seattle?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["grounded"] is False
    assert body["evidence"] == []
    assert body["generation_method"] == "none"


def test_rag_endpoint_falls_back_to_lexical_when_no_vector_index(client, monkeypatch) -> None:

    ingest = client.post("/v1/samples/sample-policy/ingest")
    document_id = ingest.json()["id"]

    # Simulate a document whose chunks were never indexed (e.g. indexing
    # failed) by clearing the app's vector store for this document.
    app = client.app
    with app.state.vector_store._connect() as conn:  # noqa: SLF001 - test-only introspection
        conn.execute("DELETE FROM chunk_vectors WHERE document_id = ?", (document_id,))
        conn.commit()

    response = client.post(
        f"/v1/documents/{document_id}/rag",
        json={"question": "Who owns this policy?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["grounded"] is True
    assert body["evidence"][0]["method"] == "lexical"


def test_rag_endpoint_unknown_document_returns_404(client) -> None:
    response = client.post(
        "/v1/documents/00000000-0000-0000-0000-000000000000/rag",
        json={"question": "Who owns this policy?"},
    )

    assert response.status_code == 404


@pytest.mark.parametrize("enabled_value", ["true", "1", "yes"])
def test_rag_falls_back_to_extractive_when_ollama_unreachable(
    client, monkeypatch, enabled_value
) -> None:
    # Ollama is "enabled" but nothing is listening on the configured port,
    # so the request must fail fast and fall back to the extractive
    # generator rather than raising or hanging.
    monkeypatch.setenv("ODI_ENABLE_OLLAMA", enabled_value)
    monkeypatch.setenv("ODI_OLLAMA_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("ODI_OLLAMA_TIMEOUT_SECONDS", "0.5")

    ingest = client.post("/v1/samples/sample-policy/ingest")
    document_id = ingest.json()["id"]

    response = client.post(
        f"/v1/documents/{document_id}/rag",
        json={"question": "Who owns this policy?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["generation_method"] == "extractive"
    assert body["grounded"] is True
    assert "Information Governance Office" in body["answer"]


def test_generation_error_is_raised_for_unreachable_ollama(monkeypatch) -> None:
    from open_document_intelligence import generation
    from open_document_intelligence.models import RetrievalMethod, RetrievedEvidence

    monkeypatch.setenv("ODI_OLLAMA_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("ODI_OLLAMA_TIMEOUT_SECONDS", "0.5")

    evidence = [
        RetrievedEvidence(
            chunk_id="chunk-1",
            page=1,
            line_start=1,
            line_end=1,
            text="Policy Owner: Information Governance Office",
            score=0.9,
            method=RetrievalMethod.vector,
        )
    ]

    with pytest.raises(generation.GenerationError):
        generation.generate_with_ollama(
            "Who owns this policy?",
            evidence,
        )
