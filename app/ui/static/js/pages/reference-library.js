/**
 * Reference Library page module.
 *
 * Browse and manage the card reference database used for authenticity
 * comparison and identification.  Supports search, filtering, approval
 * workflow, PokeWallet sync, add-from-scan, and visual comparison tools.
 */
import { api } from '../api.js';
import {
    createEmptyState,
    createLoadingSpinner,
    createStatusBadge,
    showToast,
    formatDate,
    escapeHtml,
} from '../components.js';

/* ------------------------------------------------------------------ state */
let _state = {
    cards: [],
    total: 0,
    page: 1,
    perPage: 24,
    totalPages: 1,
    search: '',
    language: '',
    setCode: '',
    status: '',
    sets: [],
    syncStatus: null,
};

let _container = null;
let _pollTimer = null;

/* ================================================================ init */
export async function init(container) {
    _container = container;
    _render();
    _bindEvents();
    await _loadSets();
    await _loadCards();
    _startSyncPoll();
    // Register cleanup so interval is cleared even if destroy() is not called
    window._pageCleanup.push(() => { if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; } });
}

export function destroy() {
    if (_pollTimer) {
        clearInterval(_pollTimer);
        _pollTimer = null;
    }
    _container = null;
}

/* ============================================================== render */
function _render() {
    _container.innerHTML = `
        <div class="px-4 py-3">
            <!-- Sync Panel -->
            <div class="card mb-3" id="ref-sync-panel">
                <div class="card-header d-flex justify-content-between align-items-center">
                    <h6 class="mb-0"><i class="bi bi-cloud-download me-2"></i>PokeWallet Sync</h6>
                    <div class="d-flex gap-2 align-items-center">
                        <div id="ref-sync-status-badge"></div>
                        <div class="input-group input-group-sm" style="width:220px;">
                            <input type="text" class="form-control" id="ref-sync-set-input"
                                   placeholder="Set code (e.g. sv1)">
                            <button class="btn btn-primary" id="ref-sync-btn">
                                <i class="bi bi-arrow-repeat me-1"></i>Sync
                            </button>
                        </div>
                    </div>
                </div>
                <div class="card-body py-2 d-none" id="ref-sync-progress-body">
                    <div class="d-flex align-items-center gap-3">
                        <div class="progress flex-grow-1" style="height:8px;">
                            <div class="progress-bar" id="ref-sync-progress-bar"
                                 role="progressbar" style="width:0%"></div>
                        </div>
                        <small class="text-muted" id="ref-sync-progress-text">0%</small>
                    </div>
                </div>
                <div class="card-footer py-2 bg-transparent border-0">
                    <small class="text-muted" id="ref-sync-library-stats"></small>
                </div>
            </div>

            <!-- Main Library Card -->
            <div class="card">
                <div class="card-header d-flex justify-content-between align-items-center flex-wrap gap-2">
                    <h6 class="mb-0"><i class="bi bi-book me-2"></i>Reference Library</h6>
                    <div class="d-flex gap-2 align-items-center flex-wrap">
                        <div class="input-group input-group-sm" style="width:260px;">
                            <span class="input-group-text"><i class="bi bi-search"></i></span>
                            <input type="text" class="form-control" id="ref-search-input"
                                   placeholder="Search cards, sets, series...">
                        </div>
                        <select class="form-select form-select-sm" style="width:auto;" id="ref-filter-status">
                            <option value="">All Statuses</option>
                            <option value="pending">Pending</option>
                            <option value="approved">Approved</option>
                            <option value="rejected">Rejected</option>
                        </select>
                        <select class="form-select form-select-sm" style="width:auto;" id="ref-filter-language">
                            <option value="">All Languages</option>
                            <option value="en">English</option>
                            <option value="ja">Japanese</option>
                            <option value="ko">Korean</option>
                            <option value="zh">Chinese</option>
                            <option value="fr">French</option>
                            <option value="de">German</option>
                            <option value="es">Spanish</option>
                            <option value="it">Italian</option>
                            <option value="pt">Portuguese</option>
                        </select>
                        <select class="form-select form-select-sm" style="width:auto;" id="ref-filter-set">
                            <option value="">All Sets</option>
                        </select>
                        <button class="btn btn-sm btn-outline-primary" id="ref-add-from-scan-btn">
                            <i class="bi bi-plus-lg me-1"></i>Add from Scan
                        </button>
                        <button class="btn btn-sm btn-outline-secondary" id="ref-compare-btn">
                            <i class="bi bi-arrows-angle-expand me-1"></i>Compare Tool
                        </button>
                    </div>
                </div>
                <div class="card-body" id="ref-grid-body">
                    ${createLoadingSpinner('Loading reference cards...')}
                </div>
                <div class="card-footer d-flex justify-content-between align-items-center" id="ref-pagination-footer">
                </div>
            </div>
        </div>

        <!-- Card Detail Modal -->
        <div class="modal fade" id="ref-detail-modal" tabindex="-1">
            <div class="modal-dialog modal-lg modal-dialog-centered">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title" id="ref-detail-title">Card Details</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body" id="ref-detail-body">
                        ${createLoadingSpinner()}
                    </div>
                    <div class="modal-footer" id="ref-detail-footer"></div>
                </div>
            </div>
        </div>

        <!-- Add from Scan Modal -->
        <div class="modal fade" id="ref-add-scan-modal" tabindex="-1">
            <div class="modal-dialog modal-dialog-centered">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">Add Reference from Scan</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="mb-3">
                            <label class="form-label">Card Record ID</label>
                            <input type="text" class="form-control" id="ref-scan-card-id"
                                   placeholder="Enter the graded card record ID">
                        </div>
                        <div class="mb-3">
                            <label class="form-label">Operator</label>
                            <input type="text" class="form-control" id="ref-scan-operator"
                                   value="operator" placeholder="Operator name">
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                        <button type="button" class="btn btn-primary" id="ref-scan-submit-btn">
                            <i class="bi bi-plus-lg me-1"></i>Add as Reference
                        </button>
                    </div>
                </div>
            </div>
        </div>

        <!-- Compare Tool Modal -->
        <div class="modal fade" id="ref-compare-modal" tabindex="-1">
            <div class="modal-dialog modal-xl modal-dialog-centered">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">Visual Comparison Tool</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="row mb-3">
                            <div class="col-md-6">
                                <label class="form-label">Scan Image Path</label>
                                <input type="text" class="form-control" id="ref-compare-scan-path"
                                       placeholder="Path to scanned image">
                            </div>
                            <div class="col-md-6">
                                <label class="form-label">Reference Card ID</label>
                                <input type="text" class="form-control" id="ref-compare-ref-id"
                                       placeholder="Reference card ID to compare against">
                            </div>
                        </div>
                        <div class="text-center mb-3">
                            <button class="btn btn-primary" id="ref-compare-run-btn">
                                <i class="bi bi-play-fill me-1"></i>Run Comparison
                            </button>
                        </div>
                        <div id="ref-compare-results" class="d-none">
                            <hr>
                            <div class="row">
                                <div class="col-md-4 text-center" id="ref-compare-scan-preview">
                                    <h6 class="text-muted mb-2">Scan</h6>
                                </div>
                                <div class="col-md-4 text-center" id="ref-compare-heatmap-preview">
                                    <h6 class="text-muted mb-2">Difference Heat Map</h6>
                                </div>
                                <div class="col-md-4 text-center" id="ref-compare-ref-preview">
                                    <h6 class="text-muted mb-2">Reference</h6>
                                </div>
                            </div>
                            <div class="row mt-3" id="ref-compare-scores"></div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `;
}

