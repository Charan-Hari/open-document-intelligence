// Default to same-origin (empty base) so a single combined deployment (e.g.
// the Docker image, Hugging Face Spaces) just works with no config. Local
// dev serves the UI from a separate static server (see README), so it falls
// back to the API's default port in that one specific case.
const API_BASE =
  window.ODI_API_BASE !== undefined
    ? window.ODI_API_BASE
    : window.location.port === '8080'
      ? 'http://localhost:8000'
      : '';

const STAGE_LABELS = {
  upload: 'Upload & validate',
  parsing: 'Parse document',
  extraction: 'Extract fields',
  evidence: 'Find evidence',
  indexing: 'Index for retrieval',
  review: 'Human review',
};

const STAGE_ORDER = ['upload', 'parsing', 'extraction', 'evidence', 'indexing', 'review'];

const state = {
  documents: [],
  selectedId: null,
};

const els = {
  apiStatus: document.querySelector('#api-status'),
  docCount: document.querySelector('#doc-count'),
  pipeline: document.querySelector('#pipeline'),
  status: document.querySelector('#status'),
  uploadForm: document.querySelector('#upload-form'),
  uploadButton: document.querySelector('#upload-button'),
  uploadError: document.querySelector('#upload-error'),
  fileInput: document.querySelector('#file-input'),
  dropzone: document.querySelector('#dropzone'),
  selectedFile: document.querySelector('#selected-file'),
  documentType: document.querySelector('#document-type'),
  sampleList: document.querySelector('#sample-list'),
  documentList: document.querySelector('#document-list'),
  refreshDocuments: document.querySelector('#refresh-documents'),
  detailTitle: document.querySelector('#detail-title'),
  detailConfidence: document.querySelector('#detail-confidence'),
  detailEmpty: document.querySelector('#detail-empty'),
  detailContent: document.querySelector('#detail-content'),
  detailMeta: document.querySelector('#detail-meta'),
  detailError: document.querySelector('#detail-error'),
  ocrStatus: document.querySelector('#ocr-status'),
  fieldList: document.querySelector('#field-list'),
  evidenceList: document.querySelector('#evidence-list'),
  textPreview: document.querySelector('#text-preview'),
  auditList: document.querySelector('#audit-list'),
  questionForm: document.querySelector('#question-form'),
  questionInput: document.querySelector('#question-input'),
  questionError: document.querySelector('#question-error'),
  questionAnswer: document.querySelector('#question-answer'),
  runEvaluation: document.querySelector('#run-evaluation'),
  evaluationResult: document.querySelector('#evaluation-result'),
  evaluationError: document.querySelector('#evaluation-error'),
};

function escapeHtml(value) {
  const div = document.createElement('div');
  div.textContent = value ?? '';
  return div.innerHTML;
}

function formatStageStatus(status) {
  return status.replace(/_/g, ' ');
}

function renderStages(stages) {
  const source = stages && stages.length
    ? stages
    : STAGE_ORDER.map((stage) => ({
        stage,
        label: STAGE_LABELS[stage],
        status: 'pending',
        detail: 'Not started yet.',
      }));

  els.pipeline.innerHTML = source
    .map((stage, index) => `
      <div class="stage ${stage.status}">
        <div class="stage-number">${String(index + 1).padStart(2, '0')}</div>
        <div><strong>${escapeHtml(stage.label)}</strong><span>${escapeHtml(stage.detail)}</span></div>
        <b>${formatStageStatus(stage.status)}</b>
      </div>`)
    .join('');
}

function statusLabel(status) {
  return {
    pending: 'Pending',
    ready: 'Ready',
    needs_review: 'Needs review',
    failed: 'Failed',
  }[status] || status;
}

async function apiFetch(path, options) {
  const response = await fetch(`${API_BASE}${path}`, options);
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      /* ignore parse errors */
    }
    throw new Error(detail);
  }
  return response.status === 204 ? null : response.json();
}

async function checkHealth() {
  try {
    await apiFetch('/health');
    els.apiStatus.textContent = 'API connected';
    els.apiStatus.classList.add('online');
    return true;
  } catch {
    els.apiStatus.textContent = 'API unavailable — start the local server';
    els.apiStatus.classList.remove('online');
    return false;
  }
}

async function loadSamples() {
  try {
    const samples = await apiFetch('/v1/samples');
    els.sampleList.innerHTML = samples
      .map(
        (sample) => `
        <article class="sample-card" data-sample-id="${sample.id}">
          <div>
            <span class="sample-type">${escapeHtml(sample.document_type)}</span>
            <h4>${escapeHtml(sample.title)}</h4>
            <p>${escapeHtml(sample.description)}</p>
          </div>
          <button class="secondary-button run-sample" type="button" data-sample-id="${sample.id}">
            Run sample
          </button>
        </article>`
      )
      .join('');
  } catch (error) {
    els.sampleList.innerHTML = `<p class="form-error">Could not load samples: ${escapeHtml(error.message)}</p>`;
  }
}

