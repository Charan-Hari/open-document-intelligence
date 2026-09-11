"""Runs every uploaded or sample document through the visible processing pipeline.

Stages: upload -> parsing -> extraction -> evidence -> review. Each stage is
recorded with a status and human-readable detail so the UI can render exactly
what happened, and so failures stop the pipeline at the stage that failed
instead of silently continuing.
"""

from __future__ import annotations

from uuid import UUID

from .extraction import extract_fields, needs_review, overall_confidence
from .models import (
    DocumentChunk,
    DocumentDetail,
    DocumentSource,
    DocumentType,
    PipelineStage,
    ProcessingStage,
    ProcessingStatus,
    StageStatus,
)
from .parsing import Page, ParsingError, parse_document

MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
ALLOWED_EXTENSIONS = {".txt", ".md", ".csv", ".pdf"}


class ValidationError(Exception):
    """Raised when an uploaded file fails validation before processing starts."""


def validate_upload(filename: str, content: bytes) -> None:
    if not filename or "." not in filename:
        raise ValidationError("Uploaded file must have a name with an extension.")
    extension = "." + filename.rsplit(".", 1)[-1].lower()
    if extension not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise ValidationError(f"Unsupported file type '{extension}'. Allowed types: {allowed}.")
    if not content:
        raise ValidationError("Uploaded file is empty.")
    if len(content) > MAX_FILE_SIZE_BYTES:
        limit_mb = MAX_FILE_SIZE_BYTES // (1024 * 1024)
        raise ValidationError(f"File exceeds the {limit_mb} MB limit.")


def process_document(
    document_id: UUID,
    filename: str,
    content: bytes,
    document_type: DocumentType,
    source: DocumentSource,
) -> DocumentDetail:
    """Run the pipeline assuming ``validate_upload`` already passed.

    Basic input validation (extension, size, non-empty) is a client-input
    concern and is checked by the caller before a document record is even
    created. This function only records failures that happen once
    processing has started, such as a file that parses to no readable text.
    """
    stages: list[PipelineStage] = []

    stages.append(
        PipelineStage(
            stage=ProcessingStage.upload,
            label="Upload & validate",
            status=StageStatus.complete,
            detail=f"Stored {len(content):,} bytes as '{filename}'.",
        )
    )

    try:
        parsed = parse_document(filename, content)
    except ParsingError as exc:
        stages.append(
            PipelineStage(
                stage=ProcessingStage.parsing,
                label="Parse document",
                status=StageStatus.error,
                detail=str(exc),
            )
        )
        for stage, label in (
            (ProcessingStage.extraction, "Extract fields"),
            (ProcessingStage.evidence, "Find evidence"),
            (ProcessingStage.review, "Human review"),
        ):
            stages.append(
                PipelineStage(
                    stage=stage,
                    label=label,
                    status=StageStatus.skipped,
                    detail="Skipped because parsing failed.",
                )
            )
        return DocumentDetail(
            id=document_id,
            filename=filename,
            document_type=document_type,
            source=source,
            status=ProcessingStatus.failed,
            current_stage=ProcessingStage.parsing,
            confidence=None,
            stages=stages,
            error=str(exc),
        )

    stages.append(
        PipelineStage(
            stage=ProcessingStage.parsing,
            label="Parse document",
            status=StageStatus.complete,
            detail=(
                f"Extracted {parsed.char_count:,} characters across "
                f"{parsed.page_count} page(s)."
            ),
        )
    )

    chunks = _build_chunks(parsed.pages)
    fields, evidence = extract_fields(parsed, document_type)
    found_count = sum(1 for field in fields if field.value is not None)
    flagged = needs_review(fields)
    extraction_detail = (
        f"Extracted {found_count}/{len(fields)} field(s) for "
        f"document type '{document_type.value}'."
    )
    stages.append(
        PipelineStage(
            stage=ProcessingStage.extraction,
            label="Extract fields",
            status=StageStatus.needs_review if flagged else StageStatus.complete,
            detail=extraction_detail,
        )
    )

    stages.append(
        PipelineStage(
            stage=ProcessingStage.evidence,
            label="Find evidence",
            status=StageStatus.complete if evidence else StageStatus.needs_review,
            detail=(
                f"Linked {len(evidence)} citation(s) back to source pages and lines."
                if evidence
                else "No supporting evidence could be located in the document."
            ),
        )
    )

    review_flagged = [
        field for field in fields if field.status.value in ("needs_review", "missing")
    ]
    stages.append(
        PipelineStage(
            stage=ProcessingStage.review,
            label="Human review",
            status=StageStatus.needs_review if review_flagged else StageStatus.complete,
            detail=(
                f"{len(review_flagged)} field(s) need reviewer confirmation."
                if review_flagged
                else "All extracted fields met the confidence threshold."
            ),
        )
    )

    status = ProcessingStatus.needs_review if flagged else ProcessingStatus.ready
    confidence = overall_confidence(fields)

    return DocumentDetail(
        id=document_id,
        filename=filename,
        document_type=document_type,
        source=source,
        status=status,
        current_stage=ProcessingStage.review,
        confidence=confidence,
        stages=stages,
        fields=fields,
        evidence=evidence,
        chunks=chunks,
        text_preview=parsed.preview(),
        page_count=parsed.page_count,
        char_count=parsed.char_count,
        error=None,
    )


def _build_chunks(pages: list[Page]) -> list[DocumentChunk]:
    chunks: list[DocumentChunk] = []
    for page in pages:
        non_empty = [
            (number, line.strip())
            for number, line in enumerate(page.lines, start=1)
            if line.strip()
        ]
        for offset in range(0, len(non_empty), 4):
            window = non_empty[offset : offset + 4]
            if not window:
                continue
            chunks.append(
                DocumentChunk(
                    id=f"chunk-{len(chunks) + 1}",
                    text=" ".join(line for _, line in window),
                    page=page.number,
                    line_start=window[0][0],
                    line_end=window[-1][0],
                )
            )
    return chunks