/* ========================================================== data loading */
async function _loadCards() {
    const body = document.getElementById('ref-grid-body');
    if (!body) return;
    body.innerHTML = createLoadingSpinner('Loading reference cards...');

    try {
        const params = new URLSearchParams();
        if (_state.search)   params.set('search', _state.search);
        if (_state.language)  params.set('language', _state.language);
        if (_state.setCode)   params.set('set_code', _state.setCode);
        if (_state.status)    params.set('status', _state.status);
        params.set('page', _state.page);
        params.set('per_page', _state.perPage);

        const data = await api.get(`/reference/cards?${params}`);
        _state.cards = data.cards || [];
        _state.total = data.total || 0;
        _state.totalPages = data.total_pages || 1;

        _renderGrid();
        _renderPagination();
    } catch (err) {
        body.innerHTML = createEmptyState(
            `Failed to load reference cards: ${err.message}`, 'bi-exclamation-triangle'
        );
    }
}

async function _loadSets() {
    try {
        const data = await api.get('/reference/sets');
        _state.sets = data.sets || [];
        _populateSetDropdown();
    } catch {
        // Non-critical — dropdown stays at "All Sets"
    }
}

function _populateSetDropdown() {
    const sel = document.getElementById('ref-filter-set');
    if (!sel) return;
    // Keep the "All Sets" option, append fetched sets
    _state.sets.forEach(s => {
        const opt = document.createElement('option');
        opt.value = s.code;
        opt.textContent = `${s.code} — ${s.name}`;
        sel.appendChild(opt);
    });
}

