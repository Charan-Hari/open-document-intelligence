from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class ProcessingStage(StrEnum):
    upload = "upload"
    parsing = "parsing"
    extraction = "extraction"
    evidence = "evidence"
    review = "review"


class StageStatus(StrEnum):
    pending = "pending"
    complete = "complete"
    needs_review = "needs_review"
    error = "error"
    skipped = "skipped"


class ProcessingStatus(StrEnum):
    pending = "pending"
    ready = "ready"
    needs_review = "needs_review"
    failed = "failed"


class DocumentType(StrEnum):
    contract = "contract"
    invoice = "invoice"
    policy = "policy"
    form = "form"
    generic = "generic"


class DocumentSource(StrEnum):
    upload = "upload"
    sample = "sample"


class FieldStatus(StrEnum):
    extracted = "extracted"
    needs_review = "needs_review"
    missing = "missing"
    confirmed = "confirmed"
    corrected = "corrected"


class PipelineStage(BaseModel):
    stage: ProcessingStage
    label: str
    status: StageStatus
    detail: str


class Evidence(BaseModel):
    id: str
    field: str | None = None
    snippet: str
    page: int
    line: int
    confidence: float = Field(ge=0, le=1)


class ExtractedField(BaseModel):
    key: str
    label: str
    value: str | None = None
    confidence: float = Field(default=0.0, ge=0, le=1)
    status: FieldStatus = FieldStatus.missing
    evidence_id: str | None = None


class DocumentSummary(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    filename: str
    document_type: DocumentType = DocumentType.generic
    source: DocumentSource = DocumentSource.upload
    status: ProcessingStatus = ProcessingStatus.pending
    current_stage: ProcessingStage = ProcessingStage.upload
    confidence: float | None = Field(default=None, ge=0, le=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class DocumentDetail(DocumentSummary):
    stages: list[PipelineStage] = Field(default_factory=list)
    fields: list[ExtractedField] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    text_preview: str | None = None
    page_count: int | None = None
    char_count: int | None = None
    error: str | None = None


class SampleCatalogEntry(BaseModel):
    id: str
    title: str
    description: str
    document_type: DocumentType
    filename: str


class ReviewDecision(StrEnum):
    approve = "approve"
    correct = "correct"


class ReviewRequest(BaseModel):
    field_key: str
    decision: ReviewDecision
    corrected_value: str | None = None