async function loadDocuments() {
  try {
    const documents = await apiFetch('/v1/documents');
    state.documents = documents;
    els.docCount.textContent = String(documents.length);
    if (!documents.length) {
      els.documentList.innerHTML = '<li class="muted">No documents yet. Upload one or run a sample above.</li>';
      return;
    }
    els.documentList.innerHTML = documents
      .map(
        (doc) => `
        <li class="document-item ${doc.id === state.selectedId ? 'active' : ''}" data-doc-id="${doc.id}">
          <div>
            <strong>${escapeHtml(doc.filename)}</strong>
            <span class="doc-meta">${escapeHtml(doc.document_type)} · ${escapeHtml(doc.source)}</span>
          </div>
          <span class="badge badge-${doc.status}">${statusLabel(doc.status)}</span>
        </li>`
      )
      .join('');
  } catch (error) {
    els.documentList.innerHTML = `<li class="form-error">Could not load documents: ${escapeHtml(error.message)}</li>`;
  }
}

function fieldStatusLabel(status) {
  return {
    extracted: 'Extracted',
    needs_review: 'Needs review',
    missing: 'Missing',
    confirmed: 'Confirmed',
    corrected: 'Corrected',
  }[status] || status;
}

function renderFields(document) {
  if (!document.fields.length) {
    els.fieldList.innerHTML = '<p class="muted">No fields are defined for this document type.</p>';
    return;
  }
  els.fieldList.innerHTML = document.fields
    .map((field) => {
      const pct = Math.round((field.confidence || 0) * 100);
      const actionable = field.status === 'needs_review' || field.status === 'missing';
      return `
      <div class="field-card status-${field.status}">
        <div class="field-card-top">
          <strong>${escapeHtml(field.label)}</strong>
          <span class="badge badge-field-${field.status}">${fieldStatusLabel(field.status)}</span>
        </div>
        <p class="field-value">${field.value ? escapeHtml(field.value) : '<span class="muted">No value found</span>'}</p>
        <div class="confidence-bar"><div class="confidence-fill" style="width:${pct}%"></div></div>
        <span class="confidence-label">${pct}% confidence${field.evidence_id ? ` · citation ${field.evidence_id}` : ''}</span>
        ${
          actionable
            ? `<div class="field-actions">
                <button class="tiny-button approve" data-key="${field.key}">Approve</button>
                <button class="tiny-button correct" data-key="${field.key}">Correct…</button>
              </div>
              <div class="correct-form" data-key="${field.key}" hidden>
                <input type="text" placeholder="Enter the correct value" />
                <button class="tiny-button submit-correction" data-key="${field.key}">Save</button>
              </div>`
            : ''
        }
      </div>`;
    })
    .join('');
}

function renderEvidence(document) {
  if (!document.evidence.length) {
    els.evidenceList.innerHTML = '<li class="muted">No supporting evidence was located.</li>';
    return;
  }
  els.evidenceList.innerHTML = document.evidence
    .map(
      (item) => `
      <li>
        <span class="evidence-loc">p.${item.page} · line ${item.line}</span>
        <span class="evidence-snippet">${escapeHtml(item.snippet)}</span>
        <span class="evidence-confidence">${Math.round(item.confidence * 100)}%</span>
      </li>`
    )
    .join('');
}

const OCR_STATUS_LABELS = {
  not_needed: null,
  used: 'OCR recovered text from scanned page(s)',
  unavailable: 'OCR needed but unavailable locally',
  failed: 'OCR was attempted but failed',
};

function renderOcrStatus(document) {
  const label = OCR_STATUS_LABELS[document.ocr_status];
  if (!label) {
    els.ocrStatus.hidden = true;
    return;
  }
  els.ocrStatus.hidden = false;
  els.ocrStatus.className = `ocr-status ocr-${document.ocr_status}`;
  els.ocrStatus.textContent = document.ocr_detail ? `${label}: ${document.ocr_detail}` : label;
}

function auditEventLabel(eventType) {
  return {
    document_processed: 'Processed',
    field_reviewed: 'Reviewed',
  }[eventType] || eventType;
}

