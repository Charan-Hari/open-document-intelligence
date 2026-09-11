"""Small, deterministic local retrieval engine for grounded document questions."""

from __future__ import annotations

import re

from .models import DocumentChunk, QuestionCitation, QuestionResponse

_STOP_WORDS = {
    "a", "an", "and", "are", "be", "by", "do", "for", "from", "how", "in",
    "is", "it", "of", "on", "or", "the", "to", "was", "what", "when", "where",
    "which", "who", "with",
}
_TERM_ALIASES = {"owns": "owner", "owned": "owner", "owning": "owner"}


def _terms(value: str) -> set[str]:
    return {
        _TERM_ALIASES.get(term, term)
        for term in re.findall(r"[a-z0-9]+", value.casefold())
        if term not in _STOP_WORDS and len(term) > 1
    }


def answer_question(question: str, chunks: list[DocumentChunk]) -> QuestionResponse:
    query_terms = _terms(question)
    ranked: list[tuple[float, DocumentChunk]] = []
    for chunk in chunks:
        chunk_terms = _terms(chunk.text)
        overlap = query_terms & chunk_terms
        if not overlap:
            continue
        score = min(1.0, len(overlap) / max(1, len(query_terms)))
        if score < 0.75:
            continue
        ranked.append((score, chunk))

    ranked.sort(key=lambda item: item[0], reverse=True)
    selected = ranked[:3]
    if not selected:
        return QuestionResponse(
            answer="I could not find enough evidence in this document to answer that question.",
            confidence=0.0,
            citations=[],
            grounded=False,
        )

    citations = [
        QuestionCitation(
            chunk_id=chunk.id,
            page=chunk.page,
            line_start=chunk.line_start,
            line_end=chunk.line_end,
            text=chunk.text,
            score=round(score, 4),
        )
        for score, chunk in selected
    ]
    answer = "Based on the document: " + " ".join(citation.text for citation in citations)
    return QuestionResponse(
        answer=answer,
        confidence=round(sum(score for score, _ in selected) / len(selected), 4),
        citations=citations,
        grounded=True,
    )
