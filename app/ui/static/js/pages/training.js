/**
 * Training Mode — Expert grades cards manually, AI grades independently,
 * system shows comparison and learns from deltas.
 */
import { api, agent, isCloudMode } from '../api.js';
import { showToast, escapeHtml } from '../components.js';

let _currentCard = null;
let _scanState = { sessionId: null, frontImagePath: null, backImagePath: null, pipelineResult: null, cardRecordId: null };

function _resetScanState() {
    _scanState = { sessionId: null, frontImagePath: null, backImagePath: null, pipelineResult: null, cardRecordId: null };
}

export async function init(container) {
    container.innerHTML = `
        <div class="px-4 py-3">
            <div class="d-flex justify-content-between align-items-center mb-3">
                <h5 class="mb-0"><i class="bi bi-mortarboard me-2"></i>Training Mode</h5>
                <a href="#/calibration" class="btn btn-sm btn-outline-primary">
                    <i class="bi bi-sliders me-1"></i>Calibration Dashboard
                </a>
            </div>

            <div class="card mb-3">
                <div class="card-body" id="training-body">
                    <div id="step-select"></div>
                </div>
            </div>

            <!-- Recent training grades -->
            <div class="card">
                <div class="card-header d-flex justify-content-between align-items-center">
                    <span><i class="bi bi-list-task me-2"></i>Recent Training Grades</span>
                    <span class="badge bg-primary" id="training-count">0</span>
                </div>
                <div class="card-body p-0">
                    <div class="table-responsive">
                        <table class="table table-hover table-sm mb-0">
                            <thead><tr><th>Card</th><th>Expert</th><th>AI</th><th>Delta</th><th>Operator</th><th>Date</th><th></th></tr></thead>
                            <tbody id="training-tbody"></tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>`;

    await showSelectStep();
    await loadRecentGrades();
}

export function destroy() {
    _currentCard = null;
    _resetScanState();
}

// ---------------------------------------------------------------------------
// Step 1: Choose mode — Select Existing Card or Scan Training Card
// ---------------------------------------------------------------------------

async function showSelectStep() {
    const body = document.getElementById('step-select') || document.getElementById('training-body');

    body.innerHTML = `
        <h6 class="mb-3">Step 1: Choose how to grade</h6>
        <div class="row g-3 mb-3">
            <div class="col-md-6">
                <button class="btn btn-outline-primary w-100 py-3" id="btn-mode-select">
                    <i class="bi bi-list-ul d-block" style="font-size:1.5rem"></i>
                    Select Existing Card
                </button>
            </div>
            <div class="col-md-6">
                <button class="btn btn-outline-success w-100 py-3" id="btn-mode-scan">
                    <i class="bi bi-upc-scan d-block" style="font-size:1.5rem"></i>
                    Scan Training Card
                </button>
            </div>
        </div>
        <div id="mode-content"></div>`;

    document.getElementById('btn-mode-select').addEventListener('click', renderCardSelectDropdown);
    document.getElementById('btn-mode-scan').addEventListener('click', scanStepStart);
}

async function renderCardSelectDropdown() {
    const content = document.getElementById('mode-content');
    if (!content) return;

    try {
        const res = await api.get('/queue/list?limit=100');
        const cards = res.cards || [];

        content.innerHTML = `
            <div class="row g-2">
                <div class="col-md-8">
                    <select class="form-select" id="card-select">
                        <option value="">Choose a card...</option>
                        ${cards.filter(c => c.serial_number).map(c =>
                            `<option value="${c.id}" data-name="${escapeHtml(c.card_name || '')}" data-set="${escapeHtml(c.set_name || '')}" data-serial="${escapeHtml(c.serial_number || '')}" data-grade="${c.final_grade || ''}">${escapeHtml(c.serial_number)} — ${escapeHtml(c.card_name || 'Unknown')} (${escapeHtml(c.set_name || '')})</option>`
                        ).join('')}
                    </select>
                </div>
                <div class="col-md-4">
                    <button class="btn btn-primary w-100" id="btn-select-card" disabled>
                        <i class="bi bi-arrow-right me-1"></i>Grade This Card
                    </button>
                </div>
            </div>`;

        const select = document.getElementById('card-select');
        const btn = document.getElementById('btn-select-card');

        select.addEventListener('change', () => { btn.disabled = !select.value; });
        btn.addEventListener('click', () => {
            const opt = select.selectedOptions[0];
            _currentCard = {
                id: select.value,
                card_name: opt.dataset.name,
                set_name: opt.dataset.set,
                serial_number: opt.dataset.serial,
                ai_grade: opt.dataset.grade,
            };
            showExpertGradeStep();
        });
    } catch (e) {
        content.innerHTML = `<div class="alert alert-warning">Could not load cards: ${escapeHtml(e.message)}</div>`;
    }
}

