/**
 * Audit Log page module.
 *
 * Displays a chronological log of all system events with filtering,
 * expandable row detail, pagination, CSV export, and auto-refresh.
 */
import { api } from '../api.js';
import { createEmptyState, createLoadingSpinner, formatDate, showToast } from '../components.js';

let _container = null;
let _autoRefreshTimer = null;
let _autoRefreshEnabled = false;

/** Current filter / pagination state. */
let _state = {
    eventType: '',
    entityType: '',
    operator: '',
    dateStart: '',
    dateEnd: '',
    limit: 25,
    offset: 0,
    total: 0,
};

// ------------------------------------------------------------------
// Badge colour mapping for event types
// ------------------------------------------------------------------

const EVENT_BADGE_COLORS = {
    'grade.approved':       'primary',
    'grade.overridden':     'primary',
    'grade.calculated':     'primary',
    'auth.decided':         'purple',
    'auth.overridden':      'purple',
    'auth.completed':       'purple',
    'auth.flagged':         'purple',
    'settings.changed':     'warning',
    'scan.started':         'info',
    'scan.completed':       'info',
    'card.created':         'secondary',
    'reference.approved':   'secondary',
    'calibration.run':      'dark',
};

function badgeColor(eventType) {
    // Try exact match first, then prefix match
    if (EVENT_BADGE_COLORS[eventType]) return EVENT_BADGE_COLORS[eventType];
    const prefix = (eventType || '').split('.')[0];
    const map = { grade: 'primary', auth: 'purple', settings: 'warning', scan: 'info' };
    return map[prefix] || 'secondary';
}

// ------------------------------------------------------------------
// Lifecycle
// ------------------------------------------------------------------

export async function init(container) {
    _container = container;
    _state = { eventType: '', entityType: '', operator: '', dateStart: '', dateEnd: '', limit: 25, offset: 0, total: 0 };
    container.innerHTML = buildLayout();
    await loadFilterOptions();
    bindEvents();
    await loadEvents();
}

export function destroy() {
    stopAutoRefresh();
    _container = null;
}

// ------------------------------------------------------------------
// Layout
// ------------------------------------------------------------------

function buildLayout() {
    return `
        <div class="px-4 py-3">
            <div class="card">
                <div class="card-header d-flex justify-content-between align-items-center flex-wrap gap-2">
                    <h6 class="mb-0"><i class="bi bi-journal-text me-2"></i>Audit Log</h6>
                    <div class="d-flex gap-2 flex-wrap align-items-center">
                        <select id="audit-event-type" class="form-select form-select-sm" style="width:auto;">
                            <option value="">All Event Types</option>
                        </select>
                        <select id="audit-entity-type" class="form-select form-select-sm" style="width:auto;">
                            <option value="">All Entities</option>
                            <option value="card">Card</option>
                            <option value="scan">Scan</option>
                            <option value="grade">Grade</option>
                            <option value="authenticity">Authenticity</option>
                            <option value="settings">Settings</option>
                            <option value="reference">Reference</option>
                        </select>
                        <input type="text" id="audit-operator" class="form-control form-control-sm" style="width:130px;" placeholder="Operator...">
                        <input type="date" id="audit-date-start" class="form-control form-control-sm" style="width:140px;">
                        <input type="date" id="audit-date-end" class="form-control form-control-sm" style="width:140px;">
                        <button id="btn-audit-apply" class="btn btn-sm btn-primary">
                            <i class="bi bi-funnel me-1"></i>Apply
                        </button>
                        <button id="btn-audit-export" class="btn btn-sm btn-outline-secondary">
                            <i class="bi bi-download me-1"></i>Export CSV
                        </button>
                        <div class="form-check form-switch ms-2">
                            <input class="form-check-input" type="checkbox" id="audit-auto-refresh">
                            <label class="form-check-label small" for="audit-auto-refresh">Auto</label>
                        </div>
                    </div>
                </div>
                <div class="card-body p-0" id="audit-table-body">
                    ${createLoadingSpinner('Loading audit events...')}
                </div>
                <div class="card-footer bg-white d-flex justify-content-between align-items-center">
                    <small class="text-muted" id="audit-showing">Showing 0 entries</small>
                    <nav>
                        <ul class="pagination pagination-sm mb-0" id="audit-pagination"></ul>
                    </nav>
                </div>
            </div>
        </div>

        <!-- Detail modal -->
        <div class="modal fade" id="audit-detail-modal" tabindex="-1">
            <div class="modal-dialog modal-lg">
                <div class="modal-content">
                    <div class="modal-header">
                        <h6 class="modal-title">Event Detail</h6>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body" id="audit-detail-content"></div>
                </div>
            </div>
        </div>
    `;
}

