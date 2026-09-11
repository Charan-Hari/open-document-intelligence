import os
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from .models import (
    DocumentDetail,
    DocumentSource,
    DocumentSummary,
    DocumentType,
    FieldStatus,
    ProcessingStatus,
    QuestionRequest,
    QuestionResponse,
    ReviewDecision,
    ReviewRequest,
    StageStatus,
)
from .pipeline import ValidationError, process_document, validate_upload
from .retrieval import answer_question
from .samples import SAMPLE_CATALOG, get_sample, read_sample_bytes
from .storage import DocumentStore

DEFAULT_DATA_DIR = Path(
    os.environ.get("ODI_DATA_DIR", Path(__file__).resolve().parents[2] / ".data")
)

PENDING_FIELD_STATUSES = (FieldStatus.needs_review, FieldStatus.missing)


def create_app(data_dir: Path | None = None) -> FastAPI:
    store = DocumentStore(data_dir or DEFAULT_DATA_DIR)

    app = FastAPI(
        title="Open Document Intelligence",
        version="0.1.0",
        description="Local-first, evidence-backed document processing workbench.",
    )
    allowed_origins = [
        origin.strip()
        for origin in os.environ.get("ODI_ALLOWED_ORIGINS", "http://localhost:8080").split(",")
        if origin.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    app.state.store = store

    def get_store() -> DocumentStore:
        return app.state.store

    StoreDep = Annotated[DocumentStore, Depends(get_store)]

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
        )
        if document.status != ProcessingStatus.failed:
            store.save_raw_file(document.id, entry.filename, content)
        store.add(document)
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
        )
        if document.status != ProcessingStatus.failed:
            store.save_raw_file(document.id, filename, content)
        store.add(document)
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
        return document

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
        )
        store.save_raw_file(document.id, entry.filename, content)
        store.add(document)
        return document

    return app


app = create_app()
