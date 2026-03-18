/**
 * New Scan — Full workflow page.
 *
 * Flow: Scan/Upload Front → (optional) Scan/Upload Back → Process → Report
 * Supports: single-card, multi-card, dual-side, quick-scan→high-res
 */
import { api } from '../api.js';
import { ImageViewer } from '../image-viewer.js';
import { createGradeBadge, createAuthBadge, createStatusBadge, showToast } from '../components.js';

let viewer = null;
let state = {
    sessionId: null,
    frontImageId: null,
    frontImagePath: null,
    backImageId: null,
    backImagePath: null,
    cardId: null,
    pipelineResult: null,
    multiMode: false,
    multiResult: null,
    selectedCardIndex: 0,
    phase: 'scan', // scan | processing | report
    currentSide: 'front', // which side is being scanned
};

function resetState() {
    return {
        sessionId: null, frontImageId: null, frontImagePath: null,
        backImageId: null, backImagePath: null, cardId: null,
        pipelineResult: null, multiMode: false, multiResult: null,
        selectedCardIndex: 0, phase: 'scan', currentSide: 'front',
    };
}

export async function init(container) {
    state = resetState();
    renderScanPhase(container);
}

export function destroy() {
    if (viewer) { viewer.destroy(); viewer = null; }
}

// ─── Phase 1: Scan / Upload ──────────────────────────────────────────
function renderScanPhase(container) {
    const hasFront = !!state.frontImagePath;
    const hasBack = !!state.backImagePath;

    container.innerHTML = `
        <div class="px-4 py-3">
            <div class="d-flex align-items-center mb-3">
                <h5 class="mb-0 me-3">New Card Scan</h5>
                <span class="badge bg-secondary" id="scanner-status">Checking scanner...</span>
            </div>
            <div class="row">
                <div class="col-lg-8 mb-4">
                    <!-- Front Image Card -->
                    <div class="card mb-3">
                        <div class="card-header d-flex justify-content-between align-items-center">
                            <h6 class="mb-0"><i class="bi bi-front me-2"></i>Front Side ${hasFront ? '<i class="bi bi-check-circle-fill text-success ms-1"></i>' : ''}</h6>
                            <div class="d-flex gap-2">
                                <label class="btn btn-sm btn-outline-secondary mb-0" for="file-upload-front">
                                    <i class="bi bi-upload me-1"></i>Upload
                                </label>
                                <input type="file" id="file-upload-front" accept="image/*" class="d-none">
                                <button class="btn btn-sm btn-primary" id="btn-scan-front" disabled>
                                    <i class="bi bi-upc-scan me-1"></i>Scan Front
                                </button>
                            </div>
                        </div>
                        <div class="card-body">
                            <div id="scan-preview-front" style="min-height:${hasFront ? '200' : '350'}px;background:#1a1a2e;border-radius:8px;display:flex;align-items:center;justify-content:center;color:#666;position:relative;">
                                ${hasFront ? '' : `
                                <div class="text-center" id="scan-placeholder-front">
                                    <i class="bi bi-image" style="font-size:3rem;display:block;margin-bottom:8px;"></i>
                                    <span>Upload or scan the front of the card</span>
                                    <div class="mt-2"><small class="text-muted">Supported: PNG, JPG, BMP, TIFF</small></div>
                                </div>`}
                            </div>
                        </div>
                    </div>

                    <!-- Back Image Card -->
                    <div class="card ${hasFront ? '' : 'opacity-50'}">
                        <div class="card-header d-flex justify-content-between align-items-center">
                            <h6 class="mb-0"><i class="bi bi-back me-2"></i>Back Side ${hasBack ? '<i class="bi bi-check-circle-fill text-success ms-1"></i>' : '<span class="badge bg-secondary ms-1">Optional</span>'}</h6>
                            <div class="d-flex gap-2">
                                <label class="btn btn-sm btn-outline-secondary mb-0 ${hasFront ? '' : 'disabled'}" for="file-upload-back">
                                    <i class="bi bi-upload me-1"></i>Upload
                                </label>
                                <input type="file" id="file-upload-back" accept="image/*" class="d-none" ${hasFront ? '' : 'disabled'}>
                                <button class="btn btn-sm btn-outline-primary" id="btn-scan-back" disabled>
                                    <i class="bi bi-upc-scan me-1"></i>Scan Back
                                </button>
                            </div>
                        </div>
                        <div class="card-body">
                            <div id="scan-preview-back" style="min-height:120px;background:#1a1a2e;border-radius:8px;display:flex;align-items:center;justify-content:center;color:#666;">
                                ${hasBack ? '' : '<span class="small text-muted">Back side scan helps with card identification accuracy</span>'}
                            </div>
                        </div>
                    </div>
                </div>
                <div class="col-lg-4 mb-4">
                    <div class="card mb-3">
                        <div class="card-header"><h6 class="mb-0"><i class="bi bi-sliders me-2"></i>Scan Settings</h6></div>
                        <div class="card-body">
                            <div class="mb-3">
                                <label class="form-label fw-semibold">Scan Preset</label>
                                <select class="form-select" id="scan-preset">
                                    <option value="detailed" selected>Detailed (600 DPI)</option>
                                    <option value="fast_production">Fast Production (300 DPI)</option>
                                    <option value="authenticity">Authenticity (1200 DPI)</option>
                                </select>
                            </div>
                            <div class="mb-3">
                                <label class="form-label fw-semibold">Operator</label>
                                <input type="text" class="form-control" id="scan-operator" value="default" placeholder="Operator name">
                            </div>
                            <div class="form-check form-switch mb-3">
                                <input class="form-check-input" type="checkbox" id="multi-card-toggle" ${state.multiMode ? 'checked' : ''}>
                                <label class="form-check-label" for="multi-card-toggle">
                                    <i class="bi bi-grid-3x2 me-1"></i>Force Multi-Card Mode
                                </label>
                                <div class="form-text">Multiple cards are auto-detected. Enable to force multi-card processing.</div>
                            </div>
                            <hr>
                            <div class="d-grid gap-2">
                                <button class="btn btn-success btn-lg" id="btn-process" ${hasFront ? '' : 'disabled'}>
                                    <i class="bi bi-play-circle me-2"></i>Process Card(s)
                                </button>
                                <button class="btn btn-outline-info" id="btn-smart-scan" disabled>
                                    <i class="bi bi-lightning me-1"></i>Smart Scan (Quick + Detailed)
                                </button>
                            </div>
                            <small class="text-muted d-block mt-2 text-center">Smart Scan: quick 150 DPI preview, then full 600 DPI scan</small>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `;

    // Restore front preview if returning to this phase
    if (hasFront) showImagePreview('front', '/' + state.frontImagePath.replace(/\\/g, '/'));
    if (hasBack) showImagePreview('back', '/' + state.backImagePath.replace(/\\/g, '/'));

    // Check scanner
    checkScanner();

    // File upload handlers
    document.getElementById('file-upload-front').addEventListener('change', (e) => handleFileUpload(e, 'front', container));
    document.getElementById('file-upload-back').addEventListener('change', (e) => handleFileUpload(e, 'back', container));

    // Scan buttons
    document.getElementById('btn-scan-front').addEventListener('click', () => handleScan('front', container));
    document.getElementById('btn-scan-back').addEventListener('click', () => handleScan('back', container));

    // Multi-card toggle
    document.getElementById('multi-card-toggle').addEventListener('change', (e) => {
        state.multiMode = e.target.checked;
        const processBtn = document.getElementById('btn-process');
        if (processBtn) processBtn.innerHTML = `<i class="bi bi-play-circle me-2"></i>Process Card${state.multiMode ? 's' : ''}`;
    });

    // Process button — always uses runPipeline which auto-detects multi-card
    document.getElementById('btn-process').addEventListener('click', () => {
        runPipeline(container);
    });

    // Smart Scan button
    document.getElementById('btn-smart-scan').addEventListener('click', () => runSmartScan(container));
}

