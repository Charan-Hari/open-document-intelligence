"""Answer generation, kept explicitly separate from retrieval.

Two generators are available:

* Ollama (optional): calls a local Ollama server's HTTP API
  (``http://localhost:11434`` by default) if ``ODI_ENABLE_OLLAMA`` is set
  truthy. Uses only the Python standard library (``urllib``), so no new
  dependency is required. Any failure (server not running, timeout, bad
  response) raises :class:`GenerationError` and callers fall back safely.
* Extractive fallback (always available): builds an answer strictly by
  quoting the retrieved evidence chunks. It never invents text that is not
  present in the retrieved evidence, so it is always grounded when evidence
  exists.

No paid or cloud service is used by either path.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from .models import GenerationMethod, RetrievedEvidence

NO_EVIDENCE_ANSWER = "I could not find enough evidence in this document to answer that question."


class GenerationError(Exception):
    """Raised when a generator cannot produce an answer."""


def ollama_enabled() -> bool:
    return os.environ.get("ODI_ENABLE_OLLAMA", "false").strip().lower() in {"1", "true", "yes"}


def _ollama_base_url() -> str:
    return os.environ.get("ODI_OLLAMA_URL", "http://localhost:11434").rstrip("/")


def _ollama_model() -> str:
    return os.environ.get("ODI_OLLAMA_MODEL", "llama3.2")


def _ollama_timeout() -> float:
    return float(os.environ.get("ODI_OLLAMA_TIMEOUT_SECONDS", "5"))


def _build_prompt(question: str, evidence: list[RetrievedEvidence]) -> str:
    context = "\n\n".join(
        f"[Source page {item.page}, lines {item.line_start}-{item.line_end}]\n{item.text}"
        for item in evidence
    )
    return (
        "Answer the question using ONLY the context below. "
        "If the context does not contain the answer, say you do not know.\n\n"
        f"Context:\n{context}\n\nQuestion: {question}\nAnswer:"
    )


def generate_with_ollama(question: str, evidence: list[RetrievedEvidence]) -> str:
    """Call a local Ollama server. Raises GenerationError on any failure."""
    prompt = _build_prompt(question, evidence)
    payload = json.dumps(
        {"model": _ollama_model(), "prompt": prompt, "stream": False}
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{_ollama_base_url()}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=_ollama_timeout()) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
        raise GenerationError(f"Ollama request failed: {exc}") from exc

    answer = str(body.get("response", "")).strip()
    if not answer:
        raise GenerationError("Ollama returned an empty response.")
    return answer


def generate_extractive_answer(evidence: list[RetrievedEvidence]) -> str:
    """A safe fallback: quote retrieved evidence verbatim, never hallucinate."""
    if not evidence:
        return NO_EVIDENCE_ANSWER
    return "Based on the document: " + " ".join(item.text for item in evidence)


def generate_answer(
    question: str, evidence: list[RetrievedEvidence]
) -> tuple[str, GenerationMethod]:
    """Produce ``(answer, generation_method)`` for the given evidence.

    Prefers Ollama when explicitly enabled and reachable; always falls back
    to the deterministic extractive generator otherwise, so an answer is
    never silently dropped just because a local LLM isn't running.
    """
    if not evidence:
        return NO_EVIDENCE_ANSWER, GenerationMethod.none

    if ollama_enabled():
        try:
            return generate_with_ollama(question, evidence), GenerationMethod.ollama
        except GenerationError:
            pass

    return generate_extractive_answer(evidence), GenerationMethod.extractive
