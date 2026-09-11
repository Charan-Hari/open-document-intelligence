# Open Document Intelligence

A local-first document intelligence workbench for inspecting contracts, policies,
invoices, forms, and operational documents with evidence-backed results.

## Product direction

The platform makes every processing phase visible:

1. Upload and validate
2. Parse text and layout
3. Extract structured fields
4. Retrieve supporting evidence
5. Validate and score confidence
6. Route uncertain results for human review
7. Preserve an auditable history

The first implementation is intentionally provider-neutral. Local parsing, OCR,
embeddings, and language models can be added without changing the API contract.

## What's implemented

- **Real multipart upload** (`POST /v1/documents`) with extension/size/empty-file
  validation, `.txt`/`.md`/`.csv` decoding, and `.pdf` text extraction via `pypdf`.
- **File-backed persistence**: raw uploads and JSON document records live under
  `apps/api/.data/` (configurable with `ODI_DATA_DIR`) and survive process restarts.
- **A visible processing pipeline** (upload → parsing → extraction → evidence →
  review) recorded per document, including error/skip states when a stage fails.
- **Deterministic, regex-based extraction** per document type (contract, invoice,
  policy, form, generic) with a confidence score per field.
- **Evidence & citations**: every extracted value links back to the exact page
  and line it came from.
- **Human review workflow** (`POST /v1/documents/{id}/review`) to approve or
  correct low-confidence/missing fields, which updates document status.
- **A bundled sample dataset catalog** (`GET /v1/samples`,
  `POST /v1/samples/{id}/ingest`) of synthetic contract/invoice/policy/form
  documents so the workbench is useful with zero setup.
- **A polished web UI** with upload + drag/drop, sample picker, a live pipeline
  stepper, a document list/detail view, and confidence/evidence/review controls.

## Repository layout

```text
apps/
  api/      FastAPI service and document domain
  web/      Browser workbench (upload, samples, pipeline, review UI)
docs/       Architecture and product notes
```

## Local development

### API

```powershell
cd apps/api
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
uvicorn open_document_intelligence.main:app --reload
```

The API is available at `http://localhost:8000`, with OpenAPI documentation at
`http://localhost:8000/docs`. Document data is stored under `apps/api/.data/`
by default; set `ODI_DATA_DIR` to use a different location.

Run the test suite and linter from `apps/api`:

```powershell
pytest
ruff check .
```

### Web

The UI is a dependency-free browser app that talks to the local API at
`http://localhost:8000` (override with `window.ODI_API_BASE` before
`app.js` loads). Serve the folder with any static file server, e.g.:

```powershell
cd apps/web
python -m http.server 8080
```

Then open `http://localhost:8080` with the API running.

## Principles

- Local-first and no required paid service
- Evidence before generated conclusions
- Explicit uncertainty instead of silent fallback
- Human review for low-confidence results
- Separate raw files, derived artifacts, and audit events
- Public or synthetic documents for demos

## Status

End-to-end local pipeline implemented: upload/validate, parse (text/PDF),
deterministic extraction, evidence citations, and a human review loop, plus a
sample dataset catalog and a full web UI. Future milestones: OCR for scanned
PDFs, pluggable ML/LLM extraction backends, and richer audit history.