async function checkScanner() {
    const badge = document.getElementById('scanner-status');
    const scanFrontBtn = document.getElementById('btn-scan-front');
    const scanBackBtn = document.getElementById('btn-scan-back');
    const smartScanBtn = document.getElementById('btn-smart-scan');
    try {
        const res = await api.get('/scan/devices/list');
        const hasReal = res.real_devices && res.real_devices.length > 0;
        if (res.devices && res.devices.length > 0) {
            const d = res.devices[0];
            scanFrontBtn.disabled = false;
            if (state.frontImagePath) scanBackBtn.disabled = false;
            smartScanBtn.disabled = false;
            if (res.mock_mode) {
                badge.className = hasReal ? 'badge bg-info text-dark' : 'badge bg-warning text-dark';
                badge.textContent = hasReal
                    ? `Mock Mode (${res.real_devices[0].name} available)`
                    : 'Mock Mode (No scanner detected)';
            } else {
                badge.className = 'badge bg-success';
                badge.textContent = d.name;
            }
        } else {
            badge.className = 'badge bg-warning text-dark';
            badge.textContent = 'No scanner found';
        }
    } catch {
        badge.className = 'badge bg-danger';
        badge.textContent = 'Scanner offline';
    }
}

async function createSession() {
    if (state.sessionId) return;
    const preset = document.getElementById('scan-preset')?.value || 'detailed';
    const operator = document.getElementById('scan-operator')?.value || 'default';
    const res = await api.post(`/scan/start?preset=${preset}&operator=${encodeURIComponent(operator)}`);
    state.sessionId = res.session_id;
}

async function handleFileUpload(e, side, container) {
    const file = e.target.files[0];
    if (!file) return;
    try {
        await createSession();
        showToast(`Uploading ${side} image...`, 'info');
        const res = await api.uploadFile(`/scan/${state.sessionId}/upload?side=${side}`, file);
        if (side === 'front') {
            state.frontImageId = res.image_id;
            state.frontImagePath = res.path;
        } else {
            state.backImageId = res.image_id;
            state.backImagePath = res.path;
        }
        showToast(`${side} image uploaded`, 'success');
        // Re-render to update button states
        renderScanPhase(container);
    } catch (err) {
        showToast('Upload failed: ' + err.message, 'error');
    }
}