// ------------------------------------------------------------------
// Filter options
// ------------------------------------------------------------------

async function loadFilterOptions() {
    try {
        const [typesRes, opsRes] = await Promise.all([
            api.get('/audit/event-types'),
            api.get('/audit/operators'),
        ]);

        const typeSelect = _container.querySelector('#audit-event-type');
        (typesRes.event_types || []).forEach(t => {
            const opt = document.createElement('option');
            opt.value = t;
            opt.textContent = t;
            typeSelect.appendChild(opt);
        });

        const opInput = _container.querySelector('#audit-operator');
        // Store operators for potential autocomplete (kept simple for now)
        _container._operators = opsRes.operators || [];
    } catch (err) {
        console.warn('Could not load filter options:', err);
    }
}

// ------------------------------------------------------------------
// Event binding
// ------------------------------------------------------------------

function bindEvents() {
    _container.querySelector('#btn-audit-apply')?.addEventListener('click', () => {
        readFilters();
        _state.offset = 0;
        loadEvents();
    });

    _container.querySelector('#btn-audit-export')?.addEventListener('click', exportCsv);

    _container.querySelector('#audit-auto-refresh')?.addEventListener('change', (e) => {
        _autoRefreshEnabled = e.target.checked;
        if (_autoRefreshEnabled) startAutoRefresh();
        else stopAutoRefresh();
    });
}

function readFilters() {
    _state.eventType = _container.querySelector('#audit-event-type')?.value || '';
    _state.entityType = _container.querySelector('#audit-entity-type')?.value || '';
    _state.operator = _container.querySelector('#audit-operator')?.value || '';
    _state.dateStart = _container.querySelector('#audit-date-start')?.value || '';
    _state.dateEnd = _container.querySelector('#audit-date-end')?.value || '';
}

// ------------------------------------------------------------------
// Auto-refresh
// ------------------------------------------------------------------

function startAutoRefresh() {
    stopAutoRefresh();
    _autoRefreshTimer = setInterval(() => {
        if (_container) loadEvents();
    }, 30000);
}

function stopAutoRefresh() {
    if (_autoRefreshTimer) { clearInterval(_autoRefreshTimer); _autoRefreshTimer = null; }
}

// ------------------------------------------------------------------
// Load events
// ------------------------------------------------------------------

async function loadEvents() {
    if (!_container) return;
    const params = new URLSearchParams();
    if (_state.eventType)  params.set('event_type', _state.eventType);
    if (_state.entityType) params.set('entity_type', _state.entityType);
    if (_state.operator)   params.set('operator', _state.operator);
    if (_state.dateStart)  params.set('date_start', _state.dateStart);
    if (_state.dateEnd)    params.set('date_end', _state.dateEnd);
    params.set('limit', _state.limit);
    params.set('offset', _state.offset);

    try {
        const data = await api.get('/audit/events?' + params.toString());
        _state.total = data.total || 0;
        renderTable(data.events || []);
        renderPagination();
        updateShowing();
    } catch (err) {
        console.error('Audit load error:', err);
        const body = _container.querySelector('#audit-table-body');
        if (body) body.innerHTML = createEmptyState('Failed to load audit events.', 'bi-exclamation-triangle');
    }
}

