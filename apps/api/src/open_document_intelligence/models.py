from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class ProcessingStage(StrEnum):
    upload = "upload"
    parsing = "parsing"
    extraction = "extraction"
    evidence = "evidence"
    indexing = "indexing"
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


class DocumentChunk(BaseModel):
    id: str
    text: str
    page: int
    line_start: int
    line_end: int


class ExtractedField(BaseModel):
    key: str
    label: str
    value: str | None = None
    confidence: float = Field(default=0.0, ge=0, le=1)
    status: FieldStatus = FieldStatus.missing
    evidence_id: str | None = None


class WorkflowMode(StrEnum):
    """How a processing job actually ran.

    This project does not implement a background job queue. ``sync`` is the
    only honest value: a document is fully processed, start to finish,
    within the request that created it. The model exists so clients can
    inspect phase-by-phase results and failures without the API implying a
    poll-for-status async job it does not have.
    """

    sync = "sync"


class ProcessingJob(BaseModel):
    """A record of one processing run, exposed for transparency and audit."""

    document_id: UUID
    mode: WorkflowMode = WorkflowMode.sync
    status: ProcessingStatus
    stages: list[PipelineStage] = Field(default_factory=list)
    started_at: datetime
    completed_at: datetime
    duration_ms: float = Field(ge=0)
    error: str | None = None


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
    chunks: list[DocumentChunk] = Field(default_factory=list)
    text_preview: str | None = None
    page_count: int | None = None
    char_count: int | None = None
    error: str | None = None
    workflow: ProcessingJob | None = None


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


class QuestionRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)


class QuestionCitation(BaseModel):
    chunk_id: str
    page: int
    line_start: int
    line_end: int
    text: str
    score: float = Field(ge=0, le=1)


class QuestionResponse(BaseModel):
    answer: str
    confidence: float = Field(ge=0, le=1)
    citations: list[QuestionCitation] = Field(default_factory=list)
    grounded: bool


class RetrievalMethod(StrEnum):
    vector = "vector"
    lexical = "lexical"
    none = "none"


class GenerationMethod(StrEnum):
    ollama = "ollama"
    extractive = "extractive"
    none = "none"


class RagRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)


class RetrievedEvidence(BaseModel):
    """One piece of retrieval evidence, kept separate from any generated text."""

    chunk_id: str
    page: int
    line_start: int
    line_end: int
    text: str
    score: float = Field(ge=0, le=1)
    method: RetrievalMethod


class RagResponse(BaseModel):
    """A RAG answer with retrieval evidence and generation kept explicit.

    ``evidence`` is always the retrieved, citable source material and is
    populated the same way regardless of whether a generator is available.
    ``answer``/``generation_method`` describe how the natural-language
    answer was produced: an optional local Ollama model, or a safe
    extractive fallback that only ever quotes retrieved evidence.
    """

    question: str
    evidence: list[RetrievedEvidence] = Field(default_factory=list)
    answer: str
    generation_method: GenerationMethod
    grounded: bool
    confidence: float = Field(ge=0, le=1)