async function handleScan(side, container) {
    const btn = document.getElementById(`btn-scan-${side}`);
    const preview = document.getElementById(`scan-preview-${side}`);
    try {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Scanning...';
        if (preview) {
            preview.innerHTML = `
                <div class="text-center">
                    <div class="spinner-border text-light mb-2" style="width:2rem;height:2rem;"></div>
                    <div class="text-light small">Scanning ${side}...</div>
                </div>`;
        }
        await createSession();
        const preset = document.getElementById('scan-preset')?.value || 'detailed';
        const dpiMap = { fast_production: 300, detailed: 600, authenticity: 1200 };
        const dpi = dpiMap[preset] || 600;
        const res = await api.request('POST', `/scan/${state.sessionId}/acquire?side=${side}&dpi=${dpi}`, null, { timeout: 300000 });
        if (side === 'front') {
            state.frontImageId = res.image_id;
            state.frontImagePath = res.path;
        } else {
            state.backImageId = res.image_id;
            state.backImagePath = res.path;
        }
        showToast(`${side} scan complete: ${res.width}x${res.height} @ ${res.dpi}dpi`, 'success');
        renderScanPhase(container);
    } catch (err) {
        showToast(`${side} scan failed: ` + err.message, 'error');
        if (preview) {
            preview.innerHTML = `<span class="text-danger small">Scan failed. Try again.</span>`;
        }
        btn.disabled = false;
        btn.innerHTML = `<i class="bi bi-upc-scan me-1"></i>Scan ${side.charAt(0).toUpperCase() + side.slice(1)}`;
    }
}

// ─── Smart Scan: Quick 150 DPI → High-Res ────────────────────────────
async function runSmartScan(container) {
    const smartBtn = document.getElementById('btn-smart-scan');
    const preview = document.getElementById('scan-preview-front');

    smartBtn.disabled = true;
    smartBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Quick scan...';
    if (preview) {
        preview.innerHTML = `
            <div class="text-center">
                <div class="spinner-border text-info mb-2" style="width:2rem;height:2rem;"></div>
                <div class="text-light small">Step 1/3: Quick 150 DPI preview scan...</div>
            </div>`;
    }

    try {
        await createSession();

        // Step 1: Quick scan at 150 DPI for card detection
        const quickRes = await api.request('POST', `/scan/${state.sessionId}/acquire?side=front&dpi=150`, null, { timeout: 120000 });
        showToast('Quick scan done, card positions detected.', 'info');

        if (preview) {
            // Show the quick preview briefly
            showImagePreview('front', '/' + quickRes.path.replace(/\\/g, '/'));
            preview.innerHTML += `<div class="position-absolute bottom-0 start-0 end-0 bg-info bg-opacity-75 text-white text-center py-1 small">Quick preview - high-res scan starting...</div>`;
        }

        // Step 2: High-res scan at 600 DPI
        if (preview) {
            const overlay = preview.querySelector('.position-absolute');
            if (overlay) overlay.textContent = 'Step 2/3: High-res 600 DPI scan in progress...';
        }
        smartBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>High-res scan...';

        const hiRes = await api.request('POST', `/scan/${state.sessionId}/acquire?side=front&dpi=600`, null, { timeout: 300000 });
        state.frontImageId = hiRes.image_id;
        state.frontImagePath = hiRes.path;
        showToast(`High-res scan complete: ${hiRes.width}x${hiRes.height} @ 600dpi`, 'success');

        // Step 3: Prompt for back side
        smartBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Flip card for back...';
        if (preview) {
            const overlay = preview.querySelector('.position-absolute');
            if (overlay) overlay.textContent = 'Step 3/3: Place card back-side up and scanning...';
        }

        try {
            const backRes = await api.request('POST', `/scan/${state.sessionId}/acquire?side=back&dpi=300`, null, { timeout: 180000 });
            state.backImageId = backRes.image_id;
            state.backImagePath = backRes.path;
            showToast('Back side scanned!', 'success');
        } catch {
            showToast('Back scan skipped — will proceed with front only.', 'info');
        }

        renderScanPhase(container);
    } catch (err) {
        showToast('Smart scan failed: ' + err.message, 'error');
        smartBtn.disabled = false;
        smartBtn.innerHTML = '<i class="bi bi-lightning me-1"></i>Smart Scan (Quick + Detailed)';
    }
}

function showImagePreview(side, url) {
    const preview = document.getElementById(`scan-preview-${side}`);
    if (!preview) return;
    preview.innerHTML = '';
    preview.style.padding = '0';
    const img = document.createElement('img');
    img.src = url;
    img.style.cssText = `max-width:100%;max-height:${side === 'front' ? '400' : '200'}px;display:block;margin:auto;border-radius:8px;`;
    preview.appendChild(img);
}

