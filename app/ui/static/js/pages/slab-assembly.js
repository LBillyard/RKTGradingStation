/**
 * Slab Assembly — Step-by-step workflow for printing slab inserts
 * and programming NFC tags.
 *
 * Flow: Select Card → Print Insert → Program NFC → Complete
 *
 * The NFC tag type (NTag213 or NTag424 DNA) is configured in
 * Settings → NFC / Printer. Default is NTag424 DNA (more secure).
 */
import { api } from '../api.js';
import { showToast } from '../components.js';

let _pollTimer = null;
let _currentAssembly = null;
let _nfcSettings = null;

export async function init(container) {
    try {
        _nfcSettings = await api.get('/settings/nfc');
    } catch {
        _nfcSettings = { default_tag_type: 'ntag424_dna', verify_base_url: 'https://rktgrading.com/verify' };
    }

    container.innerHTML = `
        <div class="px-4 py-3">
            <!-- Header -->
            <div class="d-flex justify-content-between align-items-center mb-3">
                <h5 class="mb-0"><i class="bi bi-box-seam me-2"></i>Slab Assembly</h5>
            </div>

            <!-- Stepper -->
            <div class="card mb-3">
                <div class="card-body py-3">
                    <div class="d-flex align-items-center justify-content-center gap-0" id="step-indicators">
                        <div class="slab-step active" data-step="select">
                            <span class="slab-step-num">1</span>
                            <span class="slab-step-label">Select Card</span>
                        </div>
                        <div class="slab-step-line"></div>
                        <div class="slab-step" data-step="print">
                            <span class="slab-step-num">2</span>
                            <span class="slab-step-label">Print Insert</span>
                        </div>
                        <div class="slab-step-line"></div>
                        <div class="slab-step" data-step="nfc">
                            <span class="slab-step-num">3</span>
                            <span class="slab-step-label">Program NFC</span>
                        </div>
                        <div class="slab-step-line"></div>
                        <div class="slab-step" data-step="complete">
                            <span class="slab-step-num">4</span>
                            <span class="slab-step-label">Complete</span>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Step content -->
            <div class="card mb-3">
                <div class="card-body" id="step-body">
                    <div class="text-center py-4">
                        <div class="spinner-border text-primary" role="status"></div>
                    </div>
                </div>
            </div>

            <!-- Assembly queue -->
            <div class="card">
                <div class="card-header d-flex justify-content-between align-items-center">
                    <span><i class="bi bi-list-task me-2"></i>Recent Assemblies</span>
                    <button class="btn btn-sm btn-outline-secondary" id="btn-refresh-queue">
                        <i class="bi bi-arrow-clockwise"></i>
                    </button>
                </div>
                <div class="card-body p-0">
                    <div class="table-responsive">
                        <table class="table table-hover mb-0">
                            <thead>
                                <tr>
                                    <th>Serial</th>
                                    <th>Card</th>
                                    <th>Grade</th>
                                    <th>Status</th>
                                    <th></th>
                                </tr>
                            </thead>
                            <tbody id="queue-tbody"></tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>
    `;

    document.getElementById('btn-refresh-queue')?.addEventListener('click', loadQueue);

    await showSelectCardStep();
    await loadQueue();
}

export function destroy() {
    if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
    _currentAssembly = null;
    _nfcSettings = null;
}

// ---- Helpers ----

function _tagTypeLabel(type) {
    return type === 'ntag424_dna' ? 'NTag424 DNA' : 'NTag213';
}

function _isSecureTag(type) {
    return type === 'ntag424_dna';
}

// ---- Step rendering ----

function updateStepIndicators(currentStep) {
    const steps = ['select', 'print', 'nfc', 'complete'];
    const currentIdx = steps.indexOf(currentStep);
    document.querySelectorAll('.slab-step').forEach(el => {
        const step = el.dataset.step;
        const idx = steps.indexOf(step);
        el.classList.remove('active', 'done');
        if (idx < currentIdx) el.classList.add('done');
        else if (idx === currentIdx) el.classList.add('active');
    });
    // Update connector lines
    document.querySelectorAll('.slab-step-line').forEach((line, i) => {
        line.classList.toggle('done', i < currentIdx);
    });
}

