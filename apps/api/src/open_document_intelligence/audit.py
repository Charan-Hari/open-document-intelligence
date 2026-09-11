"""Append-only, file-backed audit trail for document processing and review.

Kept as a separate store (and separate JSON file) from ``DocumentStore`` so
document *state* (mutable, replaced on every update) and the *history* of
operations performed on a document (immutable, only ever appended to) don't
share a persistence model. Like the rest of this project, everything is
local: plain JSON on disk, no database server required.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from uuid import UUID

from .models import AuditEvent, AuditEventType


class AuditStore:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.audit_path = data_dir / "audit.json"
        self._lock = threading.Lock()
        self._events: list[AuditEvent] = []
        self._load()

    def _load(self) -> None:
        if not self.audit_path.exists():
            return
        raw = json.loads(self.audit_path.read_text(encoding="utf-8"))
        self._events = [AuditEvent.model_validate(item) for item in raw]

    def _persist(self) -> None:
        payload = [event.model_dump(mode="json") for event in self._events]
        self.audit_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def record(
        self,
        document_id: UUID,
        event_type: AuditEventType,
        detail: str,
        actor: str = "system",
    ) -> AuditEvent:
        """Append a new audit event for ``document_id`` and persist it."""
        with self._lock:
            event = AuditEvent(
                id=f"audit-{len(self._events) + 1}",
                document_id=document_id,
                event_type=event_type,
                actor=actor,
                detail=detail,
            )
            self._events.append(event)
            self._persist()
            return event

    def list_for_document(self, document_id: UUID | str) -> list[AuditEvent]:
        return [event for event in self._events if str(event.document_id) == str(document_id)]

    def list_all(self) -> list[AuditEvent]:
        return list(self._events)
