/**
 * Authenticity Review page module.
 *
 * Full implementation of the authenticity review workflow:
 * - Card selector/search
 * - Side-by-side scan vs reference comparison
 * - Detailed check results table with expandable rows
 * - Confidence gauge with color-coded thresholds
 * - Status badge and action buttons
 * - Override modal with mandatory reason
 */
import { api } from '../api.js';
import { createEmptyState, createAuthBadge, createLoadingSpinner, showToast } from '../components.js';

/** Module state */
let _container = null;
let _currentCardId = null;
let _decisionData = null;

// ============================================================================
// Initialisation
// ============================================================================

export async function init(container) {
    _container = container;
    _currentCardId = null;
    _decisionData = null;

    container.innerHTML = `
        <div class="px-4 py-3">
            <!-- Search Bar -->
            <div class="page-toolbar mb-3">
                <div class="d-flex align-items-center gap-2 flex-grow-1" style="max-width:500px;">
                    <div class="input-group input-group-sm">
                        <span class="input-group-text"><i class="bi bi-search"></i></span>
                        <input type="text" id="auth-card-search" class="form-control"
                               placeholder="Enter Card ID or search by name...">
                        <button id="auth-search-btn" class="btn btn-primary">Check</button>
                    </div>
                </div>
                <button id="auth-run-btn" class="btn btn-sm btn-outline-primary" disabled>
                    <i class="bi bi-play-circle me-1"></i>Run Authenticity Check
                </button>
            </div>

            <div class="row">
                <!-- Left Column: Comparison + Check Results -->
                <div class="col-lg-8 mb-4">
                    <!-- Side-by-Side Comparison -->
                    <div class="card mb-3">
                        <div class="card-header"><h6 class="mb-0">Side-by-Side Comparison</h6></div>
                        <div class="card-body">
                            <div class="row">
                                <div class="col-6">
                                    <p class="text-muted small fw-semibold mb-2">Scanned Card</p>
                                    <div id="auth-scan-panel" class="image-panel image-panel-3x4"
                                         style="min-height:260px; background:#f8fafc; border:2px dashed #cbd5e1;
                                                border-radius:10px; display:flex; align-items:center;
                                                justify-content:center;">
                                        <div class="placeholder-content text-center text-muted">
                                            <i class="bi bi-image fs-3 d-block mb-1"></i>
                                            <small>No card selected</small>
                                        </div>
                                    </div>
                                </div>
                                <div class="col-6">
                                    <p class="text-muted small fw-semibold mb-2">Reference Image</p>
                                    <div id="auth-ref-panel" class="image-panel image-panel-3x4"
                                         style="min-height:260px; background:#f8fafc; border:2px dashed #cbd5e1;
                                                border-radius:10px; display:flex; align-items:center;
                                                justify-content:center;">
                                        <div class="placeholder-content text-center text-muted">
                                            <i class="bi bi-book fs-3 d-block mb-1"></i>
                                            <small>Reference</small>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- Check Results Table -->
                    <div class="card">
                        <div class="card-header d-flex justify-content-between align-items-center">
                            <h6 class="mb-0">Check Results</h6>
                            <span id="auth-checks-summary" class="text-muted small"></span>
                        </div>
                        <div class="card-body p-0" id="auth-checks-container">
                            ${createEmptyState('Run an authenticity check to see results.', 'bi-clipboard-check')}
                        </div>
                    </div>
                </div>

                <!-- Right Column: Verdict + Actions -->
                <div class="col-lg-4 mb-4">
                    <!-- Verdict Card -->
                    <div class="card mb-3">
                        <div class="card-header"><h6 class="mb-0">Verdict</h6></div>
                        <div class="card-body text-center" id="auth-verdict-body">
                            <!-- Status Badge -->
                            <div id="auth-status-badge" class="mb-3">
                                ${createAuthBadge('pending')}
                            </div>

                            <!-- Confidence Gauge -->
                            <div class="mb-3">
                                <div class="d-flex justify-content-between small text-muted mb-1">
                                    <span>Confidence</span>
                                    <span id="auth-confidence-label">&mdash;</span>
                                </div>
                                <div class="progress" style="height:12px; border-radius:6px;">
                                    <div id="auth-confidence-bar" class="progress-bar"
                                         role="progressbar" style="width:0%;" aria-valuenow="0"
                                         aria-valuemin="0" aria-valuemax="100">
                                    </div>
                                </div>
                            </div>

                            <!-- Stats -->
                            <div class="row text-center small mb-3">
                                <div class="col-4">
                                    <div class="fw-bold text-success" id="auth-pass-count">0</div>
                                    <div class="text-muted">Passed</div>
                                </div>
                                <div class="col-4">
                                    <div class="fw-bold text-danger" id="auth-fail-count">0</div>
                                    <div class="text-muted">Failed</div>
                                </div>
                                <div class="col-4">
                                    <div class="fw-bold text-secondary" id="auth-total-count">0</div>
                                    <div class="text-muted">Total</div>
                                </div>
                            </div>

                            <!-- Flags -->
                            <div id="auth-flags" class="text-start small mb-3" style="display:none;">
                                <p class="fw-semibold text-muted mb-1">Flags:</p>
                                <ul id="auth-flags-list" class="list-unstyled mb-0"></ul>
                            </div>

                            <!-- Override info -->
                            <div id="auth-override-info" class="text-start small mb-3" style="display:none;">
                                <div class="alert alert-info py-2 px-3 small mb-0">
                                    <i class="bi bi-person-check me-1"></i>
                                    <strong>Operator Override:</strong>
                                    <span id="auth-override-text"></span>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- Actions Card -->
                    <div class="card">
                        <div class="card-header"><h6 class="mb-0">Actions</h6></div>
                        <div class="card-body">
                            <div class="d-grid gap-2">
                                <button id="btn-confirm-authentic" class="btn btn-success btn-sm" disabled>
                                    <i class="bi bi-shield-check me-1"></i>Confirm Authentic
                                </button>
                                <button id="btn-flag-suspect" class="btn btn-warning btn-sm" disabled>
                                    <i class="bi bi-exclamation-triangle me-1"></i>Flag as Suspect
                                </button>
                                <button id="btn-reject" class="btn btn-danger btn-sm" disabled>
                                    <i class="bi bi-x-octagon me-1"></i>Reject
                                </button>
                                <button id="btn-manual-review" class="btn btn-info btn-sm" disabled>
                                    <i class="bi bi-eye me-1"></i>Escalate to Manual Review
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Override Modal -->
        <div class="modal fade" id="auth-override-modal" tabindex="-1" aria-hidden="true">
            <div class="modal-dialog">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">Override Authenticity Decision</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="mb-3">
                            <label class="form-label fw-semibold">New Status</label>
                            <select id="override-status" class="form-select">
                                <option value="authentic">Authentic</option>
                                <option value="suspect">Suspect</option>
                                <option value="reject">Reject</option>
                            </select>
                        </div>
                        <div class="mb-3">
                            <label class="form-label fw-semibold">Reason <span class="text-danger">*</span></label>
                            <textarea id="override-reason" class="form-control" rows="3"
                                      placeholder="Explain why you are overriding the automated decision..."
                                      required></textarea>
                        </div>
                        <div class="mb-3">
                            <label class="form-label fw-semibold">Operator Name <span class="text-danger">*</span></label>
                            <input type="text" id="override-operator" class="form-control"
                                   placeholder="Your name" required>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary btn-sm" data-bs-dismiss="modal">Cancel</button>
                        <button type="button" id="override-submit-btn" class="btn btn-primary btn-sm">
                            Submit Override
                        </button>
                    </div>
                </div>
            </div>
        </div>
    `;

    _bindEvents();
}