/* ============================================================ grid render */
function _renderGrid() {
    const body = document.getElementById('ref-grid-body');
    if (!body) return;

    if (_state.cards.length === 0) {
        body.innerHTML = createEmptyState(
            'No reference cards found. Sync a set or add references from scans.', 'bi-book'
        );
        return;
    }

    const cardsHtml = _state.cards.map(card => {
        const thumb = _thumbnailUrl(card);
        const statusBadge = createStatusBadge(card.status);
        return `
            <div class="col-xl-2 col-lg-3 col-md-4 col-sm-6 mb-3">
                <div class="card h-100 ref-card-tile" role="button" data-card-id="${card.id}">
                    <div class="card-img-top bg-light d-flex align-items-center justify-content-center"
                         style="height:180px; overflow:hidden;">
                        ${thumb
                            ? `<img src="${thumb}" alt="${escapeHtml(card.card_name)}" class="img-fluid" style="max-height:180px; object-fit:contain;">`
                            : `<i class="bi bi-image text-muted fs-1"></i>`
                        }
                    </div>
                    <div class="card-body p-2">
                        <p class="card-title mb-1 small fw-semibold text-truncate" title="${escapeHtml(card.card_name)}">
                            ${escapeHtml(card.card_name)}
                        </p>
                        <p class="mb-1 text-muted" style="font-size:0.75rem;">
                            ${escapeHtml(card.set_code || '')} ${card.collector_number ? '#' + escapeHtml(card.collector_number) : ''}
                        </p>
                        <div class="d-flex justify-content-between align-items-center">
                            ${statusBadge}
                            ${card.status === 'pending' ? `
                                <div class="btn-group btn-group-sm">
                                    <button class="btn btn-outline-success btn-approve-inline py-0 px-1"
                                            data-card-id="${card.id}" title="Approve">
                                        <i class="bi bi-check-lg"></i>
                                    </button>
                                    <button class="btn btn-outline-danger btn-reject-inline py-0 px-1"
                                            data-card-id="${card.id}" title="Reject">
                                        <i class="bi bi-x-lg"></i>
                                    </button>
                                </div>
                            ` : ''}
                        </div>
                    </div>
                </div>
            </div>
        `;
    }).join('');

    body.innerHTML = `<div class="row">${cardsHtml}</div>`;
}

function _thumbnailUrl(card) {
    if (card.images && card.images.length > 0) {
        const frontImg = card.images.find(i => i.side === 'front') || card.images[0];
        if (frontImg && frontImg.image_path) {
            // image_path is an absolute filesystem path; convert to the /data/ served route
            const dataIdx = frontImg.image_path.replace(/\\/g, '/').indexOf('data/');
            if (dataIdx >= 0) {
                return '/' + frontImg.image_path.replace(/\\/g, '/').substring(dataIdx);
            }
        }
    }
    return null;
}

