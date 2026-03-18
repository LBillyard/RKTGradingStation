/**
 * Graded Cards page module.
 *
 * Displays all cards with their grades, thumbnails, and status.
 * Supports search, grade filtering, sorting, and click-to-review.
 */
import { api } from '../api.js';
import { createEmptyState, createGradeBadge, createStatusBadge } from '../components.js';
import { showToast } from '../components.js';

// ----- Module state -----
let currentPage = 0;
const PAGE_SIZE = 25;
let currentSearch = '';
let currentGradeMin = null;
let currentGradeMax = null;
let currentStatus = 'all';
let currentSortBy = 'created_at';
let currentSortDir = 'desc';
let totalCards = 0;

const _shortcutFns = {};

export async function init(container) {
    container.innerHTML = buildLayout();
    attachListeners(container);

    // Keyboard shortcuts: arrow left/right for pagination
    _shortcutFns['shortcut:prev-card'] = () => {
        if (currentPage > 0) { currentPage--; loadCards(); }
    };
    _shortcutFns['shortcut:next-card'] = () => {
        const totalPages = Math.ceil(totalCards / PAGE_SIZE);
        if (currentPage < totalPages - 1) { currentPage++; loadCards(); }
    };
    for (const [e, fn] of Object.entries(_shortcutFns)) window.addEventListener(e, fn);

    await loadCards();
}

export function destroy() {
    for (const [e, fn] of Object.entries(_shortcutFns)) window.removeEventListener(e, fn);
    currentPage = 0;
    currentSearch = '';
    currentGradeMin = null;
    currentGradeMax = null;
    currentStatus = 'all';
    totalCards = 0;
}

// ----- Layout -----

function buildLayout() {
    return `
        <div class="px-4 py-3">
            <div class="card">
                <div class="card-header">
                    <div class="d-flex justify-content-between align-items-center mb-2">
                        <h6 class="mb-0"><i class="bi bi-collection me-2"></i>Graded Cards</h6>
                        <button id="gc-refresh" class="btn btn-sm btn-outline-secondary">
                            <i class="bi bi-arrow-clockwise me-1"></i>Refresh
                        </button>
                    </div>
                    <div class="d-flex gap-2 flex-wrap align-items-center">
                        <input type="text" id="gc-search" class="form-control form-control-sm"
                               placeholder="Search card name..." style="width:220px;">
                        <select id="gc-grade-min" class="form-select form-select-sm" style="width:110px;">
                            <option value="">Min Grade</option>
                            <option value="1">1+</option>
                            <option value="3">3+</option>
                            <option value="5">5+</option>
                            <option value="7">7+</option>
                            <option value="8">8+</option>
                            <option value="9">9+</option>
                            <option value="9.5">9.5+</option>
                            <option value="10">10</option>
                        </select>
                        <select id="gc-grade-max" class="form-select form-select-sm" style="width:110px;">
                            <option value="">Max Grade</option>
                            <option value="4">4</option>
                            <option value="6">6</option>
                            <option value="8">8</option>
                            <option value="9">9</option>
                            <option value="10">10</option>
                        </select>
                        <select id="gc-status" class="form-select form-select-sm" style="width:130px;">
                            <option value="all">All Statuses</option>
                            <option value="pending">Pending</option>
                            <option value="processing">Processing</option>
                            <option value="graded">Graded</option>
                            <option value="complete">Complete</option>
                        </select>
                        <div class="ms-auto d-flex align-items-center gap-2">
                            <span class="text-muted small" id="gc-count">0 cards</span>
                            <a href="/api/queue/export" class="btn btn-sm btn-outline-success" download title="Export all graded cards as CSV">
                                <i class="bi bi-file-earmark-spreadsheet me-1"></i>Export CSV
                            </a>
                        </div>
                    </div>
                </div>
                <div class="card-body p-0">
                    <div class="table-responsive">
                        <table class="table table-hover mb-0 align-middle" id="gc-table">
                            <thead class="table-light">
                                <tr>
                                    <th style="width:60px;"></th>
                                    <th class="gc-sortable" data-sort="card_name">Card Name</th>
                                    <th>Set</th>
                                    <th class="gc-sortable text-center" data-sort="grade">Grade</th>
                                    <th class="gc-sortable text-center" data-sort="status">Status</th>
                                    <th>Serial</th>
                                    <th class="gc-sortable" data-sort="created_at">Date</th>
                                </tr>
                            </thead>
                            <tbody id="gc-tbody">
                                <tr><td colspan="7">${createEmptyState('Loading...', 'bi-hourglass-split')}</td></tr>
                            </tbody>
                        </table>
                    </div>
                </div>
                <div class="card-footer d-flex justify-content-between align-items-center">
                    <button id="gc-prev" class="btn btn-sm btn-outline-secondary" disabled>
                        <i class="bi bi-chevron-left me-1"></i>Previous
                    </button>
                    <span class="text-muted small" id="gc-page-info">Page 1</span>
                    <button id="gc-next" class="btn btn-sm btn-outline-secondary" disabled>
                        Next<i class="bi bi-chevron-right ms-1"></i>
                    </button>
                </div>
            </div>
        </div>
    `;
}

// ----- Data Loading -----