export function destroy() {
    _container = null;
    _currentCardId = null;
    _decisionData = null;
}

// ============================================================================
// Event Binding
// ============================================================================

function _bindEvents() {
    // Search / Load
    const searchInput = document.getElementById('auth-card-search');
    const searchBtn = document.getElementById('auth-search-btn');

    searchBtn.addEventListener('click', () => _loadCard(searchInput.value.trim()));
    searchInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') _loadCard(searchInput.value.trim());
    });

    // Run check
    document.getElementById('auth-run-btn').addEventListener('click', _runCheck);

    // Action buttons - all open the override modal with pre-selected status
    document.getElementById('btn-confirm-authentic').addEventListener('click', () => _openOverrideModal('authentic'));
    document.getElementById('btn-flag-suspect').addEventListener('click', () => _openOverrideModal('suspect'));
    document.getElementById('btn-reject').addEventListener('click', () => _openOverrideModal('reject'));
    document.getElementById('btn-manual-review').addEventListener('click', () => _openOverrideModal('suspect'));

    // Override submit
    document.getElementById('override-submit-btn').addEventListener('click', _submitOverride);
}

// ============================================================================
// Card Loading
// ============================================================================

async function _loadCard(cardId) {
    if (!cardId) {
        showToast('Please enter a Card ID.', 'warning');
        return;
    }

    _currentCardId = cardId;
    document.getElementById('auth-run-btn').disabled = false;

    try {
        const data = await api.get(`/authenticity/${cardId}`);
        _decisionData = data;
        _renderDecision(data);
        _enableActions(true);
    } catch (err) {
        if (err.status === 404) {
            // No decision yet - that is OK, user can run a check
            _decisionData = null;
            _resetVerdict();
            _enableActions(false);
            showToast('No authenticity decision found. Click "Run Authenticity Check" to analyze.', 'info');
        } else {
            showToast(`Error loading card: ${err.message}`, 'error');
        }
    }
}