/* ======================================================== pagination */
function _renderPagination() {
    const footer = document.getElementById('ref-pagination-footer');
    if (!footer) return;

    const start = Math.min((_state.page - 1) * _state.perPage + 1, _state.total);
    const end   = Math.min(_state.page * _state.perPage, _state.total);

    footer.innerHTML = `
        <small class="text-muted">
            Showing ${start}\u2013${end} of ${_state.total} reference cards
        </small>
        <nav>
            <ul class="pagination pagination-sm mb-0">
                <li class="page-item ${_state.page <= 1 ? 'disabled' : ''}">
                    <a class="page-link" href="#" id="ref-page-prev">&laquo; Prev</a>
                </li>
                <li class="page-item disabled">
                    <span class="page-link">${_state.page} / ${_state.totalPages}</span>
                </li>
                <li class="page-item ${_state.page >= _state.totalPages ? 'disabled' : ''}">
                    <a class="page-link" href="#" id="ref-page-next">Next &raquo;</a>
                </li>
            </ul>
        </nav>
    `;
}

/* ========================================================= event binding */
function _bindEvents() {
    // Debounced search
    let searchTimer = null;
    _container.addEventListener('input', e => {
        if (e.target.id === 'ref-search-input') {
            clearTimeout(searchTimer);
            searchTimer = setTimeout(() => {
                _state.search = e.target.value.trim();
                _state.page = 1;
                _loadCards();
            }, 400);
        }
    });

    _container.addEventListener('change', e => {
        if (e.target.id === 'ref-filter-status') {
            _state.status = e.target.value;
            _state.page = 1;
            _loadCards();
        }
        if (e.target.id === 'ref-filter-language') {
            _state.language = e.target.value;
            _state.page = 1;
            _loadCards();
        }
        if (e.target.id === 'ref-filter-set') {
            _state.setCode = e.target.value;
            _state.page = 1;
            _loadCards();
        }
    });

    _container.addEventListener('click', e => {
        const target = e.target.closest('[data-card-id]');

        // Inline approve / reject (stop propagation so tile click doesn't fire)
        const approveBtn = e.target.closest('.btn-approve-inline');
        if (approveBtn) {
            e.stopPropagation();
            _approveCard(approveBtn.dataset.cardId);
            return;
        }
        const rejectBtn = e.target.closest('.btn-reject-inline');
        if (rejectBtn) {
            e.stopPropagation();
            _rejectCard(rejectBtn.dataset.cardId);
            return;
        }

        // Tile click -> detail modal
        const tile = e.target.closest('.ref-card-tile');
        if (tile) {
            _openDetailModal(tile.dataset.cardId);
            return;
        }

        // Pagination
        if (e.target.id === 'ref-page-prev' || e.target.closest('#ref-page-prev')) {
            e.preventDefault();
            if (_state.page > 1) { _state.page--; _loadCards(); }
            return;
        }
        if (e.target.id === 'ref-page-next' || e.target.closest('#ref-page-next')) {
            e.preventDefault();
            if (_state.page < _state.totalPages) { _state.page++; _loadCards(); }
            return;
        }

        // Sync button
        if (e.target.id === 'ref-sync-btn' || e.target.closest('#ref-sync-btn')) {
            _triggerSync();
            return;
        }

        // Add from scan button
        if (e.target.id === 'ref-add-from-scan-btn' || e.target.closest('#ref-add-from-scan-btn')) {
            _openAddScanModal();
            return;
        }

        // Add from scan submit
        if (e.target.id === 'ref-scan-submit-btn' || e.target.closest('#ref-scan-submit-btn')) {
            _submitAddFromScan();
            return;
        }

        // Compare tool button
        if (e.target.id === 'ref-compare-btn' || e.target.closest('#ref-compare-btn')) {
            _openCompareModal();
            return;
        }

        // Compare run
        if (e.target.id === 'ref-compare-run-btn' || e.target.closest('#ref-compare-run-btn')) {
            _runComparison();
            return;
        }

        // Detail modal approve/reject
        if (e.target.id === 'ref-detail-approve' || e.target.closest('#ref-detail-approve')) {
            const id = document.getElementById('ref-detail-modal')?.dataset?.cardId;
            if (id) _approveCard(id, true);
            return;
        }
        if (e.target.id === 'ref-detail-reject' || e.target.closest('#ref-detail-reject')) {
            const id = document.getElementById('ref-detail-modal')?.dataset?.cardId;
            if (id) _rejectCard(id, true);
            return;
        }
    });
}