async function loadAudit(documentId) {
  try {
    const events = await apiFetch(`/v1/documents/${documentId}/audit`);
    if (!events.length) {
      els.auditList.innerHTML = '<li class="muted">No audit events recorded yet.</li>';
      return;
    }
    els.auditList.innerHTML = events
      .map(
        (event) => `
        <li>
          <span class="audit-time">${new Date(event.created_at).toLocaleString()}</span>
          <span class="audit-type">${escapeHtml(auditEventLabel(event.event_type))}</span>
          <span class="audit-detail">${escapeHtml(event.detail)} (${escapeHtml(event.actor)})</span>
        </li>`
      )
      .join('');
  } catch (error) {
    els.auditList.innerHTML = `<li class="form-error">Could not load audit trail: ${escapeHtml(error.message)}</li>`;
  }
}

function renderDetail(document) {
  state.selectedId = document.id;
  els.detailEmpty.hidden = true;
  els.detailContent.hidden = false;
  els.detailTitle.textContent = document.filename;
  els.status.textContent = `${statusLabel(document.status)} · ${document.filename}`;

  if (document.confidence !== null && document.confidence !== undefined) {
    els.detailConfidence.hidden = false;
    els.detailConfidence.textContent = `${Math.round(document.confidence * 100)}% overall confidence`;
  } else {
    els.detailConfidence.hidden = true;
  }

  els.detailMeta.textContent =
    `${document.document_type} · ${document.source} · ${document.page_count ?? '–'} page(s) · ` +
    `${document.char_count ?? 0} characters`;

  if (document.error) {
    els.detailError.hidden = false;
    els.detailError.textContent = document.error;
  } else {
    els.detailError.hidden = true;
  }

  renderOcrStatus(document);
  renderFields(document);
  renderEvidence(document);
  els.textPreview.textContent = document.text_preview || '(no preview available)';
  renderStages(document.stages);
  els.questionAnswer.hidden = true;
  els.questionAnswer.innerHTML = '';
  loadAudit(document.id);
}

async function askQuestion(event) {
  event.preventDefault();
  if (!state.selectedId || !els.questionInput.value.trim()) return;
  els.questionError.hidden = true;
  els.questionAnswer.hidden = false;
  els.questionAnswer.innerHTML = '<span class="muted">Searching document evidence…</span>';
  try {
    const result = await apiFetch(`/v1/documents/${state.selectedId}/rag`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: els.questionInput.value.trim() }),
    });
    const evidence = result.evidence.length
      ? `<ul class="answer-citations">${result.evidence.map((item) => `
          <li><span>p.${item.page} · lines ${item.line_start}-${item.line_end} · ${escapeHtml(item.method)} match</span>
            ${escapeHtml(item.text)}</li>`).join('')}</ul>`
      : '<p class="muted">No supporting evidence was found.</p>';
    els.questionAnswer.innerHTML = `
      <div class="answer-header">
        <strong>${result.grounded ? 'Grounded answer' : 'Insufficient evidence'}</strong>
        <span>${Math.round(result.confidence * 100)}% match confidence · generated via ${escapeHtml(result.generation_method)}</span>
      </div>
      <p>${escapeHtml(result.answer)}</p>${evidence}`;
  } catch (error) {
    els.questionAnswer.hidden = true;
    els.questionError.hidden = false;
    els.questionError.textContent = error.message;
  }
}

async function selectDocument(id) {
  try {
    const document_ = await apiFetch(`/v1/documents/${id}`);
    renderDetail(document_);
    await loadDocuments();
  } catch (error) {
    els.detailError.hidden = false;
    els.detailError.textContent = error.message;
  }
}

async function runSample(sampleId, button) {
  button.disabled = true;
  button.textContent = 'Processing…';
  try {
    const document_ = await apiFetch(`/v1/samples/${sampleId}/ingest`, { method: 'POST' });
    await loadDocuments();
    renderDetail(document_);
  } catch (error) {
    els.uploadError.hidden = false;
    els.uploadError.textContent = error.message;
  } finally {
    button.disabled = false;
    button.textContent = 'Run sample';
  }
}

async function submitUpload(event) {
  event.preventDefault();
  els.uploadError.hidden = true;
  const file = els.fileInput.files[0];
  if (!file) {
    els.uploadError.hidden = false;
    els.uploadError.textContent = 'Choose a file first.';
    return;
  }
  const formData = new FormData();
  formData.append('file', file);
  formData.append('document_type', els.documentType.value);

  els.uploadButton.disabled = true;
  els.uploadButton.textContent = 'Processing…';
  try {
    const document_ = await apiFetch('/v1/documents', { method: 'POST', body: formData });
    await loadDocuments();
    renderDetail(document_);
    els.uploadForm.reset();
    els.selectedFile.hidden = true;
  } catch (error) {
    els.uploadError.hidden = false;
    els.uploadError.textContent = error.message;
  } finally {
    els.uploadButton.disabled = false;
    els.uploadButton.textContent = 'Upload & process';
  }
}