// ============================================================================
// Run Check
// ============================================================================

async function _runCheck() {
    if (!_currentCardId) return;

    const btn = document.getElementById('auth-run-btn');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Analyzing...';

    const checksContainer = document.getElementById('auth-checks-container');
    checksContainer.innerHTML = createLoadingSpinner('Running authenticity checks...');

    try {
        const data = await api.post(`/authenticity/${_currentCardId}/run`, {});
        _decisionData = data;
        _renderDecision(data);
        _enableActions(true);
        showToast(`Authenticity check complete: ${data.overall_status}`, 'success');
    } catch (err) {
        showToast(`Authenticity check failed: ${err.message}`, 'error');
        checksContainer.innerHTML = createEmptyState('Check failed. Please try again.', 'bi-exclamation-triangle');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="bi bi-play-circle me-1"></i>Run Authenticity Check';
    }
}

// ============================================================================
// Rendering
// ============================================================================

function _renderDecision(data) {
    // Status badge
    const effectiveStatus = data.operator_override || data.overall_status;
    document.getElementById('auth-status-badge').innerHTML = `
        <div class="mb-1">${createAuthBadge(effectiveStatus)}</div>
        <div class="text-muted small">${_statusRecommendation(effectiveStatus)}</div>
    `;

    // Confidence gauge
    const pct = Math.round((data.confidence || 0) * 100);
    const barColor = _confidenceColor(pct);
    const bar = document.getElementById('auth-confidence-bar');
    bar.style.width = `${pct}%`;
    bar.className = `progress-bar ${barColor}`;
    bar.setAttribute('aria-valuenow', pct);
    document.getElementById('auth-confidence-label').textContent = `${pct}%`;

    // Pass / Fail / Total
    document.getElementById('auth-pass-count').textContent = data.checks_passed || 0;
    document.getElementById('auth-fail-count').textContent = data.checks_failed || 0;
    document.getElementById('auth-total-count').textContent = data.checks_total || 0;
    document.getElementById('auth-checks-summary').textContent =
        `${data.checks_passed || 0}/${data.checks_total || 0} passed`;

    // Flags
    const flags = data.flags || [];
    const flagsEl = document.getElementById('auth-flags');
    const flagsList = document.getElementById('auth-flags-list');
    if (flags.length > 0) {
        flagsEl.style.display = 'block';
        flagsList.innerHTML = flags.map(f =>
            `<li class="mb-1"><i class="bi bi-flag-fill text-warning me-1"></i>${_escapeHtml(f)}</li>`
        ).join('');
    } else {
        flagsEl.style.display = 'none';
    }

    // Override info
    const overrideEl = document.getElementById('auth-override-info');
    if (data.operator_override) {
        overrideEl.style.display = 'block';
        document.getElementById('auth-override-text').textContent =
            `${data.operator_override} by ${data.reviewed_by || 'unknown'} - ${data.override_reason || ''}`;
    } else {
        overrideEl.style.display = 'none';
    }

    // Render check results table
    _renderChecksTable(data.checks || []);
}

