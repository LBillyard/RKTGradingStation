/**
 * Training Mode — Expert grades cards manually, AI grades independently,
 * system shows comparison and learns from deltas.
 */
import { api } from '../api.js';
import { showToast, escapeHtml } from '../components.js';

let _currentCard = null;

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

export function destroy() { _currentCard = null; }

async function showSelectStep() {
    const body = document.getElementById('step-select') || document.getElementById('training-body');

    try {
        const res = await api.get('/queue/list?limit=100');
        const cards = res.cards || [];

        body.innerHTML = `
            <h6 class="mb-3">Step 1: Select a card to grade</h6>
            <div class="row g-2 mb-3">
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
        body.innerHTML = `<div class="alert alert-warning">Could not load cards: ${escapeHtml(e.message)}</div>`;
    }
}

function showExpertGradeStep() {
    const body = document.getElementById('training-body');
    const c = _currentCard;

    body.innerHTML = `
        <div class="d-flex justify-content-between align-items-center mb-3">
            <h6 class="mb-0">Step 2: Enter your expert grades</h6>
            <span class="badge bg-secondary">${escapeHtml(c.serial_number)}</span>
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
                <p class="small text-muted mb-0">${expert.defect_notes}</p>
            </div>` : ''}

        ${data.ai_defects?.length ? `
            <div class="mb-3">
                <strong class="small">AI Detected Defects (${data.ai_defects.length}):</strong>
                <div class="small">
                    ${data.ai_defects.map(d => `
                        <span class="badge bg-${d.severity === 'critical' ? 'danger' : d.severity === 'major' ? 'warning text-dark' : 'secondary'} me-1 mb-1">${d.category}: ${d.defect_type} (${d.severity})</span>
                    `).join('')}
                </div>
            </div>` : ''}

        <button class="btn btn-primary" id="btn-grade-another">
            <i class="bi bi-plus me-1"></i>Grade Another Card
        </button>`;

    document.getElementById('btn-grade-another')?.addEventListener('click', () => {
        _currentCard = null;
        document.getElementById('training-body').innerHTML = '<div id="step-select"></div>';
        showSelectStep();
    });
}

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
