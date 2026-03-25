/**
 * RKT Grading Station - Reusable UI Components
 *
 * Factory functions that return HTML strings (or perform DOM side-effects
 * in the case of toasts).  Imported by every page module.
 */

/* global bootstrap */

// ------------------------------------------------------------------ HTML Escaping
/**
 * Escape HTML special characters in a string to prevent XSS when
 * inserting dynamic data into innerHTML.  Safe for all user-supplied
 * or API-returned values.
 */
export function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    if (typeof str !== 'string') str = String(str);
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// ------------------------------------------------------------------ Stat Card
export function createStatCard(title, value, subtitle = '', icon = 'bi-bar-chart', color = 'primary') {
    return `
        <div class="col-md-3 col-sm-6 mb-3">
            <div class="card stat-card h-100">
                <div class="card-body d-flex align-items-center">
                    <div class="stat-icon bg-${color}-subtle text-${color} rounded-3 p-3 me-3">
                        <i class="bi ${icon} fs-4"></i>
                    </div>
                    <div>
                        <div class="stat-value fw-bold fs-4">${escapeHtml(value)}</div>
                        <div class="stat-title text-muted small">${escapeHtml(title)}</div>
                        ${subtitle ? `<div class="stat-subtitle text-muted small">${escapeHtml(subtitle)}</div>` : ''}
                    </div>
                </div>
            </div>
        </div>
    `;
}

// ------------------------------------------------------------ Grade Badge
export function createGradeBadge(grade, size = 'lg') {
    let color = 'danger';
    if (grade >= 10)     color = 'gold';
    else if (grade >= 9) color = 'success';
    else if (grade >= 7) color = 'info';
    else if (grade >= 5) color = 'warning';

    const sizeClass = size === 'lg' ? 'grade-badge-lg'
                    : size === 'sm' ? 'grade-badge-sm'
                    : 'grade-badge';

    const bgClass  = color === 'gold' ? 'bg-warning' : `bg-${color}`;
    const txtClass = (color === 'gold' || color === 'warning') ? 'text-dark' : 'text-white';

    return `<span class="${sizeClass} ${bgClass} ${txtClass}">${escapeHtml(grade)}</span>`;
}

// ------------------------------------------------------- Authenticity Badge
export function createAuthBadge(status) {
    const map = {
        authentic:      { color: 'success',   icon: 'bi-shield-check',         label: 'Authentic' },
        suspect:        { color: 'warning',   icon: 'bi-exclamation-triangle', label: 'Suspect' },
        reject:         { color: 'danger',    icon: 'bi-x-octagon',           label: 'Reject' },
        manual_review:  { color: 'info',      icon: 'bi-eye',                 label: 'Manual Review' },
        pending:        { color: 'secondary', icon: 'bi-hourglass-split',     label: 'Pending' },
    };
    const s = map[status] || map['pending'];
    return `<span class="badge bg-${s.color}"><i class="bi ${s.icon} me-1"></i>${s.label}</span>`;
}

// ---------------------------------------------------------- Status Badge
export function createStatusBadge(status) {
    const map = {
        pending:    'secondary',
        processing: 'info',
        complete:   'success',
        completed:  'success',
        approved:   'success',
        overridden: 'warning',
        failed:     'danger',
        draft:      'secondary',
        previewed:  'info',
        exported:   'primary',
        engraved:   'success',
    };
    const color = map[status] || 'secondary';
    return `<span class="badge bg-${color}">${escapeHtml(status)}</span>`;
}

// ---------------------------------------------------------- Empty State
export function createEmptyState(message, icon = 'bi-inbox') {
    return `
        <div class="text-center py-5 text-muted">
            <i class="bi ${icon} fs-1 d-block mb-3"></i>
            <p class="mb-0">${escapeHtml(message)}</p>
        </div>
    `;
}

// -------------------------------------------------------- Loading Spinner
export function createLoadingSpinner(message = 'Loading...') {
    return `
        <div class="text-center py-5">
            <div class="spinner-border text-primary mb-3" role="status"></div>
            <p class="text-muted">${escapeHtml(message)}</p>
        </div>
    `;
}

// -------------------------------------------------------- Toast Notification
export function showToast(message, type = 'info') {
    const toastContainer = document.getElementById('toast-container');
    if (!toastContainer) return;

    const icons  = { success: 'bi-check-circle', error: 'bi-x-circle', warning: 'bi-exclamation-triangle', info: 'bi-info-circle' };
    const colors = { success: 'text-success',    error: 'text-danger',  warning: 'text-warning',            info: 'text-primary' };

    const id = 'toast-' + Date.now();
    const html = `
        <div id="${id}" class="toast" role="alert" aria-live="assertive" aria-atomic="true">
            <div class="toast-header">
                <i class="bi ${icons[type] || icons.info} ${colors[type] || colors.info} me-2"></i>
                <strong class="me-auto">RKT</strong>
                <button type="button" class="btn-close" data-bs-dismiss="toast"></button>
            </div>
            <div class="toast-body">${escapeHtml(message)}</div>
        </div>
    `;

    toastContainer.insertAdjacentHTML('beforeend', html);
    const toastEl = document.getElementById(id);
    const toast = new bootstrap.Toast(toastEl, { delay: 4000 });
    toast.show();
    toastEl.addEventListener('hidden.bs.toast', () => toastEl.remove());
}

// -------------------------------------------------------- Date Formatter
export function formatDate(isoString) {
    if (!isoString) return '\u2014';
    const d = new Date(isoString);
    return d.toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
    });
}