async function submitReview(fieldKey, decision, correctedValue) {
  if (!state.selectedId) return;
  try {
    const document_ = await apiFetch(`/v1/documents/${state.selectedId}/review`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        field_key: fieldKey,
        decision,
        corrected_value: correctedValue || undefined,
      }),
    });
    renderDetail(document_);
    await loadDocuments();
  } catch (error) {
    els.detailError.hidden = false;
    els.detailError.textContent = error.message;
  }
}

function wireEvents() {
  els.uploadForm.addEventListener('submit', submitUpload);
  els.questionForm.addEventListener('submit', askQuestion);

  els.fileInput.addEventListener('change', () => {
    const file = els.fileInput.files[0];
    if (file) {
      els.selectedFile.hidden = false;
      els.selectedFile.textContent = `${file.name} (${Math.round(file.size / 1024)} KB)`;
    }
  });

  ['dragover', 'dragenter'].forEach((evt) =>
    els.dropzone.addEventListener(evt, (event) => {
      event.preventDefault();
      els.dropzone.classList.add('dragging');
    })
  );
  ['dragleave', 'drop'].forEach((evt) =>
    els.dropzone.addEventListener(evt, (event) => {
      event.preventDefault();
      els.dropzone.classList.remove('dragging');
    })
  );
  els.dropzone.addEventListener('drop', (event) => {
    const file = event.dataTransfer.files[0];
    if (file) {
      els.fileInput.files = event.dataTransfer.files;
      els.selectedFile.hidden = false;
      els.selectedFile.textContent = `${file.name} (${Math.round(file.size / 1024)} KB)`;
    }
  });

  els.sampleList.addEventListener('click', (event) => {
    const button = event.target.closest('.run-sample');
    if (button) runSample(button.dataset.sampleId, button);
  });

  els.documentList.addEventListener('click', (event) => {
    const item = event.target.closest('.document-item');
    if (item) selectDocument(item.dataset.docId);
  });

  els.refreshDocuments.addEventListener('click', () => loadDocuments());

  els.fieldList.addEventListener('click', (event) => {
    const approve = event.target.closest('.approve');
    if (approve) {
      submitReview(approve.dataset.key, 'approve');
      return;
    }
    const correct = event.target.closest('.correct');
    if (correct) {
      const form = els.fieldList.querySelector(`.correct-form[data-key="${correct.dataset.key}"]`);
      if (form) form.hidden = !form.hidden;
      return;
    }
    const submit = event.target.closest('.submit-correction');
    if (submit) {
      const form = els.fieldList.querySelector(`.correct-form[data-key="${submit.dataset.key}"]`);
      const input = form?.querySelector('input');
      if (input && input.value.trim()) {
        submitReview(submit.dataset.key, 'correct', input.value.trim());
      }
    }
  });

  els.runEvaluation.addEventListener('click', runEvaluation);
}

async function runEvaluation() {
  els.evaluationError.hidden = true;
  els.evaluationResult.hidden = false;
  els.evaluationResult.innerHTML = '<span class="muted">Running local evaluation…</span>';
  els.runEvaluation.disabled = true;
  try {
    const report = await apiFetch('/v1/evaluation');
    const extractionPct = Math.round(report.extraction_accuracy * 100);
    const retrievalPct = Math.round(report.retrieval_hit_rate * 100);
    const failedExtraction = report.extraction_cases.filter((c) => !c.correct);
    const failedRetrieval = report.retrieval_cases.filter((c) => !c.found);
    els.evaluationResult.innerHTML = `
      <div class="evaluation-metrics">
        <span class="evaluation-metric">Extraction accuracy: <strong>${extractionPct}%</strong>
          (${report.extraction_cases.length} case(s))</span>
        <span class="evaluation-metric">Retrieval hit rate: <strong>${retrievalPct}%</strong>
          (${report.retrieval_cases.length} case(s))</span>
      </div>
      ${
        failedExtraction.length || failedRetrieval.length
          ? `<p class="form-error">${failedExtraction.length + failedRetrieval.length} case(s) did not match the expected result.</p>`
          : '<p class="muted">All golden cases matched.</p>'
      }`;
  } catch (error) {
    els.evaluationResult.hidden = true;
    els.evaluationError.hidden = false;
    els.evaluationError.textContent = error.message;
  } finally {
    els.runEvaluation.disabled = false;
  }
}

async function init() {
  renderStages(null);
  wireEvents();
  await checkHealth();
  await Promise.all([loadSamples(), loadDocuments()]);
}

init();
