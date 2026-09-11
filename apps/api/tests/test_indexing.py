"""Unit tests for indexing behavior within the processing pipeline."""

from uuid import uuid4

from open_document_intelligence.models import (
    DocumentSource,
    DocumentType,
    ProcessingStage,
    StageStatus,
)
from open_document_intelligence.pipeline import process_document


def test_indexer_is_invoked_with_document_id_and_chunks() -> None:
    calls = []

    def fake_indexer(document_id, chunks):
        calls.append((document_id, chunks))

    document_id = uuid4()
    content = b"Policy Owner: Security Team\nReview Cycle: Quarterly\n"
    document = process_document(
        document_id=document_id,
        filename="policy.txt",
        content=content,
        document_type=DocumentType.policy,
        source=DocumentSource.upload,
        indexer=fake_indexer,
    )

    assert len(calls) == 1
    called_document_id, called_chunks = calls[0]
    assert called_document_id == document_id
    assert called_chunks == document.chunks
    indexing_stage = next(s for s in document.stages if s.stage == ProcessingStage.indexing)
    assert indexing_stage.status == StageStatus.complete


def test_indexer_failure_is_recorded_but_does_not_fail_document() -> None:
    def failing_indexer(document_id, chunks):
        raise RuntimeError("boom")

    content = b"Policy Owner: Security Team\nReview Cycle: Quarterly\n"
    document = process_document(
        document_id=uuid4(),
        filename="policy.txt",
        content=content,
        document_type=DocumentType.policy,
        source=DocumentSource.upload,
        indexer=failing_indexer,
    )

    indexing_stage = next(s for s in document.stages if s.stage == ProcessingStage.indexing)
    assert indexing_stage.status == StageStatus.error
    assert "boom" in indexing_stage.detail
    # Indexing is best-effort: a failure here must not fail the whole document.
    assert document.status.value != "failed"


def test_no_indexer_marks_stage_skipped() -> None:
    content = b"Policy Owner: Security Team\nReview Cycle: Quarterly\n"
    document = process_document(
        document_id=uuid4(),
        filename="policy.txt",
        content=content,
        document_type=DocumentType.policy,
        source=DocumentSource.upload,
    )

    indexing_stage = next(s for s in document.stages if s.stage == ProcessingStage.indexing)
    assert indexing_stage.status == StageStatus.skipped