async function loadCards() {
    const tbody = document.getElementById('gc-tbody');
    if (!tbody) return;

    tbody.innerHTML = `<tr><td colspan="7" class="text-center py-4">
        <div class="spinner-border spinner-border-sm text-primary me-2"></div>Loading...
    </td></tr>`;

    try {
        const params = new URLSearchParams({
            limit: PAGE_SIZE,
            offset: currentPage * PAGE_SIZE,
            sort_by: currentSortBy,
            sort_dir: currentSortDir,
        });
        if (currentSearch) params.set('search', currentSearch);
        if (currentGradeMin !== null) params.set('grade_min', currentGradeMin);
        if (currentGradeMax !== null) params.set('grade_max', currentGradeMax);
        if (currentStatus !== 'all') params.set('status', currentStatus);

        const data = await api.get(`/queue/list?${params}`);
        totalCards = data.total;
        renderTable(data.cards);
        updatePagination();
    } catch (err) {
        tbody.innerHTML = `<tr><td colspan="7">
            <div class="alert alert-danger m-3">${err.message}</div>
        </td></tr>`;
    }
}

function renderTable(cards) {
    const tbody = document.getElementById('gc-tbody');
    const countEl = document.getElementById('gc-count');
    if (!tbody) return;

    if (countEl) countEl.textContent = `${totalCards} card${totalCards !== 1 ? 's' : ''}`;

    if (!cards.length) {
        tbody.innerHTML = `<tr><td colspan="7">
            ${createEmptyState('No cards found. Adjust filters or start a new scan.', 'bi-collection')}
        </td></tr>`;
        return;
    }

    tbody.innerHTML = cards.map(c => {
        const grade = c.final_grade;
        const gradeBadge = grade !== null && grade !== undefined
            ? createGradeBadge(grade, 'sm')
            : '<span class="badge bg-secondary">--</span>';

        const statusBadge = createStatusBadge(c.grade_status || c.status);

        // Thumbnail
        const thumbSrc = c.thumbnail_path || c.front_image_path;
        const thumbHtml = thumbSrc
            ? `<img src="${thumbSrc}" alt="" style="width:45px;height:63px;object-fit:cover;border-radius:4px;" onerror="this.style.display='none'">`
            : '<div style="width:45px;height:63px;background:#e9ecef;border-radius:4px;" class="d-flex align-items-center justify-content-center"><i class="bi bi-image text-muted"></i></div>';

        // Date formatting
        const dateStr = c.created_at
            ? new Date(c.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
            : '--';

        const serial = c.serial_number
            ? `<code class="small">${c.serial_number.substring(0, 12)}</code>`
            : '<span class="text-muted">--</span>';

        return `
            <tr class="gc-row" data-card-id="${c.id}" style="cursor:pointer;">
                <td class="ps-3">${thumbHtml}</td>
                <td>
                    <div class="fw-semibold">${c.card_name || 'Unknown Card'}</div>
                    ${c.collector_number ? `<span class="text-muted small">#${c.collector_number}</span>` : ''}
                    ${c.rarity ? `<span class="text-muted small ms-1">${c.rarity}</span>` : ''}
                </td>
                <td class="small">${c.set_name || '--'}</td>
                <td class="text-center">${gradeBadge}</td>
                <td class="text-center">${statusBadge}</td>
                <td>${serial}</td>
                <td class="small text-muted">${dateStr}</td>
            </tr>
        `;
    }).join('');

    // Attach row click handlers
    tbody.querySelectorAll('.gc-row').forEach(row => {
        row.addEventListener('click', () => {
            const cardId = row.dataset.cardId;
            if (cardId) {
                sessionStorage.setItem('rkt_review_card_id', cardId);
                location.hash = '#/grade-review';
            }
        });
    });
}

function updatePagination() {
    const totalPages = Math.max(1, Math.ceil(totalCards / PAGE_SIZE));
    const pageInfo = document.getElementById('gc-page-info');
    const prevBtn = document.getElementById('gc-prev');
    const nextBtn = document.getElementById('gc-next');

    if (pageInfo) pageInfo.textContent = `Page ${currentPage + 1} of ${totalPages}`;
    if (prevBtn) prevBtn.disabled = currentPage <= 0;
    if (nextBtn) nextBtn.disabled = currentPage >= totalPages - 1;
}

// ----- Event Listeners -----

function attachListeners(container) {
    // Search with debounce
    let searchTimeout = null;
    container.querySelector('#gc-search')?.addEventListener('input', (e) => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
            currentSearch = e.target.value.trim();
            currentPage = 0;
            loadCards();
        }, 300);
    });

    // Grade filters
    container.querySelector('#gc-grade-min')?.addEventListener('change', (e) => {
        currentGradeMin = e.target.value ? parseFloat(e.target.value) : null;
        currentPage = 0;
        loadCards();
    });
    container.querySelector('#gc-grade-max')?.addEventListener('change', (e) => {
        currentGradeMax = e.target.value ? parseFloat(e.target.value) : null;
        currentPage = 0;
        loadCards();
    });

    // Status filter
    container.querySelector('#gc-status')?.addEventListener('change', (e) => {
        currentStatus = e.target.value;
        currentPage = 0;
        loadCards();
    });

    // Refresh
    container.querySelector('#gc-refresh')?.addEventListener('click', () => loadCards());

    // Pagination
    container.querySelector('#gc-prev')?.addEventListener('click', () => {
        if (currentPage > 0) { currentPage--; loadCards(); }
    });
    container.querySelector('#gc-next')?.addEventListener('click', () => {
        const totalPages = Math.ceil(totalCards / PAGE_SIZE);
        if (currentPage < totalPages - 1) { currentPage++; loadCards(); }
    });

    // Sortable columns
    container.querySelectorAll('.gc-sortable').forEach(th => {
        th.style.cursor = 'pointer';
        th.addEventListener('click', () => {
            const col = th.dataset.sort;
            if (currentSortBy === col) {
                currentSortDir = currentSortDir === 'desc' ? 'asc' : 'desc';
            } else {
                currentSortBy = col;
                currentSortDir = col === 'card_name' ? 'asc' : 'desc';
            }
            currentPage = 0;
            loadCards();
        });
    });
}