function _renderChecksTable(checks) {
    const container = document.getElementById('auth-checks-container');

    if (!checks.length) {
        container.innerHTML = createEmptyState('No check results available.', 'bi-clipboard-check');
        return;
    }

    let rows = '';
    checks.forEach((check, idx) => {
        const pct = Math.round((check.confidence || 0) * 100);
        const passIcon = check.passed
            ? '<span class="badge bg-success-subtle text-success"><i class="bi bi-check-circle me-1"></i>Pass</span>'
            : '<span class="badge bg-danger-subtle text-danger"><i class="bi bi-x-circle me-1"></i>Fail</span>';
        const barColor = _confidenceColor(pct);

        // Build details string from check.details
        let detailText = '';
        if (check.details) {
            detailText = check.details.detail || '';
            if (!detailText && typeof check.details === 'object') {
                const parts = [];
                for (const [k, v] of Object.entries(check.details)) {
                    if (v !== null && v !== undefined && k !== 'detail') {
                        parts.push(`${k}: ${v}`);
                    }
                }
                detailText = parts.join(', ');
            }
        }
        if (check.error_message) {
            detailText = `Error: ${check.error_message}`;
        }

        rows += `
            <tr class="check-row" data-idx="${idx}" style="cursor:pointer;">
                <td class="ps-3">
                    <span class="fw-semibold small">${_formatCheckType(check.check_type)}</span>
                </td>
                <td>${passIcon}</td>
                <td style="min-width:120px;">
                    <div class="d-flex align-items-center gap-2">
                        <div class="progress flex-grow-1" style="height:6px;">
                            <div class="progress-bar ${barColor}" style="width:${pct}%;"></div>
                        </div>
                        <span class="small fw-semibold" style="min-width:35px;">${pct}%</span>
                    </div>
                </td>
                <td class="small text-muted text-truncate" style="max-width:200px;"
                    title="${_escapeHtml(detailText)}">${_escapeHtml(_truncate(detailText, 60))}</td>
                <td class="pe-3 text-end">
                    <i class="bi bi-chevron-down small text-muted check-chevron"></i>
                </td>
            </tr>
            <tr class="check-detail-row" id="check-detail-${idx}" style="display:none;">
                <td colspan="5" class="ps-4 pe-3 py-2 bg-light">
                    <div class="small">
                        <strong>Full Details:</strong>
                        <pre class="mb-0 mt-1" style="white-space:pre-wrap; font-size:0.75rem;
                             max-height:200px; overflow-y:auto;">${_escapeHtml(detailText || 'No additional details')}</pre>
                        ${check.processing_time_ms ? `<div class="text-muted mt-1">Processing time: ${check.processing_time_ms}ms</div>` : ''}
                    </div>
                </td>
            </tr>
        `;
    });

    container.innerHTML = `
        <table class="table table-hover table-sm mb-0">
            <thead>
                <tr class="small text-muted">
                    <th class="ps-3">Check Name</th>
                    <th>Result</th>
                    <th>Confidence</th>
                    <th>Details</th>
                    <th class="pe-3"></th>
                </tr>
            </thead>
            <tbody>${rows}</tbody>
        </table>
    `;

    // Expand/collapse detail rows on click
    container.querySelectorAll('.check-row').forEach(row => {
        row.addEventListener('click', () => {
            const idx = row.dataset.idx;
            const detail = document.getElementById(`check-detail-${idx}`);
            const chevron = row.querySelector('.check-chevron');
            if (detail.style.display === 'none') {
                detail.style.display = '';
                chevron.className = 'bi bi-chevron-up small text-muted check-chevron';
            } else {
                detail.style.display = 'none';
                chevron.className = 'bi bi-chevron-down small text-muted check-chevron';
            }
        });
    });
}