// ------------------------------------------------------------------
// Render table
// ------------------------------------------------------------------

function renderTable(events) {
    const body = _container.querySelector('#audit-table-body');
    if (!body) return;

    if (!events.length) {
        body.innerHTML = `
            <div class="table-responsive">
                <table class="table table-hover table-striped mb-0">
                    <thead class="table-light">
                        <tr>
                            <th style="width:170px;">Timestamp</th>
                            <th>Event Type</th>
                            <th>Entity</th>
                            <th>Operator</th>
                            <th>Details</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr><td colspan="5">${createEmptyState('No audit log entries match the current filters.', 'bi-journal-text')}</td></tr>
                    </tbody>
                </table>
            </div>`;
        return;
    }

    const rows = events.map(e => {
        const color = badgeColor(e.event_type);
        const bgClass = color === 'purple' ? 'text-bg-purple' : `bg-${color}`;
        const detailStr = e.details ? truncate(JSON.stringify(e.details), 80) : '';
        const entityLink = e.entity_id
            ? `<span class="text-primary" style="cursor:pointer;" data-entity-type="${e.entity_type || ''}" data-entity-id="${e.entity_id}">${e.entity_type || ''}/${shortId(e.entity_id)}</span>`
            : (e.entity_type || '--');

        return `
            <tr class="audit-row" data-event-id="${e.id}" style="cursor:pointer;">
                <td class="small">${formatDate(e.created_at)}</td>
                <td><span class="badge ${bgClass}">${e.event_type}</span></td>
                <td class="small">${entityLink}</td>
                <td class="small">${e.operator || '--'}</td>
                <td class="small text-muted">${escapeHtml(detailStr)}</td>
            </tr>`;
    }).join('');

    body.innerHTML = `
        <div class="table-responsive">
            <table class="table table-hover table-striped mb-0">
                <thead class="table-light">
                    <tr>
                        <th style="width:170px;">Timestamp</th>
                        <th>Event Type</th>
                        <th>Entity</th>
                        <th>Operator</th>
                        <th>Details</th>
                    </tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>
        </div>`;

    // Style for custom purple badge
    addPurpleStyle();

    // Bind row click for detail modal
    body.querySelectorAll('.audit-row').forEach(row => {
        row.addEventListener('click', () => showDetail(row.dataset.eventId));
    });
}

// ------------------------------------------------------------------
// Detail modal
// ------------------------------------------------------------------

async function showDetail(eventId) {
    const contentEl = _container.querySelector('#audit-detail-content');
    if (!contentEl) return;
    contentEl.innerHTML = createLoadingSpinner('Loading event detail...');

    // Open modal
    const modalEl = _container.querySelector('#audit-detail-modal');
    const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
    modal.show();

    try {
        const e = await api.get(`/audit/events/${eventId}`);
        contentEl.innerHTML = `
            <div class="row mb-3">
                <div class="col-sm-6"><strong>Event Type:</strong> <span class="badge bg-${badgeColor(e.event_type)}">${e.event_type}</span></div>
                <div class="col-sm-6"><strong>Timestamp:</strong> ${formatDate(e.created_at)}</div>
            </div>
            <div class="row mb-3">
                <div class="col-sm-6"><strong>Entity:</strong> ${e.entity_type || '--'} / ${e.entity_id || '--'}</div>
                <div class="col-sm-6"><strong>Operator:</strong> ${e.operator || '--'}</div>
            </div>
            <div class="mb-3"><strong>Action:</strong> ${escapeHtml(e.action || '')}</div>
            ${e.details ? `
                <div class="mb-3">
                    <strong>Details:</strong>
                    <pre class="bg-light p-2 rounded mt-1" style="max-height:200px; overflow:auto;">${escapeHtml(JSON.stringify(e.details, null, 2))}</pre>
                </div>` : ''}
            ${e.before_state || e.after_state ? `
                <div class="row">
                    <div class="col-md-6">
                        <strong>Before State:</strong>
                        <pre class="bg-light p-2 rounded mt-1 border-start border-danger border-3" style="max-height:250px; overflow:auto; font-size:0.8rem;">${e.before_state ? escapeHtml(JSON.stringify(e.before_state, null, 2)) : '<em class="text-muted">N/A</em>'}</pre>
                    </div>
                    <div class="col-md-6">
                        <strong>After State:</strong>
                        <pre class="bg-light p-2 rounded mt-1 border-start border-success border-3" style="max-height:250px; overflow:auto; font-size:0.8rem;">${e.after_state ? escapeHtml(JSON.stringify(e.after_state, null, 2)) : '<em class="text-muted">N/A</em>'}</pre>
                    </div>
                </div>` : ''}
        `;
    } catch (err) {
        contentEl.innerHTML = `<p class="text-danger">Failed to load event detail: ${escapeHtml(err.message)}</p>`;
    }
}