/* ========================================================= sync helpers */
async function _triggerSync() {
    const input = document.getElementById('ref-sync-set-input');
    const setCode = input?.value?.trim();
    if (!setCode) {
        showToast('Enter a set code to sync.', 'warning');
        return;
    }

    try {
        await api.post('/reference/sync/set', { set_code: setCode });
        showToast(`Sync started for set "${setCode}".`, 'info');
        _showSyncProgress(true);
    } catch (err) {
        showToast(`Sync failed: ${err.message}`, 'error');
    }
}

function _startSyncPoll() {
    _pollSyncStatus();
    _pollTimer = setInterval(_pollSyncStatus, 3000);
}

async function _pollSyncStatus() {
    try {
        const data = await api.get('/reference/sync/status');
        _state.syncStatus = data;

        // Library stats
        const statsEl = document.getElementById('ref-sync-library-stats');
        if (statsEl && data.library) {
            const l = data.library;
            statsEl.textContent =
                `Library: ${l.total_cards} cards (${l.approved_cards} approved, ${l.pending_cards} pending) \u2022 ${l.total_images} images`;
        }

        // Progress bar
        const sync = data.current_sync || {};
        if (sync.is_running) {
            _showSyncProgress(true);
            const bar = document.getElementById('ref-sync-progress-bar');
            const text = document.getElementById('ref-sync-progress-text');
            if (bar) bar.style.width = sync.pct_complete + '%';
            if (text) text.textContent = `${sync.pct_complete}% \u2014 ${sync.synced_cards} synced, ${sync.skipped_cards} skipped`;
        } else if (_state.syncStatus?._wasRunning) {
            _showSyncProgress(false);
            // Reload cards after sync completes
            await _loadCards();
        }
        // Track whether sync *was* running so we know when it stops
        if (_state.syncStatus) {
            _state.syncStatus._wasRunning = sync.is_running;
        }
    } catch {
        // Polling failure is non-critical
    }
}

function _showSyncProgress(show) {
    const el = document.getElementById('ref-sync-progress-body');
    if (el) {
        el.classList.toggle('d-none', !show);
    }
}

/* ======================================================= approval actions */
async function _approveCard(cardId, closeModal = false) {
    try {
        await api.post(`/reference/cards/${cardId}/approve?operator=operator`);
        showToast('Reference card approved.', 'success');
        if (closeModal) _closeModal('ref-detail-modal');
        await _loadCards();
    } catch (err) {
        showToast(`Approve failed: ${err.message}`, 'error');
    }
}

async function _rejectCard(cardId, closeModal = false) {
    try {
        await api.post(`/reference/cards/${cardId}/reject?operator=operator`);
        showToast('Reference card rejected.', 'warning');
        if (closeModal) _closeModal('ref-detail-modal');
        await _loadCards();
    } catch (err) {
        showToast(`Reject failed: ${err.message}`, 'error');
    }
}