function _resetVerdict() {
    document.getElementById('auth-status-badge').innerHTML = createAuthBadge('pending');
    document.getElementById('auth-confidence-label').textContent = '\u2014';
    const bar = document.getElementById('auth-confidence-bar');
    bar.style.width = '0%';
    bar.className = 'progress-bar bg-secondary';
    document.getElementById('auth-pass-count').textContent = '0';
    document.getElementById('auth-fail-count').textContent = '0';
    document.getElementById('auth-total-count').textContent = '0';
    document.getElementById('auth-checks-summary').textContent = '';
    document.getElementById('auth-flags').style.display = 'none';
    document.getElementById('auth-override-info').style.display = 'none';
    document.getElementById('auth-checks-container').innerHTML =
        createEmptyState('Run an authenticity check to see results.', 'bi-clipboard-check');
}

// ============================================================================
// Override Modal
// ============================================================================

function _openOverrideModal(preselect) {
    document.getElementById('override-status').value = preselect;
    document.getElementById('override-reason').value = '';
    document.getElementById('override-operator').value = '';

    const modal = new bootstrap.Modal(document.getElementById('auth-override-modal'));
    modal.show();
}

async function _submitOverride() {
    const status = document.getElementById('override-status').value;
    const reason = document.getElementById('override-reason').value.trim();
    const operator = document.getElementById('override-operator').value.trim();

    if (!reason) {
        showToast('Please provide a reason for the override.', 'warning');
        return;
    }
    if (!operator) {
        showToast('Please enter your name.', 'warning');
        return;
    }

    try {
        await api.post(`/authenticity/${_currentCardId}/override`, {
            status,
            reason,
            operator,
        });

        // Close modal
        const modalEl = document.getElementById('auth-override-modal');
        const modal = bootstrap.Modal.getInstance(modalEl);
        if (modal) modal.hide();

        // Reload data
        showToast(`Decision overridden to "${status}".`, 'success');
        await _loadCard(_currentCardId);
    } catch (err) {
        showToast(`Override failed: ${err.message}`, 'error');
    }
}

// ============================================================================
// Helpers
// ============================================================================

function _enableActions(enabled) {
    document.getElementById('btn-confirm-authentic').disabled = !enabled;
    document.getElementById('btn-flag-suspect').disabled = !enabled;
    document.getElementById('btn-reject').disabled = !enabled;
    document.getElementById('btn-manual-review').disabled = !enabled;
}

function _confidenceColor(pct) {
    if (pct >= 85) return 'bg-success';
    if (pct >= 70) return 'bg-warning';
    if (pct >= 50) return 'bg-orange';
    return 'bg-danger';
}

function _statusRecommendation(status) {
    const map = {
        authentic: 'Card passes all authenticity checks.',
        suspect: 'Minor concerns detected. Review recommended.',
        reject: 'Significant failures. Do not grade.',
        manual_review: 'Manual inspection required.',
        pending: 'No check has been run yet.',
    };
    return map[status] || '';
}

function _formatCheckType(type) {
    // "text_card_name" -> "Text: Card Name"
    if (!type) return 'Unknown';
    const parts = type.split('_');
    if (parts.length < 2) return type;
    const category = parts[0].charAt(0).toUpperCase() + parts[0].slice(1);
    const name = parts.slice(1).map(p => p.charAt(0).toUpperCase() + p.slice(1)).join(' ');
    return `${category}: ${name}`;
}

function _truncate(str, max) {
    if (!str) return '';
    return str.length > max ? str.substring(0, max) + '...' : str;
}

function _escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}