async function showSelectCardStep() {
    updateStepIndicators('select');
    const body = document.getElementById('step-body');

    try {
        const queueRes = await api.get('/queue/list?limit=100');
        const cards = queueRes.cards || [];
        const assemblies = await api.get('/slab/queue');
        const assembledCardIds = new Set(assemblies.map(a => a.card_record_id));
        const available = cards.filter(c =>
            !assembledCardIds.has(c.id) &&
            c.serial_number &&
            (c.grade_status === 'approved' || c.grade_status === 'overridden')
        );

        if (available.length === 0) {
            body.innerHTML = `
                <div class="text-center py-5 text-muted">
                    <i class="bi bi-inbox fs-1 d-block mb-3"></i>
                    <h6>No graded cards ready for slab assembly</h6>
                    <small>Cards must have an approved grade before assembly.</small>
                </div>`;
            return;
        }

        body.innerHTML = `
            <h6 class="mb-3">Select a graded card to begin slab assembly</h6>
            <div class="table-responsive">
                <table class="table table-hover mb-0">
                    <thead><tr><th>Serial</th><th>Card Name</th><th>Set</th><th>Grade</th><th></th></tr></thead>
                    <tbody>
                        ${available.map(c => `
                            <tr>
                                <td><code class="small">${c.serial_number || '—'}</code></td>
                                <td>${c.card_name || 'Unknown'}</td>
                                <td class="text-muted">${c.set_name || '—'}</td>
                                <td><span class="badge bg-primary">${c.final_grade || '—'}</span></td>
                                <td class="text-end">
                                    <button class="btn btn-sm btn-primary btn-start-assembly" data-card-id="${c.id}">
                                        <i class="bi bi-play-fill me-1"></i>Start
                                    </button>
                                </td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>`;

        body.querySelectorAll('.btn-start-assembly').forEach(btn => {
            btn.addEventListener('click', async () => {
                btn.disabled = true;
                btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
                try {
                    const assembly = await api.post('/slab/start', { card_record_id: btn.dataset.cardId });
                    _currentAssembly = assembly;
                    await showPrintStep();
                    await loadQueue();
                } catch (e) {
                    showToast('Failed to start assembly: ' + e.message, 'danger');
                    btn.disabled = false;
                    btn.innerHTML = '<i class="bi bi-play-fill me-1"></i>Start';
                }
            });
        });
    } catch (e) {
        body.innerHTML = `<div class="alert alert-warning m-0"><i class="bi bi-exclamation-triangle me-2"></i>Could not load cards: ${e.message}</div>`;
    }
}

async function showPrintStep() {
    updateStepIndicators('print');
    const body = document.getElementById('step-body');
    const a = _currentAssembly;

    if (a.print_job && a.print_job.status === 'printed') {
        await showNfcStep();
        return;
    }

    let printers = [];
    try {
        const res = await api.get('/slab/printers/list');
        printers = res.printers || [];
    } catch { /* ignore */ }

    body.innerHTML = `
        <div class="row">
            <div class="col-lg-7">
                <h6 class="mb-3"><i class="bi bi-printer me-2"></i>Print Slab Insert</h6>
                <div class="row g-3">
                    <div class="col-sm-6">
                        <label class="form-label small text-muted">Card</label>
                        <input class="form-control form-control-sm" disabled value="${a.card?.card_name || 'Unknown'}">
                    </div>
                    <div class="col-sm-3">
                        <label class="form-label small text-muted">Grade</label>
                        <input class="form-control form-control-sm" disabled value="${a.grade || '—'}">
                    </div>
                    <div class="col-sm-3">
                        <label class="form-label small text-muted">Serial</label>
                        <input class="form-control form-control-sm" disabled value="${a.serial_number}">
                    </div>
                    <div class="col-sm-8">
                        <label class="form-label small text-muted">Printer</label>
                        <select class="form-select form-select-sm" id="printer-select">
                            ${printers.map(p => `<option value="${p}">${p}</option>`).join('')}
                            ${printers.length === 0 ? '<option value="">No printers found</option>' : ''}
                        </select>
                    </div>
                    <div class="col-sm-4 d-flex align-items-end">
                        <button class="btn btn-primary w-100" id="btn-print">
                            <i class="bi bi-printer me-1"></i>Print
                        </button>
                    </div>
                </div>
                <div id="print-status" class="mt-3"></div>
            </div>
            <div class="col-lg-5">
                <div class="border rounded text-center p-4 h-100 d-flex align-items-center justify-content-center" id="print-preview" style="min-height: 150px; background: var(--bg-body);">
                    <div class="text-muted">
                        <i class="bi bi-image fs-2 d-block mb-2"></i>
                        <small>Label preview</small>
                    </div>
                </div>
            </div>
        </div>`;

    document.getElementById('btn-print')?.addEventListener('click', async () => {
        const btn = document.getElementById('btn-print');
        const statusDiv = document.getElementById('print-status');
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Printing...';
        statusDiv.innerHTML = '<div class="alert alert-info alert-sm py-2 small"><i class="bi bi-hourglass-split me-1"></i>Rendering and printing label...</div>';

        try {
            const result = await api.post(`/slab/${a.id}/print`, {
                printer_name: document.getElementById('printer-select')?.value || '',
            });
            _currentAssembly = result;

            if (result.print_job?.status === 'printed') {
                statusDiv.innerHTML = '<div class="alert alert-success py-2 small"><i class="bi bi-check-circle me-1"></i>Label printed!</div>';
                if (result.print_job.image_path) {
                    document.getElementById('print-preview').innerHTML =
                        `<img src="/${result.print_job.image_path}" class="img-fluid rounded" alt="Label">`;
                }
                setTimeout(() => showNfcStep(), 1200);
            } else {
                statusDiv.innerHTML = `<div class="alert alert-danger py-2 small"><i class="bi bi-x-circle me-1"></i>${result.print_job?.error_message || 'Print failed'}</div>`;
                btn.disabled = false;
                btn.innerHTML = '<i class="bi bi-printer me-1"></i>Retry';
            }
        } catch (e) {
            statusDiv.innerHTML = `<div class="alert alert-danger py-2 small"><i class="bi bi-x-circle me-1"></i>${e.message}</div>`;
            btn.disabled = false;
            btn.innerHTML = '<i class="bi bi-printer me-1"></i>Retry';
        }
        await loadQueue();
    });
}

async function showNfcStep() {
    updateStepIndicators('nfc');
    const body = document.getElementById('step-body');
    const a = _currentAssembly;
    const tagType = _nfcSettings?.default_tag_type || 'ntag424_dna';
    const isSecure = _isSecureTag(tagType);
    const nfcTag = a.nfc_tag;

    if (nfcTag && nfcTag.status === 'programmed') {
        await showCompleteStep();
        return;
    }

    const tagLabel = _tagTypeLabel(tagType);
    const apiEndpoint = isSecure ? 'ntag424' : 'ntag213';
    const baseUrl = _nfcSettings?.verify_base_url || 'https://rktgrading.com/verify';
    const icon = isSecure ? 'bi-shield-lock' : 'bi-nfc';

    body.innerHTML = `
        <h6 class="mb-3"><i class="bi ${icon} me-2"></i>Program NFC Tag</h6>
        <div class="row align-items-center">
            <div class="col-lg-8">
                <div class="alert ${isSecure ? 'alert-warning' : 'alert-info'} py-2 small mb-3">
                    <i class="bi ${isSecure ? 'bi-shield-exclamation' : 'bi-info-circle'} me-1"></i>
                    Place a <strong>${tagLabel}</strong> tag on the NFC reader, then click Program.
                    ${isSecure ? 'Each tap will generate a unique cryptographic URL.' : ''}
                </div>
                <div class="d-flex align-items-center gap-3 mb-3">
                    <div>
                        <span class="badge ${isSecure ? 'bg-warning text-dark' : 'bg-secondary'}">${tagLabel}</span>
                        <a href="#/settings" class="ms-2 small text-muted">Change</a>
                    </div>
                    <div class="text-muted small">Serial: <code>${a.serial_number}</code></div>
                </div>
            </div>
            <div class="col-lg-4 text-end">
                <button class="btn ${isSecure ? 'btn-warning' : 'btn-primary'}" id="btn-program-nfc">
                    <i class="bi ${icon} me-1"></i>Program ${tagLabel}
                </button>
            </div>
        </div>
        <div id="nfc-status"></div>`;

    document.getElementById('btn-program-nfc')?.addEventListener('click', async () => {
        const btn = document.getElementById('btn-program-nfc');
        const statusDiv = document.getElementById('nfc-status');
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Programming...';
        statusDiv.innerHTML = `<div class="alert alert-info py-2 small"><i class="bi bi-hourglass-split me-1"></i>${isSecure ? 'Configuring SUN/SDM...' : 'Writing NDEF URL...'}</div>`;

        try {
            const result = await api.post(`/slab/${a.id}/nfc/${apiEndpoint}`, {});
            _currentAssembly = result;
            const tag = result.nfc_tag;

            if (tag?.status === 'programmed') {
                statusDiv.innerHTML = `<div class="alert alert-success py-2 small"><i class="bi bi-check-circle me-1"></i>${tagLabel} programmed! UID: <code>${tag.tag_uid}</code></div>`;
                setTimeout(() => showCompleteStep(), 1200);
            } else {
                statusDiv.innerHTML = `<div class="alert alert-danger py-2 small"><i class="bi bi-x-circle me-1"></i>${tag?.error_message || 'Failed'}</div>`;
                btn.disabled = false;
                btn.innerHTML = `<i class="bi ${icon} me-1"></i>Retry`;
            }
        } catch (e) {
            statusDiv.innerHTML = `<div class="alert alert-danger py-2 small"><i class="bi bi-x-circle me-1"></i>${e.message}</div>`;
            btn.disabled = false;
            btn.innerHTML = `<i class="bi ${icon} me-1"></i>Retry`;
        }
        await loadQueue();
    });
}

async function showCompleteStep() {
    updateStepIndicators('complete');
    const body = document.getElementById('step-body');
    const a = _currentAssembly;
    const nfcTag = a.nfc_tag;
    const tagLabel = nfcTag ? _tagTypeLabel(nfcTag.tag_type) : 'NFC Tag';

    body.innerHTML = `
        <div class="text-center py-4">
            <i class="bi bi-check-circle-fill text-success" style="font-size: 2.5rem;"></i>
            <h5 class="mt-2 mb-1">Assembly Complete</h5>
            <p class="text-muted small mb-3"><code>${a.serial_number}</code></p>

            <div class="row justify-content-center">
                <div class="col-md-6">
                    <table class="table table-sm text-start mb-3">
                        <tr>
                            <td class="text-muted"><i class="bi bi-printer me-1"></i>Label</td>
                            <td>${a.print_job?.status === 'printed'
                                ? '<span class="badge bg-success">Printed</span>'
                                : '<span class="badge bg-secondary">Pending</span>'}</td>
                        </tr>
                        <tr>
                            <td class="text-muted"><i class="bi ${nfcTag?.tag_type === 'ntag424_dna' ? 'bi-shield-lock' : 'bi-nfc'} me-1"></i>${tagLabel}</td>
                            <td>${nfcTag?.status === 'programmed'
                                ? `<span class="badge bg-success">Done</span> <code class="small">${nfcTag.tag_uid}</code>`
                                : '<span class="badge bg-secondary">Pending</span>'}</td>
                        </tr>
                    </table>
                </div>
            </div>

            <div class="d-flex justify-content-center gap-2">
                ${a.workflow_status !== 'complete' ? `
                    <button class="btn btn-success" id="btn-finalize">
                        <i class="bi bi-check2-all me-1"></i>Finalize
                    </button>
                ` : '<span class="badge bg-success py-2 px-3">Finalized</span>'}
                <button class="btn btn-outline-primary" id="btn-new-assembly">
                    <i class="bi bi-plus me-1"></i>New Assembly
                </button>
            </div>
        </div>`;

    document.getElementById('btn-finalize')?.addEventListener('click', async () => {
        try {
            const result = await api.post(`/slab/${a.id}/complete`, {});
            _currentAssembly = result;
            showToast('Assembly finalized!', 'success');
            await showCompleteStep();
            await loadQueue();
        } catch (e) {
            showToast('Failed: ' + e.message, 'danger');
        }
    });

    document.getElementById('btn-new-assembly')?.addEventListener('click', async () => {
        _currentAssembly = null;
        await showSelectCardStep();
    });
}

// ---- Queue ----

async function loadQueue() {
    const tbody = document.getElementById('queue-tbody');
    if (!tbody) return;

    try {
        const assemblies = await api.get('/slab/queue');
        if (!assemblies || assemblies.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted py-3 small">No assemblies yet</td></tr>';
            return;
        }

        const statusColors = {
            graded: 'secondary', insert_printed: 'info',
            nfc_programmed: 'primary', complete: 'success',
        };

        tbody.innerHTML = assemblies.map(a => `
            <tr class="${_currentAssembly?.id === a.id ? 'table-active' : ''}">
                <td><code class="small">${a.serial_number}</code></td>
                <td class="small">${a.card?.card_name || '—'}</td>
                <td><span class="badge bg-primary">${a.grade || '—'}</span></td>
                <td><span class="badge bg-${statusColors[a.workflow_status] || 'secondary'}">${a.workflow_status.replace(/_/g, ' ')}</span></td>
                <td class="text-end">
                    <button class="btn btn-sm btn-outline-secondary btn-resume" data-id="${a.id}">
                        ${a.workflow_status === 'complete' ? 'View' : 'Resume'}
                    </button>
                </td>
            </tr>
        `).join('');

        tbody.querySelectorAll('.btn-resume').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                e.stopPropagation();
                try {
                    const assembly = await api.get(`/slab/${btn.dataset.id}`);
                    _currentAssembly = assembly;
                    switch (assembly.workflow_status) {
                        case 'graded': await showPrintStep(); break;
                        case 'insert_printed': await showNfcStep(); break;
                        case 'nfc_programmed': await showCompleteStep(); break;
                        case 'complete': await showCompleteStep(); break;
                        default: await showPrintStep();
                    }
                } catch (e) {
                    showToast('Failed to load assembly: ' + e.message, 'danger');
                }
            });
        });
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="5" class="text-danger small">Error: ${e.message}</td></tr>`;
    }
}