// ------------------------------------------------------------------
// Pagination
// ------------------------------------------------------------------

function renderPagination() {
    const nav = _container.querySelector('#audit-pagination');
    if (!nav) return;

    const totalPages = Math.max(1, Math.ceil(_state.total / _state.limit));
    const currentPage = Math.floor(_state.offset / _state.limit) + 1;

    let html = '';
    // Previous
    html += `<li class="page-item ${currentPage <= 1 ? 'disabled' : ''}">
        <a class="page-link" href="#" data-page="${currentPage - 1}">Previous</a></li>`;

    // Page numbers (show max 7)
    const start = Math.max(1, currentPage - 3);
    const end = Math.min(totalPages, start + 6);
    for (let i = start; i <= end; i++) {
        html += `<li class="page-item ${i === currentPage ? 'active' : ''}">
            <a class="page-link" href="#" data-page="${i}">${i}</a></li>`;
    }

    // Next
    html += `<li class="page-item ${currentPage >= totalPages ? 'disabled' : ''}">
        <a class="page-link" href="#" data-page="${currentPage + 1}">Next</a></li>`;

    nav.innerHTML = html;

    nav.querySelectorAll('.page-link').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const page = parseInt(link.dataset.page, 10);
            if (page >= 1 && page <= totalPages) {
                _state.offset = (page - 1) * _state.limit;
                loadEvents();
            }
        });
    });
}

function updateShowing() {
    const el = _container.querySelector('#audit-showing');
    if (!el) return;
    const from = _state.total === 0 ? 0 : _state.offset + 1;
    const to = Math.min(_state.offset + _state.limit, _state.total);
    el.textContent = `Showing ${from}-${to} of ${_state.total} entries`;
}

// ------------------------------------------------------------------
// CSV Export
// ------------------------------------------------------------------

async function exportCsv() {
    readFilters();
    try {
        const body = {
            event_type: _state.eventType || null,
            entity_type: _state.entityType || null,
            operator: _state.operator || null,
            date_start: _state.dateStart || null,
            date_end: _state.dateEnd || null,
        };

        const response = await fetch('/api/audit/export', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });

        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'audit_events.csv';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        showToast('CSV exported successfully', 'success');
    } catch (err) {
        console.error('Export error:', err);
        showToast('Failed to export CSV: ' + err.message, 'error');
    }
}

// ------------------------------------------------------------------
// Helpers
// ------------------------------------------------------------------

function truncate(str, max) {
    if (!str) return '';
    return str.length > max ? str.substring(0, max) + '...' : str;
}

function shortId(id) {
    if (!id) return '';
    return id.length > 8 ? id.substring(0, 8) + '...' : id;
}

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

/** Inject a one-time style for .text-bg-purple badge. */
let _purpleStyleAdded = false;
function addPurpleStyle() {
    if (_purpleStyleAdded) return;
    _purpleStyleAdded = true;
    const style = document.createElement('style');
    style.textContent = `.text-bg-purple { background-color: #6f42c1 !important; color: #fff !important; }`;
    document.head.appendChild(style);
}