// ---------------------------------------------------------------------------
// Scan Training Flow — T1: Scan Front + Process
// ---------------------------------------------------------------------------

async function scanStepStart() {
    _resetScanState();
    const body = document.getElementById('training-body');

    body.innerHTML = `
        <div class="text-center py-4" id="scan-progress">
            <div class="spinner-border text-success mb-3" style="width:3rem;height:3rem"></div>
            <h6 id="scan-status-text">Starting scan session...</h6>
            <p class="text-muted small" id="scan-status-detail">Please wait</p>
            <div class="progress mt-3" style="height:6px;max-width:400px;margin:0 auto">
                <div class="progress-bar bg-success" id="scan-progress-bar" style="width:5%"></div>
            </div>
        </div>`;

    const statusText = document.getElementById('scan-status-text');
    const statusDetail = document.getElementById('scan-status-detail');
    const progressBar = document.getElementById('scan-progress-bar');

    function setProgress(pct, text, detail) {
        if (progressBar) progressBar.style.width = pct + '%';
        if (statusText) statusText.textContent = text;
        if (statusDetail) statusDetail.textContent = detail || '';
    }

    try {
        // 1. Create scan session
        setProgress(10, 'Creating scan session...', '');
        const op = JSON.parse(localStorage.getItem('rkt-operator') || '{}');
        const session = await api.post('/scan/start?preset=detailed&operator=' + encodeURIComponent(op.name || 'default'));
        _scanState.sessionId = session.session_id;

        // 2. Acquire front scan
        setProgress(20, 'Scanning front side at 600 DPI...', 'This may take 2-3 minutes');
        const acqRes = await api.request('POST', `/scan/${_scanState.sessionId}/acquire?side=front&dpi=600`, null, {
            signal: AbortSignal.timeout(300000)
        });
        _scanState.frontImagePath = acqRes.path;
        setProgress(60, 'Scan complete. Processing card...', 'Running vision pipeline, OCR, identification, grading...');

        // 3. Process pipeline
        const pipeline = await api.request('POST', `/scan/${_scanState.sessionId}/process`, null, {
            signal: AbortSignal.timeout(120000)
        });
        _scanState.pipelineResult = pipeline;
        _scanState.cardRecordId = pipeline.card_id;

        // Use the processed image (card cropped/corrected) instead of raw scan
        if (pipeline.front_image_path) {
            _scanState.frontImagePath = pipeline.front_image_path.replace(/^\//, '');
        } else if (pipeline.card_id) {
            try {
                const cardData = await api.get(`/queue/list?limit=1`);
                const imgPath = cardData.cards?.[0]?.front_image_path;
                if (imgPath) {
                    _scanState.frontImagePath = imgPath.replace(/^\//, '');
                }
            } catch {}
        }

        setProgress(100, 'Done!', '');
        scanStepShowFrontResults();

    } catch (e) {
        body.innerHTML = `
            <div class="alert alert-danger">
                <i class="bi bi-exclamation-triangle me-2"></i>
                <strong>Scan failed:</strong> ${escapeHtml(e.message || 'Unknown error')}
            </div>
            <button class="btn btn-outline-primary" id="btn-scan-retry">
                <i class="bi bi-arrow-counterclockwise me-1"></i>Try Again
            </button>
            <button class="btn btn-outline-secondary ms-2" id="btn-scan-back">
                <i class="bi bi-arrow-left me-1"></i>Back
            </button>`;

        document.getElementById('btn-scan-retry')?.addEventListener('click', scanStepStart);
        document.getElementById('btn-scan-back')?.addEventListener('click', () => {
            body.innerHTML = '<div id="step-select"></div>';
            showSelectStep();
        });
    }
}

// ---------------------------------------------------------------------------
// Scan Training Flow — T2: Show Front AI Results
// ---------------------------------------------------------------------------

function scanStepShowFrontResults() {
    const body = document.getElementById('training-body');
    const r = _scanState.pipelineResult;
    if (!r) return;

    const grading = r.steps?.find(s => s.step === 'grading') || {};
    const cardId = r.steps?.find(s => s.step === 'card_identification') || {};
    const sub = grading.sub_scores || {};

    function scoreBadge(val) {
        if (val == null) return '<span class="text-muted">—</span>';
        const color = val >= 9.5 ? 'success' : val >= 8 ? 'primary' : val >= 6 ? 'warning' : 'danger';
        return `<span class="badge bg-${color}">${val}</span>`;
    }

    body.innerHTML = `
        <div class="d-flex justify-content-between align-items-center mb-3">
            <h6 class="mb-0"><i class="bi bi-check-circle text-success me-2"></i>Front Scan Complete</h6>
            <button class="btn btn-sm btn-outline-secondary" id="btn-start-over">
                <i class="bi bi-arrow-left me-1"></i>Start Over
            </button>
        </div>

        <div class="row g-3 mb-3">
            <div class="col-md-4">
                <div class="card bg-dark text-center p-2">
                    ${_scanState.frontImagePath
                        ? `<img src="/${escapeHtml(_scanState.frontImagePath)}" class="img-fluid rounded" style="max-height:300px;object-fit:contain" alt="Front scan">`
                        : '<div class="text-muted py-5">No image</div>'}
                </div>
            </div>
            <div class="col-md-8">
                <div class="card h-100">
                    <div class="card-body">
                        <p class="mb-2"><strong>${escapeHtml(cardId.card_name || 'Unknown Card')}</strong></p>
                        <p class="text-muted small mb-3">${escapeHtml(cardId.set_name || '')} ${cardId.serial ? '| ' + escapeHtml(cardId.serial) : ''}</p>

                        <h5 class="mb-3">AI Grade: ${scoreBadge(grading.final_grade)}</h5>

                        <div class="row g-2 mb-3">
                            <div class="col-3 text-center">
                                <div class="small text-muted">Centering</div>
                                ${scoreBadge(sub.centering)}
                            </div>
                            <div class="col-3 text-center">
                                <div class="small text-muted">Corners</div>
                                ${scoreBadge(sub.corners)}
                            </div>
                            <div class="col-3 text-center">
                                <div class="small text-muted">Edges</div>
                                ${scoreBadge(sub.edges)}
                            </div>
                            <div class="col-3 text-center">
                                <div class="small text-muted">Surface</div>
                                ${scoreBadge(sub.surface)}
                            </div>
                        </div>

                        <p class="small text-muted mb-0">Defects: ${grading.defect_count ?? 0} | Confidence: ${grading.grading_confidence ? grading.grading_confidence.toFixed(0) + '%' : '—'}</p>
                    </div>
                </div>
            </div>
        </div>

        <div class="d-flex gap-2">
            <button class="btn btn-success" id="btn-scan-back-side">
                <i class="bi bi-arrow-repeat me-1"></i>Scan Back
            </button>
            <button class="btn btn-outline-primary" id="btn-skip-back">
                <i class="bi bi-arrow-right me-1"></i>Skip Back — Enter Expert Grades
            </button>
        </div>`;

    document.getElementById('btn-start-over')?.addEventListener('click', () => {
        _resetScanState();
        body.innerHTML = '<div id="step-select"></div>';
        showSelectStep();
    });
    document.getElementById('btn-scan-back-side')?.addEventListener('click', scanStepAcquireBack);
    document.getElementById('btn-skip-back')?.addEventListener('click', scanStepExpertGrade);
}

// ---------------------------------------------------------------------------
// Scan Training Flow — T3: Scan Back + Re-process
// ---------------------------------------------------------------------------

async function scanStepAcquireBack() {
    const btnArea = document.querySelector('.d-flex.gap-2');
    if (btnArea) {
        btnArea.innerHTML = `
            <div class="d-flex align-items-center">
                <div class="spinner-border spinner-border-sm text-success me-2"></div>
                <span>Scanning back side at 600 DPI...</span>
            </div>`;
    }

    try {
        // Acquire back
        const acqRes = await api.request('POST', `/scan/${_scanState.sessionId}/acquire?side=back&dpi=600`, null, {
            signal: AbortSignal.timeout(300000)
        });
        _scanState.backImagePath = acqRes.path;

        if (btnArea) {
            btnArea.innerHTML = `
                <div class="d-flex align-items-center">
                    <div class="spinner-border spinner-border-sm text-primary me-2"></div>
                    <span>Re-processing with both sides...</span>
                </div>`;
        }

        // Re-process with both sides
        const pipeline = await api.request('POST', `/scan/${_scanState.sessionId}/process`, null, {
            signal: AbortSignal.timeout(120000)
        });
        _scanState.pipelineResult = pipeline;
        _scanState.cardRecordId = pipeline.card_id;

        scanStepShowBackResults();

    } catch (e) {
        showToast('Back scan failed: ' + (e.message || 'Unknown error'), 'danger');
        if (btnArea) {
            btnArea.innerHTML = `
                <div class="d-flex gap-2">
                    <button class="btn btn-success" id="btn-retry-back">
                        <i class="bi bi-arrow-repeat me-1"></i>Retry Back Scan
                    </button>
                    <button class="btn btn-outline-primary" id="btn-skip-back2">
                        <i class="bi bi-arrow-right me-1"></i>Skip — Enter Expert Grades
                    </button>
                </div>`;
            document.getElementById('btn-retry-back')?.addEventListener('click', scanStepAcquireBack);
            document.getElementById('btn-skip-back2')?.addEventListener('click', scanStepExpertGrade);
        }
    }
}

// ---------------------------------------------------------------------------
// Scan Training Flow — T3b: Show Back Results
// ---------------------------------------------------------------------------

function scanStepShowBackResults() {
    const body = document.getElementById('training-body');
    const r = _scanState.pipelineResult;
    if (!r) return;

    const grading = r.steps?.find(s => s.step === 'grading') || {};
    const cardId = r.steps?.find(s => s.step === 'card_identification') || {};
    const sub = grading.sub_scores || {};

    function scoreBadge(val) {
        if (val == null) return '<span class="text-muted">—</span>';
        const color = val >= 9.5 ? 'success' : val >= 8 ? 'primary' : val >= 6 ? 'warning' : 'danger';
        return `<span class="badge bg-${color}">${val}</span>`;
    }

    body.innerHTML = `
        <div class="d-flex justify-content-between align-items-center mb-3">
            <h6 class="mb-0"><i class="bi bi-check-circle text-success me-2"></i>Front &amp; Back Scan Complete</h6>
            <button class="btn btn-sm btn-outline-secondary" id="btn-start-over2">
                <i class="bi bi-arrow-left me-1"></i>Start Over
            </button>
        </div>

        <div class="row g-3 mb-3">
            <div class="col-md-3">
                <div class="card bg-dark text-center p-2">
                    <div class="small text-white-50 mb-1">Front</div>
                    ${_scanState.frontImagePath
                        ? `<img src="/${escapeHtml(_scanState.frontImagePath)}" class="img-fluid rounded" style="max-height:200px;object-fit:contain" alt="Front">`
                        : '<div class="text-muted py-3">—</div>'}
                </div>
            </div>
            <div class="col-md-3">
                <div class="card bg-dark text-center p-2">
                    <div class="small text-white-50 mb-1">Back</div>
                    ${_scanState.backImagePath
                        ? `<img src="/${escapeHtml(_scanState.backImagePath)}" class="img-fluid rounded" style="max-height:200px;object-fit:contain" alt="Back">`
                        : '<div class="text-muted py-3">—</div>'}
                </div>
            </div>
            <div class="col-md-6">
                <div class="card h-100">
                    <div class="card-body">
                        <p class="mb-1"><strong>${escapeHtml(cardId.card_name || 'Unknown Card')}</strong></p>
                        <p class="text-muted small mb-2">${escapeHtml(cardId.set_name || '')} ${cardId.serial ? '| ' + escapeHtml(cardId.serial) : ''}</p>

                        <h5 class="mb-3">AI Grade: ${scoreBadge(grading.final_grade)}</h5>

                        <div class="row g-2 mb-2">
                            <div class="col-3 text-center">
                                <div class="small text-muted">Centering</div>
                                ${scoreBadge(sub.centering)}
                            </div>
                            <div class="col-3 text-center">
                                <div class="small text-muted">Corners</div>
                                ${scoreBadge(sub.corners)}
                            </div>
                            <div class="col-3 text-center">
                                <div class="small text-muted">Edges</div>
                                ${scoreBadge(sub.edges)}
                            </div>
                            <div class="col-3 text-center">
                                <div class="small text-muted">Surface</div>
                                ${scoreBadge(sub.surface)}
                            </div>
                        </div>

                        <p class="small text-muted mb-0">Defects: ${grading.defect_count ?? 0} | Confidence: ${grading.grading_confidence ? grading.grading_confidence.toFixed(0) + '%' : '—'}</p>
                    </div>
                </div>
            </div>
        </div>

        <button class="btn btn-primary" id="btn-enter-expert">
            <i class="bi bi-pencil-square me-1"></i>Enter Expert Grades
        </button>`;

    document.getElementById('btn-start-over2')?.addEventListener('click', () => {
        _resetScanState();
        body.innerHTML = '<div id="step-select"></div>';
        showSelectStep();
    });
    document.getElementById('btn-enter-expert')?.addEventListener('click', scanStepExpertGrade);
}

// ---------------------------------------------------------------------------
// Scan Training Flow — T4: Bridge to Expert Grade Form
// ---------------------------------------------------------------------------

function scanStepExpertGrade() {
    const r = _scanState.pipelineResult;
    const cardId = r?.steps?.find(s => s.step === 'card_identification') || {};
    const grading = r?.steps?.find(s => s.step === 'grading') || {};

    _currentCard = {
        id: _scanState.cardRecordId || r?.card_id,
        card_name: cardId.card_name || 'Unknown',
        set_name: cardId.set_name || '',
        serial_number: cardId.serial || '',
        ai_grade: grading.final_grade || '',
    };

    showExpertGradeStep();
}

// ---------------------------------------------------------------------------
// Step 2: Expert Grade Form (shared by both flows)
// ---------------------------------------------------------------------------

function showExpertGradeStep() {
    const body = document.getElementById('training-body');
    const c = _currentCard;

    body.innerHTML = `
        <div class="d-flex justify-content-between align-items-center mb-3">
            <h6 class="mb-0">Step 2: Enter your expert grades</h6>
            <div>
                <span class="badge bg-secondary me-2">${escapeHtml(c.serial_number)}</span>
                <button class="btn btn-sm btn-outline-secondary" id="btn-back-start">
                    <i class="bi bi-arrow-left me-1"></i>Start Over
                </button>
            </div>
        </div>
        <p class="text-muted small mb-3"><strong>${escapeHtml(c.card_name)}</strong> — ${escapeHtml(c.set_name)}</p>

        <div class="row g-3">
            <div class="col-md-3">
                <label class="form-label small">Centering</label>
                <input type="number" class="form-control" id="exp-centering" min="1" max="10" step="0.5" value="8.0">
            </div>
            <div class="col-md-3">
                <label class="form-label small">Corners</label>
                <input type="number" class="form-control" id="exp-corners" min="1" max="10" step="0.5" value="8.0">
            </div>
            <div class="col-md-3">
                <label class="form-label small">Edges</label>
                <input type="number" class="form-control" id="exp-edges" min="1" max="10" step="0.5" value="8.0">
            </div>
            <div class="col-md-3">
                <label class="form-label small">Surface</label>
                <input type="number" class="form-control" id="exp-surface" min="1" max="10" step="0.5" value="8.0">
            </div>
        </div>

        <div class="row g-3 mt-1">
            <div class="col-md-3">
                <label class="form-label small">Final Grade</label>
                <input type="number" class="form-control fw-bold" id="exp-final" min="1" max="10" step="0.5" value="8.0">
                <small class="text-muted" id="computed-grade">Weighted: —</small>
            </div>
            <div class="col-md-5">
                <label class="form-label small">Defect Notes</label>
                <textarea class="form-control" id="exp-notes" rows="2" placeholder="Optional: describe defects you observed"></textarea>
            </div>
            <div class="col-md-2">
                <label class="form-label small">Expertise</label>
                <select class="form-select" id="exp-level">
                    <option value="junior">Junior</option>
                    <option value="standard" selected>Standard</option>
                    <option value="senior">Senior</option>
                </select>
            </div>
            <div class="col-md-2 d-flex align-items-end">
                <button class="btn btn-success w-100" id="btn-submit-grade">
                    <i class="bi bi-check-lg me-1"></i>Submit
                </button>
            </div>
        </div>
        <div id="submit-status" class="mt-3"></div>`;

    // "Start Over" button
    document.getElementById('btn-back-start')?.addEventListener('click', () => {
        _currentCard = null;
        _resetScanState();
        body.innerHTML = '<div id="step-select"></div>';
        showSelectStep();
    });

    // Auto-compute weighted grade
    const inputs = ['exp-centering', 'exp-corners', 'exp-edges', 'exp-surface'];
    inputs.forEach(id => {
        document.getElementById(id)?.addEventListener('input', () => {
            const c = parseFloat(document.getElementById('exp-centering').value) || 0;
            const co = parseFloat(document.getElementById('exp-corners').value) || 0;
            const e = parseFloat(document.getElementById('exp-edges').value) || 0;
            const s = parseFloat(document.getElementById('exp-surface').value) || 0;
            const weighted = (c * 0.10 + co * 0.30 + e * 0.30 + s * 0.30).toFixed(1);
            document.getElementById('computed-grade').textContent = `Weighted: ${weighted}`;
        });
    });

    document.getElementById('btn-submit-grade')?.addEventListener('click', async () => {
        const btn = document.getElementById('btn-submit-grade');
        const statusDiv = document.getElementById('submit-status');
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Submitting...';

        try {
            const op = JSON.parse(localStorage.getItem('rkt-operator') || '{}');
            const result = await api.post('/training/submit', {
                card_record_id: _currentCard.id,
                centering: parseFloat(document.getElementById('exp-centering').value),
                corners: parseFloat(document.getElementById('exp-corners').value),
                edges: parseFloat(document.getElementById('exp-edges').value),
                surface: parseFloat(document.getElementById('exp-surface').value),
                final_grade: parseFloat(document.getElementById('exp-final').value),
                defect_notes: document.getElementById('exp-notes').value,
                operator: op.name || 'default',
                expertise_level: document.getElementById('exp-level').value,
            });
            showComparisonStep(result);
            await loadRecentGrades();
        } catch (e) {
            statusDiv.innerHTML = `<div class="alert alert-danger py-2 small">${escapeHtml(e.message)}</div>`;
            btn.disabled = false;
            btn.innerHTML = '<i class="bi bi-check-lg me-1"></i>Submit';
        }
    });
}

// ---------------------------------------------------------------------------
// Step 3: Comparison (shared by both flows)
// ---------------------------------------------------------------------------

function showComparisonStep(data) {
    const body = document.getElementById('training-body');
    const expert = data.expert;
    const ai = data.ai;
    const deltas = data.deltas;
    const hasAi = ai !== null;

    function deltaCell(val) {
        if (val === null || val === undefined) return '<td class="text-muted">—</td>';
        const abs = Math.abs(val);
        const color = abs <= 0.5 ? 'text-success' : abs <= 1.0 ? 'text-warning' : 'text-danger';
        const sign = val > 0 ? '+' : '';
        return `<td class="${color} fw-bold">${sign}${val.toFixed(1)}</td>`;
    }

    body.innerHTML = `
        <div class="d-flex justify-content-between align-items-center mb-3">
            <h6 class="mb-0">Step 3: Comparison</h6>
            <div>
                ${hasAi && data.grade_match
                    ? '<span class="badge bg-success"><i class="bi bi-check-circle me-1"></i>Grade Match</span>'
                    : hasAi
                        ? '<span class="badge bg-warning text-dark"><i class="bi bi-exclamation-triangle me-1"></i>Grade Mismatch</span>'
                        : '<span class="badge bg-secondary">AI grade pending</span>'}
            </div>
        </div>

        <div class="table-responsive mb-3">
            <table class="table table-sm mb-0">
                <thead><tr><th>Sub-Grade</th><th>Expert</th><th>AI</th><th>Delta</th></tr></thead>
                <tbody>
                    <tr><td>Centering</td><td>${expert.centering}</td><td>${hasAi ? ai.centering : '—'}</td>${deltaCell(deltas?.centering)}</tr>
                    <tr><td>Corners</td><td>${expert.corners}</td><td>${hasAi ? ai.corners : '—'}</td>${deltaCell(deltas?.corners)}</tr>
                    <tr><td>Edges</td><td>${expert.edges}</td><td>${hasAi ? ai.edges : '—'}</td>${deltaCell(deltas?.edges)}</tr>
                    <tr><td>Surface</td><td>${expert.surface}</td><td>${hasAi ? ai.surface : '—'}</td>${deltaCell(deltas?.surface)}</tr>
                    <tr class="table-active fw-bold"><td>Final Grade</td><td>${expert.final}</td><td>${hasAi ? ai.final : '—'}</td>${deltaCell(deltas?.final)}</tr>
                </tbody>
            </table>
        </div>

        ${expert.defect_notes ? `
            <div class="mb-3">
                <strong class="small">Expert Notes:</strong>
                <p class="small text-muted mb-0">${escapeHtml(expert.defect_notes)}</p>
            </div>` : ''}

        ${data.ai_defects?.length ? `
            <div class="mb-3">
                <strong class="small">AI Detected Defects (${data.ai_defects.length}):</strong>
                <div class="small">
                    ${data.ai_defects.map(d => `
                        <span class="badge bg-${d.severity === 'critical' ? 'danger' : d.severity === 'major' ? 'warning text-dark' : 'secondary'} me-1 mb-1">${escapeHtml(d.category)}: ${escapeHtml(d.defect_type)} (${escapeHtml(d.severity)})</span>
                    `).join('')}
                </div>
            </div>` : ''}

        <button class="btn btn-primary" id="btn-grade-another">
            <i class="bi bi-plus me-1"></i>Grade Another Card
        </button>`;

    document.getElementById('btn-grade-another')?.addEventListener('click', () => {
        _currentCard = null;
        _resetScanState();
        body.innerHTML = '<div id="step-select"></div>';
        showSelectStep();
    });
}

// ---------------------------------------------------------------------------
// Recent Training Grades List
// ---------------------------------------------------------------------------

async function loadRecentGrades() {
    const tbody = document.getElementById('training-tbody');
    const badge = document.getElementById('training-count');
    if (!tbody) return;

    try {
        const res = await api.get('/training/list?per_page=15');
        if (badge) badge.textContent = res.total || 0;

        if (!res.items?.length) {
            tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted py-3 small">No training grades yet</td></tr>';
            return;
        }

        tbody.innerHTML = res.items.map(item => {
            const delta = item.delta_final;
            const deltaClass = delta === null ? '' : Math.abs(delta) <= 0.5 ? 'text-success' : Math.abs(delta) <= 1.0 ? 'text-warning' : 'text-danger';
            return `
                <tr>
                    <td class="small">${escapeHtml(item.card_name || '—')}</td>
                    <td><span class="badge bg-primary">${item.expert_final}</span></td>
                    <td>${item.ai_final !== null ? `<span class="badge bg-secondary">${item.ai_final}</span>` : '<span class="text-muted small">pending</span>'}</td>
                    <td class="${deltaClass} fw-bold small">${delta !== null ? (delta > 0 ? '+' : '') + delta.toFixed(1) : '—'}</td>
                    <td class="small text-muted">${escapeHtml(item.operator_name)}</td>
                    <td class="small text-muted">${item.created_at?.split('T')[0] || ''}</td>
                    <td><button class="btn btn-sm btn-outline-danger border-0 py-0 px-1 btn-delete-training" data-id="${escapeHtml(item.id)}" title="Delete"><i class="bi bi-trash"></i></button></td>
                </tr>`;
        }).join('');

        // Attach delete handlers
        tbody.querySelectorAll('.btn-delete-training').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const id = e.currentTarget.dataset.id;
                if (!confirm('Delete this training entry?')) return;
                try {
                    await api.delete(`/training/${id}`);
                    showToast('Training entry deleted', 'success');
                    await loadRecentGrades();
                } catch (err) {
                    showToast('Failed to delete: ' + (err.message || 'Unknown error'), 'danger');
                }
            });
        });
    } catch {
        tbody.innerHTML = '<tr><td colspan="7" class="text-muted small">Error loading</td></tr>';
    }
}
