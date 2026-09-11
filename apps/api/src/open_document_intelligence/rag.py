"""RAG orchestration: combines retrieval evidence and answer generation.

Kept as a distinct module (and response model) from the legacy
``/question`` endpoint so retrieval evidence and generated text are always
reported separately, per-document vector indexing is used automatically
when available, and the answer generator (Ollama or the extractive
fallback) is always named in the response.
"""

from __future__ import annotations

from uuid import UUID

from . import generation
from .models import DocumentChunk, RagResponse
from .retrieval import retrieve_evidence
from .vectorstore import VectorStore


def answer_with_rag(
    question: str,
    chunks: list[DocumentChunk],
    vector_store: VectorStore | None,
    document_id: UUID | str,
) -> RagResponse:
    evidence = retrieve_evidence(
        question, chunks, vector_store=vector_store, document_id=document_id
    )
    answer, generation_method = generation.generate_answer(question, evidence)
    confidence = round(sum(item.score for item in evidence) / len(evidence), 4) if evidence else 0.0
    return RagResponse(
        question=question,
        evidence=evidence,
        answer=answer,
        generation_method=generation_method,
        grounded=bool(evidence),
        confidence=confidence,
    )
