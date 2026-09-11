"""Small, local retrieval engine for grounded document questions.

Two retrieval strategies are available:

* Vector similarity search against a persisted :class:`VectorStore`, when an
  index exists for the document and produces a confident match.
* A lexical term-overlap fallback (used by default, and whenever the vector
  store has no index or its best match is not confident), so retrieval
  degrades gracefully instead of failing.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .models import (
    DocumentChunk,
    QuestionCitation,
    QuestionResponse,
    RetrievalMethod,
    RetrievedEvidence,
)

if TYPE_CHECKING:
    from .vectorstore import VectorStore

_STOP_WORDS = {
    "a", "an", "and", "are", "be", "by", "do", "for", "from", "how", "in",
    "is", "it", "of", "on", "or", "the", "to", "was", "what", "when", "where",
    "which", "who", "with",
}
_TERM_ALIASES = {"owns": "owner", "owned": "owner", "owning": "owner"}

#: Minimum cosine similarity for a vector hit to be trusted over the lexical fallback.
VECTOR_SCORE_THRESHOLD = 0.2
#: Minimum lexical overlap ratio for a chunk to be considered relevant.
LEXICAL_SCORE_THRESHOLD = 0.75


def _terms(value: str) -> set[str]:
    return {
        _TERM_ALIASES.get(term, term)
        for term in re.findall(r"[a-z0-9]+", value.casefold())
        if term not in _STOP_WORDS and len(term) > 1
    }


def _lexical_search(
    question: str, chunks: list[DocumentChunk], top_k: int = 3
) -> list[RetrievedEvidence]:
    query_terms = _terms(question)
    ranked: list[tuple[float, DocumentChunk]] = []
    for chunk in chunks:
        chunk_terms = _terms(chunk.text)
        overlap = query_terms & chunk_terms
        if not overlap:
            continue
        score = min(1.0, len(overlap) / max(1, len(query_terms)))
        if score < LEXICAL_SCORE_THRESHOLD:
            continue
        ranked.append((score, chunk))

    ranked.sort(key=lambda item: item[0], reverse=True)
    return [
        RetrievedEvidence(
            chunk_id=chunk.id,
            page=chunk.page,
            line_start=chunk.line_start,
            line_end=chunk.line_end,
            text=chunk.text,
            score=round(score, 4),
            method=RetrievalMethod.lexical,
        )
        for score, chunk in ranked[:top_k]
    ]


def _vector_search(
    question: str, vector_store: VectorStore, document_id: object, top_k: int = 3
) -> list[RetrievedEvidence]:
    hits = vector_store.search(document_id, question, top_k=top_k)
    return [
        RetrievedEvidence(
            chunk_id=hit.id,
            page=hit.page,
            line_start=hit.line_start,
            line_end=hit.line_end,
            text=hit.text,
            score=round(hit.score, 4),
            method=RetrievalMethod.vector,
        )
        for hit in hits
        if hit.score >= VECTOR_SCORE_THRESHOLD
    ]


def retrieve_evidence(
    question: str,
    chunks: list[DocumentChunk],
    vector_store: VectorStore | None = None,
    document_id: object | None = None,
    top_k: int = 3,
) -> list[RetrievedEvidence]:
    """Retrieve the most relevant chunks for ``question``.

    Tries vector similarity search first when a vector store and document id
    are supplied and an index exists; falls back to lexical term-overlap
    search whenever the vector store is unavailable, has no index for this
    document, or returns no confident match.
    """
    if vector_store is not None and document_id is not None and vector_store.has_index(document_id):
        vector_hits = _vector_search(question, vector_store, document_id, top_k=top_k)
        if vector_hits:
            return vector_hits
    return _lexical_search(question, chunks, top_k=top_k)


def answer_question(question: str, chunks: list[DocumentChunk]) -> QuestionResponse:
    """Legacy lexical-only Q&A used by ``POST /v1/documents/{id}/question``.

    Kept deliberately simple and dependency-free for backward compatibility.
    New integrations should prefer the RAG endpoint (see ``rag.py``), which
    separates retrieval evidence from generated text and supports vector
    retrieval.
    """
    evidence = _lexical_search(question, chunks, top_k=3)
    if not evidence:
        return QuestionResponse(
            answer="I could not find enough evidence in this document to answer that question.",
            confidence=0.0,
            citations=[],
            grounded=False,
        )

    citations = [
        QuestionCitation(
            chunk_id=item.chunk_id,
            page=item.page,
            line_start=item.line_start,
            line_end=item.line_end,
            text=item.text,
            score=item.score,
        )
        for item in evidence
    ]
    answer = "Based on the document: " + " ".join(citation.text for citation in citations)
    return QuestionResponse(
        answer=answer,
        confidence=round(sum(item.score for item in evidence) / len(evidence), 4),
        citations=citations,
        grounded=True,
    )