/* ======================================================== detail modal */
async function _openDetailModal(cardId) {
    const modalEl = document.getElementById('ref-detail-modal');
    if (!modalEl) return;
    modalEl.dataset.cardId = cardId;

    const body  = document.getElementById('ref-detail-body');
    const title = document.getElementById('ref-detail-title');
    const footer = document.getElementById('ref-detail-footer');

    body.innerHTML = createLoadingSpinner();
    footer.innerHTML = '';
    title.textContent = 'Card Details';

    /* global bootstrap */
    const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
    modal.show();

    try {
        const card = await api.get(`/reference/cards/${cardId}`);
        title.textContent = card.card_name || 'Card Details';

        const images = card.images || [];
        const frontImg = images.find(i => i.side === 'front');
        const backImg  = images.find(i => i.side === 'back');

        body.innerHTML = `
            <div class="row">
                <div class="col-md-6 text-center mb-3">
                    ${frontImg
                        ? `<img src="${_imageServePath(frontImg.image_path)}" class="img-fluid rounded" alt="Front" style="max-height:400px;">`
                        : `<div class="bg-light rounded d-flex align-items-center justify-content-center" style="height:300px;"><i class="bi bi-image fs-1 text-muted"></i></div>`
                    }
                    <small class="text-muted d-block mt-1">Front</small>
                </div>
                <div class="col-md-6 text-center mb-3">
                    ${backImg
                        ? `<img src="${_imageServePath(backImg.image_path)}" class="img-fluid rounded" alt="Back" style="max-height:400px;">`
                        : `<div class="bg-light rounded d-flex align-items-center justify-content-center" style="height:300px;"><i class="bi bi-image fs-1 text-muted"></i></div>`
                    }
                    <small class="text-muted d-block mt-1">Back</small>
                </div>
            </div>
            <table class="table table-sm table-borderless mt-2">
                <tr><th style="width:150px;">Status</th><td>${createStatusBadge(card.status)}</td></tr>
                <tr><th>Set</th><td>${escapeHtml(card.set_name || '')} (${escapeHtml(card.set_code || '')})</td></tr>
                <tr><th>Collector #</th><td>${escapeHtml(card.collector_number || '\u2014')}</td></tr>
                <tr><th>Rarity</th><td>${escapeHtml(card.rarity || '\u2014')}</td></tr>
                <tr><th>Language</th><td>${escapeHtml(card.language || '\u2014')}</td></tr>
                <tr><th>Franchise</th><td>${escapeHtml(card.franchise || '\u2014')}</td></tr>
                <tr><th>PokeWallet ID</th><td>${escapeHtml(card.pokewallet_card_id || '\u2014')}</td></tr>
                <tr><th>Approved by</th><td>${escapeHtml(card.approved_by || '\u2014')}</td></tr>
                <tr><th>Created</th><td>${formatDate(card.created_at)}</td></tr>
            </table>
        `;

        // Footer buttons based on status
        if (card.status === 'pending') {
            footer.innerHTML = `
                <button class="btn btn-success" id="ref-detail-approve">
                    <i class="bi bi-check-lg me-1"></i>Approve
                </button>
                <button class="btn btn-danger" id="ref-detail-reject">
                    <i class="bi bi-x-lg me-1"></i>Reject
                </button>
            `;
        } else {
            footer.innerHTML = `
                <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
            `;
        }
    } catch (err) {
        body.innerHTML = createEmptyState('Failed to load card: ' + escapeHtml(err.message), 'bi-exclamation-triangle');
    }
}

/* ================================================ add-from-scan modal */
function _openAddScanModal() {
    const modalEl = document.getElementById('ref-add-scan-modal');
    if (!modalEl) return;
    const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
    modal.show();
}

async function _submitAddFromScan() {
    const cardIdInput = document.getElementById('ref-scan-card-id');
    const operatorInput = document.getElementById('ref-scan-operator');
    const cardRecordId = cardIdInput?.value?.trim();
    const operator = operatorInput?.value?.trim() || 'operator';

    if (!cardRecordId) {
        showToast('Enter a card record ID.', 'warning');
        return;
    }

    try {
        await api.post('/reference/cards/add-from-scan', {
            card_record_id: cardRecordId,
            operator,
        });
        showToast('Reference created from scan.', 'success');
        _closeModal('ref-add-scan-modal');
        await _loadCards();
    } catch (err) {
        showToast(`Add from scan failed: ${err.message}`, 'error');
    }
}

/* =================================================== comparison modal */
function _openCompareModal() {
    const modalEl = document.getElementById('ref-compare-modal');
    if (!modalEl) return;
    document.getElementById('ref-compare-results')?.classList.add('d-none');
    const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
    modal.show();
}