// ─── Phase 2: Processing ────────────────────────────────────────────
async function runPipeline(container) {
    state.phase = 'processing';
    const steps = ['Vision Pipeline', 'OCR Text Recognition', 'Card Identification', 'Grading Analysis', 'AI Review', 'Authenticity Check'];
    container.innerHTML = `
        <div class="px-4 py-3">
            <h5 class="mb-4"><i class="bi bi-gear-wide-connected me-2"></i>Processing Card...</h5>
            <div class="row justify-content-center">
                <div class="col-lg-8">
                    <div class="card">
                        <div class="card-body">
                            ${steps.map((step, i) => `
                                <div class="d-flex align-items-center py-3 ${i < steps.length - 1 ? 'border-bottom' : ''}" id="step-${i}">
                                    <div class="me-3">
                                        <div class="spinner-border spinner-border-sm text-primary" id="step-spinner-${i}"></div>
                                        <i class="bi bi-check-circle-fill text-success d-none" id="step-check-${i}"></i>
                                        <i class="bi bi-x-circle-fill text-danger d-none" id="step-error-${i}"></i>
                                    </div>
                                    <div class="flex-grow-1">
                                        <div class="fw-semibold">${step}</div>
                                        <small class="text-muted" id="step-detail-${i}">Waiting...</small>
                                    </div>
                                </div>
                            `).join('')}
                        </div>
                    </div>
                    ${state.backImagePath ? '<div class="text-center mt-2"><small class="text-muted"><i class="bi bi-check-circle text-success me-1"></i>Back side image included in analysis</small></div>' : ''}
                </div>
            </div>
        </div>
    `;

    document.getElementById('step-detail-0').textContent = 'Running...';

    try {
        const url = state.multiMode
            ? `/scan/${state.sessionId}/process?force_multi=true`
            : `/scan/${state.sessionId}/process`;
        const res = await api.request('POST', url, null, { timeout: 600000 });

        // Auto-detected multiple cards — switch to multi-card report
        if (res.auto_multi) {
            state.multiResult = res;
            showToast(`Detected ${res.card_count} cards — processed individually`, 'success');
            await new Promise(r => setTimeout(r, 500));
            renderMultiReport(container);
            return;
        }

        state.pipelineResult = res;
        state.cardId = res.card_id;

        // Update step indicators
        const stepNames = ['vision_pipeline', 'ocr', 'card_identification', 'grading', 'ai_review', 'authenticity'];
        for (let i = 0; i < stepNames.length; i++) {
            const stepData = res.steps.find(s => s.step === stepNames[i]);
            const spinner = document.getElementById(`step-spinner-${i}`);
            const check = document.getElementById(`step-check-${i}`);
            const err = document.getElementById(`step-error-${i}`);
            const detail = document.getElementById(`step-detail-${i}`);

            if (spinner) spinner.classList.add('d-none');

            if (stepData && (stepData.status === 'ok' || stepData.status === 'partial')) {
                if (check) check.classList.remove('d-none');
                if (detail) { detail.textContent = getStepSummary(stepData); detail.className = 'small text-success'; }
            } else if (stepData && stepData.status === 'skipped') {
                if (check) check.classList.remove('d-none');
                if (detail) { detail.textContent = getStepSummary(stepData); detail.className = 'small text-muted'; }
            } else {
                if (err) err.classList.remove('d-none');
                if (detail) { detail.textContent = stepData?.error || 'Failed'; detail.className = 'small text-danger'; }
            }
        }

        await new Promise(r => setTimeout(r, 1000));
        renderReportPhase(container);
    } catch (err) {
        showToast('Processing failed: ' + err.message, 'error');
    }
}

function getStepSummary(step) {
    switch (step.step) {
        case 'vision_pipeline':
            return `${step.regions_extracted || 0} regions extracted, ${step.processing_time_ms || 0}ms`;
        case 'ocr':
            return step.text_length > 0 ? `${step.text_length} chars, engine: ${step.engine}` : `No text detected (${step.engine})`;
        case 'card_identification':
            return step.card_name ? `${step.card_name} (${((step.confidence || 0) * 100).toFixed(0)}%)` : 'Created as unknown, needs manual review';
        case 'grading':
            return step.final_grade ? `Grade: ${step.final_grade}, ${step.defect_count} defects` : 'Grading complete';
        case 'ai_review':
            if (step.status === 'skipped') return 'Skipped (AI not available)';
            return step.agrees_with_grade ? `AI agrees with grade (${((step.confidence || 0) * 100).toFixed(0)}% confidence)` :
                `AI suggests ${step.suggested_grade} (${((step.confidence || 0) * 100).toFixed(0)}% confidence)`;
        case 'authenticity':
            return `Decision: ${step.decision}, confidence: ${((step.confidence || 0) * 100).toFixed(0)}%`;
        default:
            return 'Done';
    }
}

