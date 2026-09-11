"""Local, file-backed persistence for documents and their raw source files.

Everything lives under a single data directory so the whole workbench can be
inspected, backed up, or wiped with normal file tools. No database server and
no network calls are required.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from uuid import UUID

from .models import DocumentDetail


class DocumentStore:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.raw_dir = data_dir / "raw"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_path = data_dir / "documents.json"
        self._lock = threading.Lock()
        self._documents: dict[str, DocumentDetail] = {}
        self._load()

    def _load(self) -> None:
        if not self.metadata_path.exists():
            return
        raw = json.loads(self.metadata_path.read_text(encoding="utf-8"))
        for item in raw:
            document = DocumentDetail.model_validate(item)
            self._documents[str(document.id)] = document

    def _persist(self) -> None:
        payload = [
            document.model_dump(mode="json") for document in self._documents.values()
        ]
        self.metadata_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def add(self, document: DocumentDetail) -> None:
        with self._lock:
            self._documents[str(document.id)] = document
            self._persist()

    def update(self, document: DocumentDetail) -> None:
        self.add(document)

    def get(self, document_id: str) -> DocumentDetail | None:
        return self._documents.get(document_id)

    def list(self) -> list[DocumentDetail]:
        return sorted(self._documents.values(), key=lambda doc: doc.created_at, reverse=True)

    def save_raw_file(self, document_id: UUID, filename: str, content: bytes) -> Path:
        doc_dir = self.raw_dir / str(document_id)
        doc_dir.mkdir(parents=True, exist_ok=True)
        path = doc_dir / Path(filename).name
        path.write_bytes(content)
        return path