async function _runComparison() {
    const scanPath = document.getElementById('ref-compare-scan-path')?.value?.trim();
    const refId    = document.getElementById('ref-compare-ref-id')?.value?.trim();

    if (!scanPath || !refId) {
        showToast('Provide both a scan image path and reference card ID.', 'warning');
        return;
    }

    const resultsDiv = document.getElementById('ref-compare-results');
    const scoresDiv  = document.getElementById('ref-compare-scores');
    resultsDiv?.classList.remove('d-none');
    if (scoresDiv) scoresDiv.innerHTML = createLoadingSpinner('Running comparison...');

    try {
        const data = await api.post('/reference/compare', {
            scan_image_path: scanPath,
            reference_card_id: refId,
        });

        const c = data.comparison;

        // Show scan preview
        const scanPreview = document.getElementById('ref-compare-scan-preview');
        if (scanPreview) {
            const dataIdx = scanPath.replace(/\\/g, '/').indexOf('data/');
            const src = dataIdx >= 0 ? '/' + scanPath.replace(/\\/g, '/').substring(dataIdx) : '';
            scanPreview.innerHTML = `
                <h6 class="text-muted mb-2">Scan</h6>
                ${src ? `<img src="${src}" class="img-fluid rounded" style="max-height:250px;">` : '<span class="text-muted">Preview not available</span>'}
            `;
        }

        // Show heatmap
        const heatmapPreview = document.getElementById('ref-compare-heatmap-preview');
        if (heatmapPreview) {
            if (c.diff_heatmap_path) {
                const hmUrl = _imageServePath(c.diff_heatmap_path);
                heatmapPreview.innerHTML = `
                    <h6 class="text-muted mb-2">Difference Heat Map</h6>
                    <img src="${hmUrl}" class="img-fluid rounded" style="max-height:250px;">
                `;
            } else {
                heatmapPreview.innerHTML = `
                    <h6 class="text-muted mb-2">Difference Heat Map</h6>
                    <span class="text-muted">Not available</span>
                `;
            }
        }

        // Scores
        if (scoresDiv) {
            scoresDiv.innerHTML = `
                <div class="col-md-3 text-center">
                    <div class="fs-3 fw-bold ${_scoreColor(c.ssim_score)}">${(c.ssim_score * 100).toFixed(1)}%</div>
                    <small class="text-muted">SSIM</small>
                </div>
                <div class="col-md-3 text-center">
                    <div class="fs-3 fw-bold ${_scoreColor(c.histogram_score)}">${(c.histogram_score * 100).toFixed(1)}%</div>
                    <small class="text-muted">Histogram</small>
                </div>
                <div class="col-md-3 text-center">
                    <div class="fs-3 fw-bold ${_scoreColor(c.orb_match_pct)}">${c.orb_match_count} (${(c.orb_match_pct * 100).toFixed(1)}%)</div>
                    <small class="text-muted">ORB Matches</small>
                </div>
                <div class="col-md-3 text-center">
                    <div class="fs-3 fw-bold ${_scoreColor(c.overall_similarity)}">${(c.overall_similarity * 100).toFixed(1)}%</div>
                    <small class="text-muted">Overall Similarity</small>
                </div>
            `;
        }
    } catch (err) {
        if (scoresDiv) {
            scoresDiv.innerHTML = `<div class="col-12 text-center text-danger">${escapeHtml(err.message)}</div>`;
        }
    }
}

function _scoreColor(score) {
    if (score >= 0.85) return 'text-success';
    if (score >= 0.60) return 'text-warning';
    return 'text-danger';
}

/* ============================================================ helpers */
function _imageServePath(absPath) {
    if (!absPath) return '';
    const normalised = absPath.replace(/\\/g, '/');
    const idx = normalised.indexOf('data/');
    return idx >= 0 ? '/' + normalised.substring(idx) : absPath;
}

function _closeModal(modalId) {
    const el = document.getElementById(modalId);
    if (!el) return;
    const inst = bootstrap.Modal.getInstance(el);
    if (inst) inst.hide();
}