// ─── Phase 3: Full Report ────────────────────────────────────────────
function renderReportPhase(container) {
    state.phase = 'report';
    const res = state.pipelineResult;
    if (!res) return;

    const vision = res.steps.find(s => s.step === 'vision_pipeline') || {};
    const ocr = res.steps.find(s => s.step === 'ocr') || {};
    const cardId = res.steps.find(s => s.step === 'card_identification') || {};
    const grading = res.steps.find(s => s.step === 'grading') || {};
    const aiReview = res.ai_review || res.steps.find(s => s.step === 'ai_review') || null;
    const auth = res.steps.find(s => s.step === 'authenticity') || {};

    const grade = grading.final_grade || 0;
    const subs = grading.sub_scores || {};
    const frontUrl = state.frontImagePath ? '/' + state.frontImagePath.replace(/\\/g, '/') : '';
    const backUrl = state.backImagePath ? '/' + state.backImagePath.replace(/\\/g, '/') : '';

    container.innerHTML = `
        <div class="px-4 py-3">
            <!-- Top Bar -->
            <div class="d-flex align-items-center justify-content-between mb-3">
                <div class="d-flex align-items-center gap-3">
                    <h5 class="mb-0">Card Report</h5>
                    ${createStatusBadge('completed')}
                </div>
                <div class="d-flex gap-2">
                    <button class="btn btn-outline-secondary" id="btn-new-scan">
                        <i class="bi bi-plus-circle me-1"></i>New Scan
                    </button>
                </div>
            </div>

            <div class="row">
                <!-- Left Column: Image + Defects -->
                <div class="col-lg-7 mb-4">
                    <div class="card mb-3">
                        <div class="card-header d-flex justify-content-between align-items-center">
                            <h6 class="mb-0"><i class="bi bi-image me-2"></i>Scanned Image</h6>
                            <div class="d-flex gap-2">
                                ${backUrl ? `
                                <div class="btn-group btn-group-sm">
                                    <button class="btn btn-outline-secondary active" id="btn-show-front">Front</button>
                                    <button class="btn btn-outline-secondary" id="btn-show-back">Back</button>
                                </div>` : ''}
                                <button class="btn btn-sm btn-outline-secondary" id="btn-toggle-defects">
                                    <i class="bi bi-eye me-1"></i>Toggle Defects
                                </button>
                                <button class="btn btn-sm btn-outline-secondary" id="btn-reset-zoom">
                                    <i class="bi bi-arrows-angle-expand me-1"></i>Fit
                                </button>
                            </div>
                        </div>
                        <div class="card-body p-0">
                            <div id="report-image-viewer" style="height:450px;background:#1a1a2e;"></div>
                        </div>
                    </div>

                    <!-- Defect List -->
                    <div class="card">
                        <div class="card-header">
                            <h6 class="mb-0"><i class="bi bi-bug me-2"></i>Defects Found
                                <span class="badge bg-secondary ms-1">${grading.defect_count || 0}</span>
                            </h6>
                        </div>
                        <div class="card-body p-0" id="defect-list-container" style="max-height:250px;overflow-y:auto;">
                            <div class="text-center text-muted py-3" id="defect-loading">Loading defects...</div>
                        </div>
                    </div>
                </div>

                <!-- Right Column: Grade + Card Info + Auth + Actions -->
                <div class="col-lg-5 mb-4">
                    <!-- Grade Card -->
                    <div class="card mb-3">
                        <div class="card-body text-center py-4">
                            <div class="mb-2"><small class="text-muted text-uppercase fw-semibold">Final Grade</small></div>
                            <div style="font-size:3.5rem;font-weight:800;line-height:1;" class="${gradeColor(grade)}">${grade.toFixed(1)}</div>
                            <div class="mt-2">${createGradeBadge(grade, 'lg')}</div>
                        </div>
                    </div>

                    <!-- Sub-Grades -->
                    <div class="card mb-3">
                        <div class="card-header"><h6 class="mb-0"><i class="bi bi-bar-chart me-2"></i>Sub-Grades</h6></div>
                        <div class="card-body">
                            ${renderSubGradeRow('Centering', subs.centering, 10)}
                            ${renderSubGradeRow('Corners', subs.corners, 30)}
                            ${renderSubGradeRow('Edges', subs.edges, 30)}
                            ${renderSubGradeRow('Surface', subs.surface, 30)}
                        </div>
                    </div>

                    <!-- Card Identification -->
                    <div class="card mb-3">
                        <div class="card-header"><h6 class="mb-0"><i class="bi bi-credit-card me-2"></i>Card Identity</h6></div>
                        <div class="card-body">
                            <table class="table table-sm table-borderless mb-0">
                                <tr><td class="text-muted" style="width:40%">Name</td><td class="fw-semibold">${cardId.card_name || 'Unknown'}</td></tr>
                                <tr><td class="text-muted">Set</td><td>${cardId.set_name || '\u2014'}</td></tr>
                                <tr><td class="text-muted">Confidence</td><td>${((cardId.confidence || 0) * 100).toFixed(0)}%</td></tr>
                                <tr><td class="text-muted">Serial</td><td><code>${cardId.serial || '\u2014'}</code></td></tr>
                                <tr><td class="text-muted">Card ID</td><td><code class="small">${res.card_id || '\u2014'}</code></td></tr>
                            </table>
                        </div>
                    </div>

                    <!-- Authenticity -->
                    <div class="card mb-3">
                        <div class="card-header"><h6 class="mb-0"><i class="bi bi-shield-check me-2"></i>Authenticity</h6></div>
                        <div class="card-body d-flex align-items-center justify-content-between">
                            ${createAuthBadge(auth.decision || 'pending')}
                            <span class="text-muted">Confidence: ${((auth.confidence || 0) * 100).toFixed(0)}%</span>
                        </div>
                    </div>

                    <!-- AI Analysis -->
                    ${aiReview && aiReview.status !== 'skipped' ? `
                    <div class="card mb-3">
                        <div class="card-header"><h6 class="mb-0"><i class="bi bi-robot me-2"></i>AI Analysis</h6></div>
                        <div class="card-body">
                            <div class="d-flex align-items-center justify-content-between mb-2">
                                <span class="fw-semibold">${aiReview.agrees_with_grade ? '<i class="bi bi-check-circle text-success me-1"></i>Agrees with grade' : '<i class="bi bi-exclamation-circle text-warning me-1"></i>Suggests adjustment'}</span>
                                ${aiReview.suggested_grade ? `<span class="badge bg-warning text-dark">Suggested: ${aiReview.suggested_grade}</span>` : ''}
                            </div>
                            <p class="small text-muted mb-2">${aiReview.overall_assessment || ''}</p>
                            ${aiReview.missed_defects?.length ? `<div class="small"><strong>Possible missed defects:</strong> ${aiReview.missed_defects.join(', ')}</div>` : ''}
                            ${aiReview.over_penalised?.length ? `<div class="small"><strong>Possibly over-penalised:</strong> ${aiReview.over_penalised.join(', ')}</div>` : ''}
                            <div class="mt-1"><small class="text-muted">Confidence: ${((aiReview.confidence || 0) * 100).toFixed(0)}%</small></div>
                        </div>
                    </div>
                    ` : ''}

                    <!-- Pipeline Summary -->
                    <div class="card mb-3">
                        <div class="card-header"><h6 class="mb-0"><i class="bi bi-list-check me-2"></i>Pipeline Steps</h6></div>
                        <div class="card-body p-0">
                            <table class="table table-sm mb-0">
                                <tbody>
                                    ${res.steps.map(s => `
                                        <tr>
                                            <td style="width:40%">${stepLabel(s.step)}</td>
                                            <td>${s.status === 'ok' ? '<i class="bi bi-check-circle text-success"></i>' :
                                                  s.status === 'partial' ? '<i class="bi bi-exclamation-circle text-warning"></i>' :
                                                  s.status === 'skipped' ? '<i class="bi bi-dash-circle text-muted"></i>' :
                                                  '<i class="bi bi-x-circle text-danger"></i>'} ${s.status}</td>
                                        </tr>
                                    `).join('')}
                                </tbody>
                            </table>
                        </div>
                    </div>

                </div>
            </div>
        </div>
    `;

    // Init image viewer
    initReportViewer(frontUrl);

    // Load defects
    loadDefects();

    // Front/Back toggle
    if (backUrl) {
        document.getElementById('btn-show-front')?.addEventListener('click', () => {
            initReportViewer(frontUrl);
            document.getElementById('btn-show-front').classList.add('active');
            document.getElementById('btn-show-back').classList.remove('active');
        });
        document.getElementById('btn-show-back')?.addEventListener('click', () => {
            initReportViewer(backUrl);
            document.getElementById('btn-show-back').classList.add('active');
            document.getElementById('btn-show-front').classList.remove('active');
        });
    }

    // Event handlers
    document.getElementById('btn-new-scan').addEventListener('click', () => {
        state = resetState();
        if (viewer) { viewer.destroy(); viewer = null; }
        renderScanPhase(container);
    });

    document.getElementById('btn-toggle-defects')?.addEventListener('click', () => {
        if (viewer) viewer.toggleOverlays();
    });
    document.getElementById('btn-reset-zoom')?.addEventListener('click', () => {
        if (viewer) viewer.resetView();
    });
}

