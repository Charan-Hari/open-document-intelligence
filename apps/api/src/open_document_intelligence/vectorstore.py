"""A dependency-light, locally persisted vector store for document chunks.

The store persists embeddings to a SQLite database (part of the Python
standard library, no server or extra package required) and computes cosine
similarity in pure Python. Two embedding backends are supported:

* :class:`HashingEmbedder` (default): a deterministic, dependency-free
  bag-of-words hashing embedding. It has no external model to download, is
  fully reproducible, and is good enough to rank chunks that share
  vocabulary with a query.
* :class:`SentenceTransformerEmbedder` (optional): used only if the
  ``sentence-transformers`` package is installed *and* explicitly requested
  via ``ODI_EMBEDDING_BACKEND=sentence-transformers``. It is never a hard
  dependency; if the package is missing or fails to load, callers
  automatically fall back to the hashing embedder.

Nothing here calls out to a network or paid service.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import threading
from pathlib import Path
from typing import Protocol
from uuid import UUID

from .models import DocumentChunk

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")

#: Common function words excluded so cosine similarity reflects shared
#: *content* words rather than shared grammar, which otherwise causes
#: spurious matches between unrelated sentences.
_STOP_WORDS = {
    "a", "an", "and", "any", "are", "as", "at", "be", "been", "by", "do",
    "does", "for", "from", "had", "has", "have", "how", "in", "is", "it",
    "its", "of", "on", "or", "such", "that", "the", "their", "this", "to",
    "was", "were", "what", "when", "where", "which", "who", "will", "with",
}


class Embedder(Protocol):
    """Turns text into a fixed-length vector of floats."""

    dimension: int

    def embed(self, text: str) -> list[float]: ...


class HashingEmbedder:
    """Deterministic, dependency-free bag-of-words hashing embedding.

    Every content token (stop words removed) is hashed with SHA-256 into
    one of ``dimension`` buckets and the resulting term-frequency vector is
    L2-normalized, so cosine similarity reduces to a plain dot product.
    This is not a semantic embedding, but it is fully local, requires no
    model download, and is reproducible across processes and machines.
    """

    def __init__(self, dimension: int = 2048) -> None:
        self.dimension = dimension

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        tokens = [
            token
            for token in _TOKEN_PATTERN.findall(text.casefold())
            if len(token) > 1 and token not in _STOP_WORDS
        ]
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
            index = int(digest, 16) % self.dimension
            vector[index] += 1.0
        norm = math.sqrt(sum(value * value for value in vector))
        if norm > 0:
            vector = [value / norm for value in vector]
        return vector


class SentenceTransformerEmbedder:
    """Optional semantic embedder backed by ``sentence-transformers``.

    Only imported and constructed when explicitly requested; if the
    dependency is not installed this raises ``ImportError`` and callers are
    expected to fall back to :class:`HashingEmbedder`.
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]

        self._model = SentenceTransformer(model_name)
        self.dimension = int(self._model.get_sentence_embedding_dimension())

    def embed(self, text: str) -> list[float]:
        vector = self._model.encode(text, normalize_embeddings=True)
        return [float(value) for value in vector]


def get_default_embedder() -> Embedder:
    """Select an embedder based on ``ODI_EMBEDDING_BACKEND`` (default: hashing)."""
    backend = os.environ.get("ODI_EMBEDDING_BACKEND", "hashing").strip().lower()
    if backend == "sentence-transformers":
        try:
            return SentenceTransformerEmbedder()
        except Exception:  # noqa: BLE001 - any failure means "not available here"
            return HashingEmbedder()
    return HashingEmbedder()


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class VectorHit(DocumentChunk):
    """A retrieved chunk plus its similarity score."""

    score: float


class VectorStore:
    """SQLite-persisted embeddings for document chunks, per document."""

    def __init__(self, db_path: Path, embedder: Embedder | None = None) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.embedder = embedder or get_default_embedder()
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chunk_vectors (
                    document_id TEXT NOT NULL,
                    chunk_id TEXT NOT NULL,
                    page INTEGER NOT NULL,
                    line_start INTEGER NOT NULL,
                    line_end INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    embedding TEXT NOT NULL,
                    PRIMARY KEY (document_id, chunk_id)
                )
                """
            )
            conn.commit()

    def index_chunks(self, document_id: UUID | str, chunks: list[DocumentChunk]) -> None:
        """Replace the index for a document with fresh embeddings for ``chunks``."""
        doc_id = str(document_id)
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM chunk_vectors WHERE document_id = ?", (doc_id,))
            for chunk in chunks:
                vector = self.embedder.embed(chunk.text)
                conn.execute(
                    """
                    INSERT INTO chunk_vectors
                        (document_id, chunk_id, page, line_start, line_end, text, embedding)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        doc_id,
                        chunk.id,
                        chunk.page,
                        chunk.line_start,
                        chunk.line_end,
                        chunk.text,
                        json.dumps(vector),
                    ),
                )
            conn.commit()

    def has_index(self, document_id: UUID | str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM chunk_vectors WHERE document_id = ? LIMIT 1",
                (str(document_id),),
            ).fetchone()
        return row is not None

    def search(
        self, document_id: UUID | str, query: str, top_k: int = 3
    ) -> list[VectorHit]:
        """Return the ``top_k`` most similar chunks to ``query`` for a document."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT chunk_id, page, line_start, line_end, text, embedding "
                "FROM chunk_vectors WHERE document_id = ?",
                (str(document_id),),
            ).fetchall()
        if not rows:
            return []

        query_vector = self.embedder.embed(query)
        scored: list[tuple[float, VectorHit]] = []
        for chunk_id, page, line_start, line_end, text, embedding_json in rows:
            vector = json.loads(embedding_json)
            score = _cosine_similarity(query_vector, vector)
            scored.append(
                (
                    score,
                    VectorHit(
                        id=chunk_id,
                        text=text,
                        page=page,
                        line_start=line_start,
                        line_end=line_end,
                        score=score,
                    ),
                )
            )
        scored.sort(key=lambda item: item[0], reverse=True)
        return [hit for _, hit in scored[:top_k]]
