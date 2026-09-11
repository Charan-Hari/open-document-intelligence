import os
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from .audit import AuditStore
from .evaluation import run_evaluation
from .models import (
    AuditEvent,
    AuditEventType,
    DocumentChunk,
    DocumentDetail,
    DocumentSource,
    DocumentSummary,
    DocumentType,
    EvaluationReport,
    FieldStatus,
    ProcessingJob,
    ProcessingStatus,
    QuestionRequest,
    QuestionResponse,
    RagRequest,
    RagResponse,
    ReviewDecision,
    ReviewRequest,
    StageStatus,
)
from .pipeline import ValidationError, process_document, validate_upload
from .rag import answer_with_rag
from .retrieval import answer_question
from .samples import SAMPLE_CATALOG, get_sample, read_sample_bytes
from .storage import DocumentStore
from .vectorstore import VectorStore

DEFAULT_DATA_DIR = Path(
    os.environ.get("ODI_DATA_DIR", Path(__file__).resolve().parents[2] / ".data")
)

PENDING_FIELD_STATUSES = (FieldStatus.needs_review, FieldStatus.missing)


def create_app(data_dir: Path | None = None, vector_store: VectorStore | None = None) -> FastAPI:
    resolved_data_dir = data_dir or DEFAULT_DATA_DIR
    store = DocumentStore(resolved_data_dir)
    audit = AuditStore(resolved_data_dir)
    vectors = vector_store or VectorStore(resolved_data_dir / "vectors.db")

    def index_chunks(document_id: UUID, chunks: list[DocumentChunk]) -> None:
        vectors.index_chunks(document_id, chunks)

    def _record_processed(document: DocumentDetail) -> None:
        """Record an audit trail entry for a completed processing run."""
        audit.record(
            document.id,
            AuditEventType.document_processed,
            detail=(
                f"Processed '{document.filename}' from {document.source.value}; "
                f"result: {document.status.value}."
            ),
        )

    app = FastAPI(
        title="Open Document Intelligence",
        version="0.1.0",
        description="Local-first, evidence-backed document processing workbench.",
    )
    # CORS defaults are intentionally restrictive: no wildcard origin, no
    # credentials, and only the methods/headers this API actually uses.
    allowed_origins = [
        origin.strip()
        for origin in os.environ.get("ODI_ALLOWED_ORIGINS", "http://localhost:8080").split(",")
        if origin.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    app.state.store = store
    app.state.vector_store = vectors

    def get_store() -> DocumentStore:
        return app.state.store

    def get_vector_store() -> VectorStore:
        return app.state.vector_store

    StoreDep = Annotated[DocumentStore, Depends(get_store)]
    VectorStoreDep = Annotated[VectorStore, Depends(get_vector_store)]

    @app.get("/health", tags=["operations"])
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "open-document-intelligence-api"}

    @app.get("/v1/samples", response_model=list[dict], tags=["samples"])
    def list_samples() -> list[dict]:
        return [entry.model_dump() for entry in SAMPLE_CATALOG]

    @app.post(
        "/v1/samples/{sample_id}/ingest",
        response_model=DocumentDetail,
        status_code=201,
        tags=["samples"],
    )
    def ingest_sample(sample_id: str, store: StoreDep) -> DocumentDetail:
        entry = get_sample(sample_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="Sample document was not found.")
        content = read_sample_bytes(entry)
        document_id = uuid4()
        document = process_document(
            document_id=document_id,
            filename=entry.filename,
            content=content,
            document_type=entry.document_type,
            source=DocumentSource.sample,
            indexer=index_chunks,
        )
        if document.status != ProcessingStatus.failed:
            store.save_raw_file(document.id, entry.filename, content)
        store.add(document)
        _record_processed(document)
        return document

    @app.get("/v1/documents", response_model=list[DocumentSummary], tags=["documents"])
    def list_documents(store: StoreDep) -> list[DocumentSummary]:
        return [DocumentSummary(**doc.model_dump()) for doc in store.list()]

    @app.get("/v1/documents/{document_id}", response_model=DocumentDetail, tags=["documents"])
    def get_document(document_id: str, store: StoreDep) -> DocumentDetail:
        document = store.get(document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="Document was not found.")
        return document

    @app.get(
        "/v1/documents/{document_id}/workflow",
        response_model=ProcessingJob,
        tags=["documents"],
    )
    def get_workflow(document_id: str, store: StoreDep) -> ProcessingJob:
        document = store.get(document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="Document was not found.")
        if document.workflow is None:
            raise HTTPException(
                status_code=404, detail="No workflow record is available for this document."
            )
        return document.workflow

    @app.post(
        "/v1/documents/{document_id}/question",
        response_model=QuestionResponse,
        tags=["retrieval"],
    )
    def question_document(
        document_id: str, request: QuestionRequest, store: StoreDep
    ) -> QuestionResponse:
        document = store.get(document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="Document was not found.")
        return answer_question(request.question, document.chunks)

    @app.post(
        "/v1/documents/{document_id}/rag",
        response_model=RagResponse,
        tags=["retrieval"],
    )
    def rag_document(
        document_id: str, request: RagRequest, store: StoreDep, vectors: VectorStoreDep
    ) -> RagResponse:
        document = store.get(document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="Document was not found.")
        return answer_with_rag(
            request.question, document.chunks, vector_store=vectors, document_id=document.id
        )

    @app.post("/v1/documents", response_model=DocumentDetail, status_code=201, tags=["documents"])
    async def upload_document(
        store: StoreDep,
        file: Annotated[UploadFile, File()],
        document_type: Annotated[DocumentType, Form()] = DocumentType.generic,
    ) -> DocumentDetail:
        content = await file.read()
        filename = file.filename or "upload"
        try:
            validate_upload(filename, content)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        document_id = uuid4()
        document = process_document(
            document_id=document_id,
            filename=filename,
            content=content,
            document_type=document_type,
            source=DocumentSource.upload,
            indexer=index_chunks,
        )
        if document.status != ProcessingStatus.failed:
            store.save_raw_file(document.id, filename, content)
        store.add(document)
        _record_processed(document)
        return document

    @app.post(
        "/v1/documents/{document_id}/review",
        response_model=DocumentDetail,
        tags=["documents"],
    )
    def review_field(document_id: str, review: ReviewRequest, store: StoreDep) -> DocumentDetail:
        document = store.get(document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="Document was not found.")

        target = next((field for field in document.fields if field.key == review.field_key), None)
        if target is None:
            raise HTTPException(status_code=404, detail="Field was not found on this document.")

        if review.decision == ReviewDecision.approve:
            target.status = FieldStatus.confirmed
            target.confidence = 1.0
        else:
            if not review.corrected_value:
                raise HTTPException(
                    status_code=422, detail="corrected_value is required to correct a field."
                )
            target.value = review.corrected_value
            target.status = FieldStatus.corrected
            target.confidence = 1.0

        still_pending = any(field.status in PENDING_FIELD_STATUSES for field in document.fields)
        document.status = ProcessingStatus.needs_review if still_pending else ProcessingStatus.ready
        for stage in document.stages:
            if stage.stage.value == "review":
                stage.status = StageStatus.needs_review if still_pending else StageStatus.complete
                pending_count = sum(
                    1 for f in document.fields if f.status in PENDING_FIELD_STATUSES
                )
                stage.detail = (
                    f"{pending_count} field(s) still need reviewer confirmation."
                    if still_pending
                    else "All fields confirmed by a reviewer."
                )

        store.update(document)
        audit.record(
            document.id,
            AuditEventType.field_reviewed,
            actor="reviewer",
            detail=(
                f"Field '{review.field_key}' {review.decision.value}d"
                + (f" to '{review.corrected_value}'" if review.corrected_value else "")
                + "."
            ),
        )
        return document

    @app.get(
        "/v1/documents/{document_id}/audit",
        response_model=list[AuditEvent],
        tags=["documents"],
    )
    def get_audit_trail(document_id: str, store: StoreDep) -> list[AuditEvent]:
        if store.get(document_id) is None:
            raise HTTPException(status_code=404, detail="Document was not found.")
        return audit.list_for_document(document_id)

    @app.get("/v1/evaluation", response_model=EvaluationReport, tags=["evaluation"])
    def get_evaluation() -> EvaluationReport:
        """Run the local extraction/retrieval evaluation harness on demand."""
        return run_evaluation()

    @app.post(
        "/v1/documents/demo", response_model=DocumentDetail, status_code=201, tags=["documents"]
    )
    def create_demo_document(store: StoreDep) -> DocumentDetail:
        entry = get_sample("sample-policy")
        assert entry is not None
        content = read_sample_bytes(entry)
        document_id = uuid4()
        document = process_document(
            document_id=document_id,
            filename=entry.filename,
            content=content,
            document_type=entry.document_type,
            source=DocumentSource.sample,
            indexer=index_chunks,
        )
        store.save_raw_file(document.id, entry.filename, content)
        store.add(document)
        _record_processed(document)
        return document

    return app


app = create_app()