async function initReportViewer(imgUrl) {
    if (!imgUrl) return;
    if (viewer) { viewer.destroy(); viewer = null; }
    viewer = new ImageViewer();
    try {
        await viewer.init('report-image-viewer', imgUrl);
    } catch (e) {
        console.error('Failed to init image viewer:', e);
    }
}

async function loadDefects() {
    const container = document.getElementById('defect-list-container');
    if (!container || !state.cardId) {
        if (container) container.innerHTML = '<div class="text-center text-muted py-3">No defect data available</div>';
        return;
    }
    try {
        const res = await api.get(`/grading/${state.cardId}/defects`);
        const defects = res.defects || res || [];
        if (!Array.isArray(defects) || defects.length === 0) {
            container.innerHTML = '<div class="text-center text-muted py-3">No defects found</div>';
            return;
        }

        container.innerHTML = `
            <table class="table table-sm table-hover mb-0">
                <thead class="table-light">
                    <tr><th>Category</th><th>Type</th><th>Severity</th><th>Impact</th></tr>
                </thead>
                <tbody>
                    ${defects.filter(d => !d.is_noise).map(d => `
                        <tr class="defect-row" data-x="${d.bbox_x||0}" data-y="${d.bbox_y||0}" data-w="${d.bbox_w||0}" data-h="${d.bbox_h||0}" style="cursor:pointer;">
                            <td>${d.category || '\u2014'}</td>
                            <td>${d.defect_type || '\u2014'}</td>
                            <td>${severityBadge(d.severity)}</td>
                            <td>${d.score_impact ? d.score_impact.toFixed(1) : '\u2014'}</td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        `;

        // Add defect overlays to viewer
        if (viewer) {
            for (const d of defects.filter(d => !d.is_noise && d.bbox_w > 0)) {
                const cls = d.severity === 'critical' ? 'defect-severe' :
                            d.severity === 'major' ? 'defect-major' :
                            d.severity === 'moderate' ? 'defect-moderate' : 'defect-minor';
                viewer.addOverlay(d.bbox_x, d.bbox_y, d.bbox_w, d.bbox_h, cls, `${d.category}: ${d.defect_type}`, d.id);
            }
        }

        // Click-to-zoom on defect rows
        container.querySelectorAll('.defect-row').forEach(row => {
            row.addEventListener('click', () => {
                const x = parseInt(row.dataset.x), y = parseInt(row.dataset.y);
                const w = parseInt(row.dataset.w), h = parseInt(row.dataset.h);
                if (viewer && w > 0 && h > 0) viewer.zoomToRegion(x, y, w, h);
            });
        });
    } catch (e) {
        container.innerHTML = `<div class="text-center text-muted py-3">Could not load defects</div>`;
    }
}

// ─── Multi-Card Pipeline ─────────────────────────────────────────────
async function runMultiPipeline(container) {
    state.phase = 'processing';
    container.innerHTML = `
        <div class="px-4 py-3">
            <h5 class="mb-4"><i class="bi bi-grid-3x2 me-2"></i>Processing Multiple Cards...</h5>
            <div class="row justify-content-center">
                <div class="col-lg-8">
                    <div class="card">
                        <div class="card-body text-center py-5">
                            <div class="spinner-border text-primary mb-3" style="width:3rem;height:3rem;"></div>
                            <div class="fw-semibold" id="multi-status">Detecting cards...</div>
                            <small class="text-muted" id="multi-detail">This may take a moment</small>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `;

    try {
        const res = await api.request('POST', `/scan/${state.sessionId}/process-multi`, null, { timeout: 600000 });
        state.multiResult = res;

        document.getElementById('multi-status').textContent = `Found ${res.card_count} card${res.card_count !== 1 ? 's' : ''}!`;
        document.getElementById('multi-detail').textContent = 'Loading report...';

        await new Promise(r => setTimeout(r, 800));
        renderMultiReport(container);
    } catch (err) {
        showToast('Multi-card processing failed: ' + err.message, 'error');
    }
}

function renderMultiReport(container) {
    state.phase = 'report';
    const res = state.multiResult;
    if (!res || !res.cards) return;

    const cards = res.cards;

    container.innerHTML = `
        <div class="px-4 py-3">
            <div class="d-flex align-items-center justify-content-between mb-3">
                <div class="d-flex align-items-center gap-3">
                    <h5 class="mb-0"><i class="bi bi-grid-3x2 me-2"></i>Multi-Card Report</h5>
                    <span class="badge bg-primary">${cards.length} cards detected</span>
                    ${createStatusBadge('completed')}
                </div>
                <div class="d-flex gap-2">
                    <button class="btn btn-outline-secondary" id="btn-new-scan-multi">
                        <i class="bi bi-plus-circle me-1"></i>New Scan
                    </button>
                </div>
            </div>

            <!-- Card selector -->
            <div class="d-flex gap-2 mb-3 flex-wrap" id="multi-card-selector">
                ${cards.map((c, i) => {
                    const gradeStep = c.steps.find(s => s.step === 'grading');
                    const grade = gradeStep?.final_grade || 0;
                    return `
                        <button class="btn ${i === 0 ? 'btn-primary' : 'btn-outline-secondary'} multi-card-btn" data-index="${i}">
                            <div class="fw-semibold small">${c.card_name || 'Card ' + (i + 1)}</div>
                            <div>${createGradeBadge(grade, 'sm')}</div>
                        </button>
                    `;
                }).join('')}
            </div>

            <!-- Selected card detail -->
            <div id="multi-card-detail"></div>
        </div>
    `;

    renderMultiCardDetail(cards[0], 0);

    container.querySelectorAll('.multi-card-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const idx = parseInt(btn.dataset.index);
            state.selectedCardIndex = idx;
            container.querySelectorAll('.multi-card-btn').forEach(b => b.className = 'btn btn-outline-secondary multi-card-btn');
            btn.className = 'btn btn-primary multi-card-btn';
            renderMultiCardDetail(cards[idx], idx);
        });
    });

    document.getElementById('btn-new-scan-multi').addEventListener('click', () => {
        state = resetState();
        state.multiMode = true;
        if (viewer) { viewer.destroy(); viewer = null; }
        renderScanPhase(container);
    });

}

function renderMultiCardDetail(card, index) {
    const detail = document.getElementById('multi-card-detail');
    if (!detail) return;

    const gradeStep = card.steps.find(s => s.step === 'grading') || {};
    const cardIdStep = card.steps.find(s => s.step === 'card_identification') || {};
    const grade = gradeStep.final_grade || 0;

    detail.innerHTML = `
        <div class="row">
            <div class="col-lg-6 mb-3">
                <div class="card">
                    <div class="card-header"><h6 class="mb-0">Card ${index + 1}: ${card.card_name || 'Unknown'}</h6></div>
                    <div class="card-body">
                        <div class="text-center mb-3">
                            <div style="font-size:3rem;font-weight:800;" class="${gradeColor(grade)}">${grade.toFixed(1)}</div>
                            ${createGradeBadge(grade, 'lg')}
                        </div>
                        <table class="table table-sm table-borderless mb-0">
                            <tr><td class="text-muted">Serial</td><td><code>${card.serial || cardIdStep.serial || '--'}</code></td></tr>
                            <tr><td class="text-muted">Confidence</td><td>${((cardIdStep.confidence || 0) * 100).toFixed(0)}%</td></tr>
                            <tr><td class="text-muted">Defects</td><td>${gradeStep.defect_count || 0}</td></tr>
                            <tr><td class="text-muted">Card ID</td><td><code class="small">${card.card_id || '--'}</code></td></tr>
                        </table>
                    </div>
                </div>
            </div>
            <div class="col-lg-6 mb-3">
                <div class="card">
                    <div class="card-header"><h6 class="mb-0">Pipeline Steps</h6></div>
                    <div class="card-body p-0">
                        <table class="table table-sm mb-0">
                            ${card.steps.map(s => `
                                <tr>
                                    <td>${stepLabel(s.step)}</td>
                                    <td>${s.status === 'ok' ? '<i class="bi bi-check-circle text-success"></i>' :
                                          s.status === 'partial' ? '<i class="bi bi-exclamation-circle text-warning"></i>' :
                                          '<i class="bi bi-x-circle text-danger"></i>'} ${s.status}</td>
                                </tr>
                            `).join('')}
                        </table>
                    </div>
                </div>

                <div class="card mt-3 border-primary">
                    <div class="card-body d-grid gap-2">
                        <button class="btn btn-outline-primary btn-view-review" data-card-id="${card.card_id}">
                            <i class="bi bi-clipboard-check me-1"></i>View Full Grade Review
                        </button>
                    </div>
                </div>
            </div>
        </div>
    `;

    // Attach event handlers
    detail.querySelector('.btn-view-review')?.addEventListener('click', (e) => {
        const cardRecordId = e.currentTarget.dataset.cardId;
        sessionStorage.setItem('rkt_review_card_id', cardRecordId);
        location.hash = '#/grade-review';
    });
}

// ─── Helpers ─────────────────────────────────────────────────────────
function gradeColor(grade) {
    if (grade >= 9) return 'text-success';
    if (grade >= 7) return 'text-info';
    if (grade >= 5) return 'text-warning';
    return 'text-danger';
}

function renderSubGradeRow(label, score, weight) {
    const val = score || 0;
    const pct = (val / 10) * 100;
    const color = val >= 9 ? 'success' : val >= 7 ? 'info' : val >= 5 ? 'warning' : 'danger';
    return `
        <div class="mb-3">
            <div class="d-flex justify-content-between mb-1">
                <span class="small fw-semibold">${label} <span class="text-muted fw-normal">(${weight}%)</span></span>
                <span class="small fw-bold text-${color}">${val.toFixed(1)}</span>
            </div>
            <div class="progress" style="height:8px;">
                <div class="progress-bar bg-${color}" style="width:${pct}%"></div>
            </div>
        </div>
    `;
}

function severityBadge(severity) {
    const map = { minor: 'warning', moderate: 'orange', major: 'danger', critical: 'dark' };
    const color = map[severity] || 'secondary';
    return `<span class="badge bg-${color}">${severity || '\u2014'}</span>`;
}

function stepLabel(step) {
    const map = {
        vision_pipeline: 'Vision',
        ocr: 'OCR',
        card_identification: 'Card ID',
        grading: 'Grading',
        ai_review: 'AI Review',
        authenticity: 'Auth Check',
    };
    return map[step] || step;
}
