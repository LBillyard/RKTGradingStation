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
    // Load NFC settings to know which tag type to use
    try {
        _nfcSettings = await api.get('/settings/nfc');
    } catch {
        _nfcSettings = { default_tag_type: 'ntag424_dna', verify_base_url: 'https://rktgrading.com/verify' };
    }

    container.innerHTML = `
        <div class="d-flex justify-content-between align-items-center mb-4">
            <h4 class="mb-0"><i class="bi bi-box-seam me-2"></i>Slab Assembly</h4>
            <div id="assembly-status-badge"></div>
        </div>

        <!-- Step indicators -->
        <div class="d-flex gap-2 mb-4" id="step-indicators">
            <div class="step-pill active" data-step="select">
                <i class="bi bi-1-circle me-1"></i>Select Card
            </div>
            <div class="step-pill" data-step="print">
                <i class="bi bi-2-circle me-1"></i>Print Insert
            </div>
            <div class="step-pill" data-step="nfc">
                <i class="bi bi-3-circle me-1"></i>Program NFC
            </div>
            <div class="step-pill" data-step="complete">
                <i class="bi bi-4-circle me-1"></i>Complete
            </div>
        </div>

        <!-- Step content -->
        <div id="step-content" class="card">
            <div class="card-body" id="step-body">
                <div class="text-center py-4">
                    <div class="spinner-border text-primary" role="status"></div>
                </div>
            </div>
        </div>

        <!-- Assembly queue -->
        <div class="card mt-4">
            <div class="card-header d-flex justify-content-between align-items-center">
                <span><i class="bi bi-list-task me-2"></i>Assembly Queue</span>
                <button class="btn btn-sm btn-outline-secondary" id="btn-refresh-queue">
                    <i class="bi bi-arrow-clockwise"></i>
                </button>
            </div>
            <div class="card-body p-0">
                <div id="queue-table-container">
                    <table class="table table-hover mb-0">
                        <thead>
                            <tr>
                                <th>Serial</th>
                                <th>Card</th>
                                <th>Grade</th>
                                <th>Status</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody id="queue-tbody"></tbody>
                    </table>
                </div>
            </div>
        </div>

        <style>
            .step-pill {
                padding: 6px 14px;
                border-radius: 20px;
                background: var(--bs-gray-200);
                font-size: 0.85rem;
                cursor: pointer;
                transition: all 0.2s;
            }
            .step-pill.active {
                background: var(--bs-primary);
                color: white;
            }
            .step-pill.done {
                background: var(--bs-success);
                color: white;
            }
            .step-pill.done i::before { content: "\\F26A"; }
        </style>
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
    document.querySelectorAll('.step-pill').forEach(pill => {
        const step = pill.dataset.step;
        const idx = steps.indexOf(step);
        pill.classList.remove('active', 'done');
        if (idx < currentIdx) pill.classList.add('done');
        else if (idx === currentIdx) pill.classList.add('active');
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
                <div class="text-center py-4 text-muted">
                    <i class="bi bi-inbox fs-1 d-block mb-2"></i>
                    <p>No graded cards ready for slab assembly.</p>
                    <small>Cards must have an approved grade before assembly.</small>
                </div>`;
            return;
        }

        body.innerHTML = `
            <h5 class="mb-3">Select a graded card to begin slab assembly</h5>
            <div class="table-responsive">
                <table class="table table-hover">
                    <thead>
                        <tr><th>Serial</th><th>Card Name</th><th>Set</th><th>Grade</th><th></th></tr>
                    </thead>
                    <tbody>
                        ${available.map(c => `
                            <tr>
                                <td><code>${c.serial_number || '—'}</code></td>
                                <td>${c.card_name || 'Unknown'}</td>
                                <td>${c.set_name || '—'}</td>
                                <td><span class="badge bg-primary">${c.final_grade || '—'}</span></td>
                                <td>
                                    <button class="btn btn-sm btn-primary btn-start-assembly"
                                            data-card-id="${c.id}">
                                        Start Assembly
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
                    const assembly = await api.post('/slab/start', {
                        card_record_id: btn.dataset.cardId,
                    });
                    _currentAssembly = assembly;
                    await showPrintStep();
                    await loadQueue();
                } catch (e) {
                    showToast('Failed to start assembly: ' + e.message, 'danger');
                    btn.disabled = false;
                    btn.textContent = 'Start Assembly';
                }
            });
        });
    } catch (e) {
        body.innerHTML = `
            <div class="alert alert-warning">
                <i class="bi bi-exclamation-triangle me-2"></i>
                Could not load cards: ${e.message}
            </div>`;
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
        <h5 class="mb-3"><i class="bi bi-printer me-2"></i>Print Slab Insert</h5>
        <div class="row">
            <div class="col-md-6">
                <div class="mb-3">
                    <label class="form-label">Card</label>
                    <input class="form-control" disabled value="${a.card?.card_name || 'Unknown'} — ${a.serial_number}">
                </div>
                <div class="mb-3">
                    <label class="form-label">Grade</label>
                    <input class="form-control" disabled value="${a.grade || '—'}">
                </div>
                <div class="mb-3">
                    <label class="form-label">Printer</label>
                    <select class="form-select" id="printer-select">
                        ${printers.map(p => `<option value="${p}">${p}</option>`).join('')}
                        ${printers.length === 0 ? '<option value="">No printers found</option>' : ''}
                    </select>
                </div>
                <button class="btn btn-primary" id="btn-print">
                    <i class="bi bi-printer me-2"></i>Print Label
                </button>
            </div>
            <div class="col-md-6">
                <div class="card bg-light">
                    <div class="card-body text-center" id="print-preview">
                        <i class="bi bi-image fs-1 text-muted d-block mb-2"></i>
                        <small class="text-muted">Label preview will appear after rendering</small>
                    </div>
                </div>
            </div>
        </div>
        <div id="print-status" class="mt-3"></div>`;

    document.getElementById('btn-print')?.addEventListener('click', async () => {
        const btn = document.getElementById('btn-print');
        const statusDiv = document.getElementById('print-status');
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Printing...';
        statusDiv.innerHTML = '<div class="alert alert-info"><i class="bi bi-hourglass-split me-2"></i>Rendering and printing label...</div>';

        try {
            const result = await api.post(`/slab/${a.id}/print`, {
                printer_name: document.getElementById('printer-select')?.value || '',
            });
            _currentAssembly = result;

            if (result.print_job?.status === 'printed') {
                statusDiv.innerHTML = '<div class="alert alert-success"><i class="bi bi-check-circle me-2"></i>Label printed successfully!</div>';
                if (result.print_job.image_path) {
                    document.getElementById('print-preview').innerHTML =
                        `<img src="/${result.print_job.image_path}" class="img-fluid" alt="Label preview">`;
                }
                setTimeout(() => showNfcStep(), 1500);
            } else {
                statusDiv.innerHTML = `<div class="alert alert-danger"><i class="bi bi-x-circle me-2"></i>Print failed: ${result.print_job?.error_message || 'Unknown error'}</div>`;
                btn.disabled = false;
                btn.innerHTML = '<i class="bi bi-printer me-2"></i>Retry Print';
            }
        } catch (e) {
            statusDiv.innerHTML = `<div class="alert alert-danger"><i class="bi bi-x-circle me-2"></i>${e.message}</div>`;
            btn.disabled = false;
            btn.innerHTML = '<i class="bi bi-printer me-2"></i>Retry Print';
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

    // Check if NFC already programmed
    const nfcTag = a.nfc_tag;
    if (nfcTag && nfcTag.status === 'programmed') {
        await showCompleteStep();
        return;
    }

    const tagLabel = _tagTypeLabel(tagType);
    const apiEndpoint = isSecure ? 'ntag424' : 'ntag213';
    const baseUrl = _nfcSettings?.verify_base_url || 'https://rktgrading.com/verify';

    const urlPreview = isSecure
        ? `${baseUrl}?s=${a.serial_number}&p=&lt;encrypted_picc_data&gt;&c=&lt;cmac&gt;`
        : `${baseUrl}/${a.serial_number}`;

    const icon = isSecure ? 'bi-shield-lock' : 'bi-nfc';
    const btnClass = isSecure ? 'btn-warning' : 'btn-primary';

    body.innerHTML = `
        <h5 class="mb-3"><i class="bi ${icon} me-2"></i>Program NFC Tag</h5>
        <div class="alert ${isSecure ? 'alert-warning' : 'alert-info'}">
            <i class="bi ${isSecure ? 'bi-shield-exclamation' : 'bi-info-circle'} me-2"></i>
            Place an <strong>${tagLabel}</strong> tag on the NFC reader, then click "Program".
            ${isSecure
                ? 'This configures Secure Dynamic Messaging (SUN/SDM) — each tap generates a unique cryptographic URL that cannot be cloned or replayed.'
                : 'This writes a simple verification URL to the tag.'}
        </div>
        <div class="row align-items-center">
            <div class="col-md-8">
                <p><strong>Tag type:</strong> <span class="badge ${isSecure ? 'bg-warning text-dark' : 'bg-secondary'}">${tagLabel}</span>
                    <a href="#/settings" class="ms-2 small text-muted">Change in Settings</a>
                </p>
                <p><strong>URL ${isSecure ? 'template' : 'to write'}:</strong></p>
                <code class="d-block text-break">${urlPreview}</code>
                ${isSecure ? '<small class="text-muted mt-1 d-block">The picc_data and cmac fields are filled dynamically by the tag hardware on each tap.</small>' : ''}
            </div>
            <div class="col-md-4 text-end">
                <button class="${btnClass} btn btn-lg" id="btn-program-nfc">
                    <i class="bi ${icon} me-2"></i>Program ${tagLabel}
                </button>
            </div>
        </div>
        <div id="nfc-status" class="mt-3"></div>`;

    document.getElementById('btn-program-nfc')?.addEventListener('click', async () => {
        const btn = document.getElementById('btn-program-nfc');
        const statusDiv = document.getElementById('nfc-status');
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Programming...';
        statusDiv.innerHTML = `<div class="alert alert-info"><i class="bi bi-hourglass-split me-2"></i>${isSecure ? 'Configuring SUN/SDM on NTag424 DNA...' : 'Writing NDEF URL to NTag213...'}</div>`;

        try {
            const result = await api.post(`/slab/${a.id}/nfc/${apiEndpoint}`, {});
            _currentAssembly = result;

            const tag = result.nfc_tag;
            if (tag?.status === 'programmed') {
                statusDiv.innerHTML = `
                    <div class="alert alert-success">
                        <i class="bi bi-check-circle me-2"></i>${tagLabel} programmed!
                        <br><small>UID: ${tag.tag_uid}${isSecure ? ' | SDM: ' + (tag.sdm_configured ? 'Configured' : 'N/A') : ''}</small>
                    </div>`;
                setTimeout(() => showCompleteStep(), 1500);
            } else {
                statusDiv.innerHTML = `<div class="alert alert-danger"><i class="bi bi-x-circle me-2"></i>Failed: ${tag?.error_message || 'Unknown error'}</div>`;
                btn.disabled = false;
                btn.innerHTML = `<i class="bi ${icon} me-2"></i>Retry`;
            }
        } catch (e) {
            statusDiv.innerHTML = `<div class="alert alert-danger"><i class="bi bi-x-circle me-2"></i>${e.message}</div>`;
            btn.disabled = false;
            btn.innerHTML = `<i class="bi ${icon} me-2"></i>Retry`;
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
            <i class="bi bi-check-circle text-success" style="font-size: 3rem;"></i>
            <h4 class="mt-3">Slab Assembly Complete</h4>
            <p class="text-muted">All steps finished for <strong>${a.serial_number}</strong></p>

            <div class="row justify-content-center mt-4">
                <div class="col-md-8">
                    <table class="table text-start">
                        <tr>
                            <td><i class="bi bi-printer me-2 text-success"></i>Label Printed</td>
                            <td>${a.print_job?.status === 'printed' ? '<span class="badge bg-success">Done</span>' : '<span class="badge bg-warning">Pending</span>'}</td>
                        </tr>
                        <tr>
                            <td><i class="bi ${nfcTag?.tag_type === 'ntag424_dna' ? 'bi-shield-lock' : 'bi-nfc'} me-2 text-success"></i>${tagLabel}</td>
                            <td>${nfcTag?.status === 'programmed'
                                ? `<span class="badge bg-success">Done</span> <small class="text-muted">UID: ${nfcTag.tag_uid}</small>`
                                : '<span class="badge bg-warning">Pending</span>'}</td>
                        </tr>
                    </table>
                </div>
            </div>

            ${a.workflow_status !== 'complete' ? `
                <button class="btn btn-success btn-lg mt-3" id="btn-finalize">
                    <i class="bi bi-check2-all me-2"></i>Finalize Assembly
                </button>
            ` : '<span class="badge bg-success fs-6 mt-3">Finalized</span>'}

            <div class="mt-3">
                <button class="btn btn-outline-primary" id="btn-new-assembly">
                    <i class="bi bi-plus-circle me-2"></i>Start New Assembly
                </button>
            </div>
        </div>`;

    document.getElementById('btn-finalize')?.addEventListener('click', async () => {
        try {
            const result = await api.post(`/slab/${a.id}/complete`, {});
            _currentAssembly = result;
            showToast('Slab assembly finalized!', 'success');
            await showCompleteStep();
            await loadQueue();
        } catch (e) {
            showToast('Failed to finalize: ' + e.message, 'danger');
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
            tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted py-3">No assemblies yet</td></tr>';
            return;
        }

        const statusColors = {
            graded: 'secondary', insert_printed: 'info',
            nfc_programmed: 'primary', complete: 'success',
        };

        tbody.innerHTML = assemblies.map(a => `
            <tr class="${_currentAssembly?.id === a.id ? 'table-active' : ''}" style="cursor:pointer" data-id="${a.id}">
                <td><code>${a.serial_number}</code></td>
                <td>${a.card?.card_name || '—'}</td>
                <td><span class="badge bg-primary">${a.grade || '—'}</span></td>
                <td><span class="badge bg-${statusColors[a.workflow_status] || 'secondary'}">${a.workflow_status.replace(/_/g, ' ')}</span></td>
                <td>
                    <button class="btn btn-sm btn-outline-primary btn-resume" data-id="${a.id}">
                        ${a.workflow_status === 'complete' ? 'View' : 'Resume'}
                    </button>
                </td>
            </tr>
        `).join('');

        tbody.querySelectorAll('.btn-resume').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                e.stopPropagation();
                const id = btn.dataset.id;
                try {
                    const assembly = await api.get(`/slab/${id}`);
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
        tbody.innerHTML = `<tr><td colspan="5" class="text-danger">Error: ${e.message}</td></tr>`;
    }
}
