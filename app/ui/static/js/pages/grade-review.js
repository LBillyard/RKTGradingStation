/**
 * Grade Review page module.
 *
 * Allows operators to review AI-assigned grades, view card images with
 * defect overlays, and approve or override grades before finalisation.
 */
import { api } from '../api.js';
import {
    createEmptyState,
    createGradeBadge,
    createStatusBadge,
    createAuthBadge,
    createLoadingSpinner,
    showToast,
} from '../components.js';
import { ImageViewer } from '../image-viewer.js';

// ----- Module state -----
let viewer = null;
let currentCardId = null;
let currentGradeData = null;
let currentFrontUrl = null;
let currentBackUrl = null;
let currentSide = 'front';

// Language display map
const LANGUAGE_LABELS = {
    en: 'English',
    ja: 'Japanese',
    ko: 'Korean',
    'zh-cn': 'Chinese (Simplified)',
    'zh-tw': 'Chinese (Traditional)',
    zh: 'Chinese',
    de: 'German',
    fr: 'French',
    es: 'Spanish',
    it: 'Italian',
    pt: 'Portuguese',
};

// Grade name labels (TAG-inspired)
const GRADE_NAMES = {
    10:  'Gem Mint',
    9.5: 'Mint+',
    9:   'Mint',
    8.5: 'NM-MT+',
    8:   'NM-MT',
    7.5: 'Near Mint+',
    7:   'Near Mint',
    6.5: 'EX-NM+',
    6:   'EX-NM',
    5.5: 'Excellent+',
    5:   'Excellent',
    4.5: 'VG-EX+',
    4:   'VG-EX',
    3.5: 'Very Good+',
    3:   'Very Good',
    2.5: 'Good+',
    2:   'Good',
    1.5: 'Fair',
    1:   'Poor',
};

function getGradeLabel(grade) {
    if (grade == null) return '';
    return GRADE_NAMES[grade] || '';
}

// Severity class mapping
const SEVERITY_CLASS_MAP = {
    minor: 'defect-minor',
    moderate: 'defect-moderate',
    major: 'defect-major',
    severe: 'defect-severe',
};

// Valid grades for the override dropdown
const VALID_GRADES = [];
for (let g = 20; g >= 2; g--) {
    VALID_GRADES.push(g / 2);
}

// ----- Page lifecycle -----

// Keyboard shortcut handlers (stored for cleanup)
const _shortcutHandlers = {};

export async function init(container) {
    container.innerHTML = buildLayout();
    attachEventListeners(container);
    attachShortcutListeners();

    // Auto-load card if passed from Graded Cards page
    const passedId = sessionStorage.getItem('rkt_review_card_id');
    if (passedId) {
        sessionStorage.removeItem('rkt_review_card_id');
        const searchInput = container.querySelector('#grade-card-search');
        if (searchInput) searchInput.value = passedId;
        await loadCard(passedId);
    }
}

export function destroy() {
    // Remove keyboard shortcut listeners
    for (const [evt, fn] of Object.entries(_shortcutHandlers)) {
        window.removeEventListener(evt, fn);
    }

    if (viewer) {
        viewer.destroy();
        viewer = null;
    }
    currentCardId = null;
    currentGradeData = null;
    currentFrontUrl = null;
    currentBackUrl = null;
    currentSide = 'front';
}

function attachShortcutListeners() {
    _shortcutHandlers['shortcut:approve'] = () => { if (currentCardId && currentGradeData) approveGrade(); };
    _shortcutHandlers['shortcut:toggle-overlays'] = () => viewer?.toggleOverlays();
    _shortcutHandlers['shortcut:flip-card'] = () => { if (currentBackUrl) flipSide(); };
    _shortcutHandlers['shortcut:zoom-in'] = () => { viewer?.zoomIn(); updateZoomDisplay(); };
    _shortcutHandlers['shortcut:zoom-out'] = () => { viewer?.zoomOut(); updateZoomDisplay(); };
    _shortcutHandlers['shortcut:zoom-reset'] = () => { viewer?.resetView(); updateZoomDisplay(); };

    for (const [evt, fn] of Object.entries(_shortcutHandlers)) {
        window.addEventListener(evt, fn);
    }
}

// ----- Layout -----

function buildLayout() {
    return `
        <div class="px-4 py-3">
            <!-- Card Search Bar -->
            <div class="row mb-3">
                <div class="col-12">
                    <div class="card">
                        <div class="card-body py-2">
                            <div class="d-flex align-items-center gap-3">
                                <label class="text-muted small text-nowrap mb-0">Card ID:</label>
                                <input type="text" id="grade-card-search"
                                       class="form-control form-control-sm"
                                       placeholder="Enter card ID or scan barcode..."
                                       style="max-width:400px;">
                                <button id="grade-load-btn" class="btn btn-sm btn-primary">
                                    <i class="bi bi-search me-1"></i>Load
                                </button>
                                <button id="grade-run-btn" class="btn btn-sm btn-outline-primary" disabled>
                                    <i class="bi bi-cpu me-1"></i>Run Grading
                                </button>
                                <div class="ms-auto d-flex align-items-center gap-2">
                                    <label class="text-muted small mb-0">Profile:</label>
                                    <select id="grade-profile-select" class="form-select form-select-sm" style="width:140px;">
                                        <option value="lenient" selected>Lenient</option>
                                        <option value="standard">Standard</option>
                                        <option value="strict">Strict</option>
                                    </select>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <div class="row">
                <!-- ===== LEFT PANEL: Image + Defects ===== -->
                <div class="col-lg-7 mb-4">
                    <div class="card">
                        <div class="card-header d-flex justify-content-between align-items-center">
                            <h6 class="mb-0">Card Image &amp; Defects</h6>
                            <div class="d-flex gap-2 align-items-center">
                                <span id="grade-side-label" class="badge bg-secondary me-1">Front</span>
                                <button id="grade-toggle-side" class="btn btn-sm btn-secondary" disabled title="Switch front/back">
                                    <i class="bi bi-arrow-left-right me-1"></i>Flip
                                </button>
                                <div class="vr mx-1"></div>
                                <button id="grade-zoom-out" class="btn btn-sm btn-secondary" disabled title="Zoom out">
                                    <i class="bi bi-zoom-out"></i>
                                </button>
                                <span id="grade-zoom-level" class="small text-light" style="min-width:40px;text-align:center;">100%</span>
                                <button id="grade-zoom-in" class="btn btn-sm btn-secondary" disabled title="Zoom in">
                                    <i class="bi bi-zoom-in"></i>
                                </button>
                                <button id="grade-reset-zoom" class="btn btn-sm btn-secondary" disabled title="Fit to view">
                                    <i class="bi bi-arrows-fullscreen me-1"></i>Fit
                                </button>
                                <div class="vr mx-1"></div>
                                <button id="grade-toggle-overlays" class="btn btn-sm btn-secondary" disabled title="Toggle defect overlays">
                                    <i class="bi bi-layers me-1"></i>Overlays
                                </button>
                            </div>
                        </div>
                        <div class="card-body p-0">
                            <div id="grade-image-container" style="min-height:450px;position:relative;background:#1a1a2e;">
                                <div class="scan-placeholder text-center py-5">
                                    <i class="bi bi-clipboard-check" style="font-size:3rem;color:#64748b;"></i>
                                    <p class="text-muted mt-2 mb-0">Select a card to begin review</p>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- Defect List -->
                    <div class="card mt-3">
                        <div class="card-header d-flex justify-content-between align-items-center">
                            <h6 class="mb-0">Detected Defects</h6>
                            <span id="grade-defect-count" class="badge bg-secondary">0</span>
                        </div>
                        <div class="card-body p-2">
                            <div id="grade-severity-summary"></div>
                            <div id="grade-defect-list" class="list-group list-group-flush" style="max-height:220px;overflow-y:auto;">
                                ${createEmptyState('No defects to display', 'bi-check-circle')}
                            </div>
                        </div>
                    </div>

                    <!-- Defect Zones -->
                    <div class="card mt-3" id="grade-zone-card" style="display:none;">
                        <div class="card-header"><h6 class="mb-0"><i class="bi bi-grid-3x3 me-2"></i>Defect Zones</h6></div>
                        <div class="card-body py-2" id="grade-zone-summary"></div>
                    </div>
                </div>

                <!-- ===== RIGHT PANEL: Grade Details ===== -->
                <div class="col-lg-5 mb-4">

                    <!-- 1. Grade Summary (always visible) -->
                    <div class="card mb-3">
                        <div class="card-header d-flex justify-content-between align-items-center">
                            <h6 class="mb-0">Grade Summary</h6>
                            <span id="grade-status-badge"></span>
                        </div>
                        <div class="card-body" id="grade-summary-body">
                            <div id="grade-card-info" class="mb-3 border-bottom pb-2" style="display:none;">
                                <div class="fw-semibold fs-6" id="grade-card-name"></div>
                                <div class="d-flex flex-wrap gap-1 mt-1" id="grade-card-meta"></div>
                            </div>
                            <div class="text-center">
                                <div class="mb-2" id="grade-badge-container">
                                    ${createGradeBadge(0, 'lg')}
                                </div>
                                <div id="grade-name-label" class="grade-name-label mb-2"></div>
                                <div class="text-muted small" id="grade-summary-text">No card selected for review</div>
                            </div>
                        </div>
                    </div>

                    <!-- 2. Authenticity Status (conditional) -->
                    <div class="card mb-3" id="grade-auth-card" style="display:none;">
                        <div class="card-header d-flex justify-content-between align-items-center">
                            <h6 class="mb-0"><i class="bi bi-shield-check me-2"></i>Authenticity</h6>
                            <span id="grade-auth-badge"></span>
                        </div>
                        <div class="card-body py-2" id="grade-auth-body"></div>
                    </div>

                    <!-- 3. Sub-Grades (default open) -->
                    <div class="card mb-3">
                        <div class="card-header d-flex justify-content-between align-items-center"
                             data-bs-toggle="collapse" data-bs-target="#collapse-subgrades" role="button">
                            <h6 class="mb-0">Sub-Grades</h6>
                            <i class="bi bi-chevron-down small"></i>
                        </div>
                        <div class="collapse show" id="collapse-subgrades">
                            <div class="card-body" id="grade-sub-grades">
                                ${buildSubGradeRows(null)}
                            </div>
                        </div>
                    </div>

                    <!-- 4. Grade Caps (conditional) -->
                    <div class="card mb-3" id="grade-caps-card" style="display:none;">
                        <div class="card-header">
                            <h6 class="mb-0"><i class="bi bi-exclamation-triangle-fill text-warning me-2"></i>Grade Caps Applied</h6>
                        </div>
                        <div class="card-body p-0" id="grade-caps-body"></div>
                    </div>

                    <!-- 5. Centering (collapsible) -->
                    <div class="card mb-3">
                        <div class="card-header d-flex justify-content-between align-items-center"
                             data-bs-toggle="collapse" data-bs-target="#collapse-centering" role="button">
                            <h6 class="mb-0">Centering</h6>
                            <i class="bi bi-chevron-down small"></i>
                        </div>
                        <div class="collapse" id="collapse-centering">
                            <div class="card-body" id="grade-centering-detail">
                                <div class="text-center text-muted small">No centering data</div>
                            </div>
                        </div>
                    </div>

                    <!-- 6. Grading Confidence (collapsible) -->
                    <div class="card mb-3" id="grade-confidence-card" style="display:none;">
                        <div class="card-header d-flex justify-content-between align-items-center"
                             data-bs-toggle="collapse" data-bs-target="#collapse-confidence" role="button">
                            <h6 class="mb-0"><i class="bi bi-speedometer me-2"></i>Grading Confidence</h6>
                            <i class="bi bi-chevron-down small"></i>
                        </div>
                        <div class="collapse" id="collapse-confidence">
                            <div class="card-body text-center" id="grade-confidence-body">
                                <div class="fs-3 fw-bold" id="grade-confidence-value">--</div>
                                <div class="progress mt-2" style="height:8px;">
                                    <div id="grade-confidence-bar" class="progress-bar" role="progressbar" style="width:0%"></div>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- 7. Grade History (collapsible) -->
                    <div class="card mb-3" id="grade-history-card" style="display:none;">
                        <div class="card-header d-flex justify-content-between align-items-center"
                             data-bs-toggle="collapse" data-bs-target="#collapse-history" role="button">
                            <h6 class="mb-0"><i class="bi bi-clock-history me-2"></i>Grade History</h6>
                            <div class="d-flex align-items-center gap-2">
                                <span id="grade-history-count" class="badge bg-secondary">0</span>
                                <i class="bi bi-chevron-down small"></i>
                            </div>
                        </div>
                        <div class="collapse" id="collapse-history">
                            <div class="card-body p-0" id="grade-history-body">
                                <div class="list-group list-group-flush" id="grade-history-list" style="max-height:150px;overflow-y:auto;"></div>
                            </div>
                        </div>
                    </div>

                    <!-- 8. Population Report (collapsible) -->
                    <div class="card mb-3" id="grade-population-card" style="display:none;">
                        <div class="card-header d-flex justify-content-between align-items-center"
                             data-bs-toggle="collapse" data-bs-target="#collapse-population" role="button">
                            <h6 class="mb-0"><i class="bi bi-bar-chart-fill me-2"></i>Population Report</h6>
                            <i class="bi bi-chevron-down small"></i>
                        </div>
                        <div class="collapse" id="collapse-population">
                            <div class="card-body py-2" id="grade-population-body"></div>
                        </div>
                    </div>

                    <!-- 9. AI Analysis (collapsible) -->
                    <div class="card mb-3" id="grade-ai-review-card" style="display:none;">
                        <div class="card-header d-flex justify-content-between align-items-center"
                             data-bs-toggle="collapse" data-bs-target="#collapse-ai" role="button">
                            <h6 class="mb-0"><i class="bi bi-robot me-2"></i>AI Analysis</h6>
                            <i class="bi bi-chevron-down small"></i>
                        </div>
                        <div class="collapse" id="collapse-ai">
                            <div class="card-body" id="grade-ai-review-body">
                                <div class="text-center text-muted small">No AI analysis available</div>
                            </div>
                        </div>
                    </div>

                    <!-- 10. Review Actions (always visible) -->
                    <div class="card">
                        <div class="card-header"><h6 class="mb-0">Review Actions</h6></div>
                        <div class="card-body">
                            <button id="grade-approve-btn" class="btn btn-success w-100 mb-2" disabled>
                                <i class="bi bi-check-lg me-2"></i>Approve Grade
                            </button>
                            <button id="grade-override-btn" class="btn btn-outline-warning w-100 mb-2" disabled>
                                <i class="bi bi-pencil me-2"></i>Override Grade
                            </button>
                            <button id="grade-rescan-btn" class="btn btn-outline-danger w-100 mb-2" disabled>
                                <i class="bi bi-arrow-return-left me-2"></i>Request Rescan
                            </button>
                            <hr>
                            <a id="grade-pdf-btn" class="btn btn-outline-secondary w-100" href="#" target="_blank" style="pointer-events:none; opacity:0.5;">
                                <i class="bi bi-file-earmark-pdf me-2"></i>Download PDF Report
                            </a>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Override Modal -->
        <div class="modal fade" id="grade-override-modal" tabindex="-1">
            <div class="modal-dialog">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">Override Grade</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="mb-3">
                            <label class="form-label">Current Auto-Grade</label>
                            <div id="override-current-grade" class="fw-bold fs-5">&mdash;</div>
                        </div>
                        <div class="mb-3">
                            <label for="override-grade-select" class="form-label">New Grade</label>
                            <select id="override-grade-select" class="form-select">
                                ${VALID_GRADES.map(g => `<option value="${g}">${g.toFixed(1)}</option>`).join('')}
                            </select>
                        </div>
                        <div class="mb-3">
                            <label for="override-reason" class="form-label">Reason (required)</label>
                            <textarea id="override-reason" class="form-control" rows="3"
                                      placeholder="Explain why you are overriding the auto-grade..."
                                      minlength="5"></textarea>
                            <div class="form-text">Minimum 5 characters required.</div>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                        <button type="button" id="override-submit-btn" class="btn btn-warning">
                            <i class="bi bi-pencil me-1"></i>Submit Override
                        </button>
                    </div>
                </div>
            </div>
        </div>
    `;
}

function buildSubGradeRows(data) {
    const categories = [
        { key: 'centering_score', label: 'Centering', weight: '10%', icon: 'bi-arrows-move' },
        { key: 'corners_score', label: 'Corners', weight: '30%', icon: 'bi-bounding-box-circles' },
        { key: 'edges_score', label: 'Edges', weight: '30%', icon: 'bi-border-outer' },
        { key: 'surface_score', label: 'Surface', weight: '30%', icon: 'bi-card-image' },
    ];

    return categories.map(cat => {
        const score = data ? data[cat.key] : null;
        const hasScore = score !== null && score !== undefined;
        const pct = hasScore ? (score / 10) * 100 : 0;
        const barColor = score >= 9 ? 'bg-success' : score >= 7 ? 'bg-info' : score >= 5 ? 'bg-warning' : 'bg-danger';
        const gradeName = hasScore ? getGradeLabel(score) : '';

        return `
            <div class="mb-3">
                <div class="d-flex justify-content-between align-items-center mb-1">
                    <div class="d-flex align-items-center gap-2">
                        <i class="bi ${cat.icon} text-muted"></i>
                        <span class="small fw-semibold">${cat.label}</span>
                        <span class="text-muted" style="font-size:0.6rem;">(${cat.weight})</span>
                    </div>
                    <div class="d-flex align-items-center gap-2">
                        ${gradeName ? `<span class="text-muted" style="font-size:0.65rem;">${gradeName}</span>` : ''}
                        ${hasScore ? createGradeBadge(score, 'sm') : '<span class="badge bg-light text-dark">&mdash;</span>'}
                    </div>
                </div>
                <div class="progress" style="height:6px;">
                    <div class="progress-bar ${hasScore ? barColor : ''}" role="progressbar"
                         style="width:${pct}%"></div>
                </div>
            </div>
        `;
    }).join('') + (data ? buildFrontBackSplit(data.defects || []) : '');
}

function buildFrontBackSplit(defects) {
    if (!defects || defects.length === 0) return '';
    const backDefects = defects.filter(d => !d.is_noise && d.side === 'back');
    if (backDefects.length === 0) return '';
    const frontDefects = defects.filter(d => !d.is_noise && d.side === 'front');
    const countBySide = (list, cat) => list.filter(d => d.category === cat).length;
    const categories = ['corner', 'edge', 'surface'];
    const rows = categories.map(cat => {
        const fc = countBySide(frontDefects, cat);
        const bc = countBySide(backDefects, cat);
        if (fc === 0 && bc === 0) return '';
        return `
            <div class="d-flex justify-content-between small py-1">
                <span class="text-capitalize">${cat}s</span>
                <span>
                    <span class="text-muted">F:</span><span class="fw-semibold">${fc}</span>
                    <span class="text-muted ms-2">B:</span><span class="fw-semibold">${bc}</span>
                </span>
            </div>`;
    }).filter(Boolean);
    if (rows.length === 0) return '';
    return `
        <div class="mt-2 pt-2 border-top">
            <div class="small text-muted fw-semibold mb-1">
                <i class="bi bi-arrow-left-right me-1"></i>Front / Back Defect Split
            </div>
            ${rows.join('')}
        </div>`;
}

// ----- Event Listeners -----

function attachEventListeners(container) {
    // Load card
    const loadBtn = container.querySelector('#grade-load-btn');
    const searchInput = container.querySelector('#grade-card-search');

    loadBtn?.addEventListener('click', () => {
        const cardId = searchInput?.value?.trim();
        if (cardId) loadCard(cardId);
    });

    searchInput?.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            const cardId = searchInput.value.trim();
            if (cardId) loadCard(cardId);
        }
    });

    // Run grading
    container.querySelector('#grade-run-btn')?.addEventListener('click', runGrading);

    // Image controls
    container.querySelector('#grade-reset-zoom')?.addEventListener('click', () => {
        viewer?.resetView();
        updateZoomDisplay();
    });
    container.querySelector('#grade-toggle-overlays')?.addEventListener('click', () => viewer?.toggleOverlays());
    container.querySelector('#grade-zoom-in')?.addEventListener('click', () => {
        viewer?.zoomIn();
        updateZoomDisplay();
    });
    container.querySelector('#grade-zoom-out')?.addEventListener('click', () => {
        viewer?.zoomOut();
        updateZoomDisplay();
    });
    container.querySelector('#grade-toggle-side')?.addEventListener('click', flipSide);

    // Approve
    container.querySelector('#grade-approve-btn')?.addEventListener('click', approveGrade);

    // Override
    container.querySelector('#grade-override-btn')?.addEventListener('click', openOverrideModal);
    container.querySelector('#override-submit-btn')?.addEventListener('click', submitOverride);

    // Rescan
    container.querySelector('#grade-rescan-btn')?.addEventListener('click', requestRescan);

    // Load profiles
    loadProfiles();
}

// ----- Data Loading -----

async function loadCard(cardId) {
    currentCardId = cardId;

    try {
        const data = await api.get(`/grading/${cardId}`);
        currentGradeData = data;
        renderGradeData(data);
        await loadCardImage(cardId);
    } catch (err) {
        if (err.status === 404) {
            // No grade yet -- still allow running grading
            currentGradeData = null;
            renderEmptyGrade();
            await loadCardImage(cardId);
            enableRunButton(true);
            showToast('No grade found for this card. Click "Run Grading" to analyse.', 'info');
        } else {
            showToast(`Failed to load grade: ${err.message}`, 'error');
        }
    }
}

async function loadCardImage(cardId) {
    // Initialise viewer
    if (!viewer) {
        viewer = new ImageViewer();
        await viewer.init('grade-image-container');
        viewer.onOverlayClick = handleOverlayClick;

        // Update zoom display on wheel events
        const container = document.getElementById('grade-image-container');
        container?.addEventListener('wheel', () => setTimeout(updateZoomDisplay, 50));
    }

    // Use image paths from grade data API response
    currentFrontUrl = currentGradeData?.front_image_url || null;
    currentBackUrl = currentGradeData?.back_image_url || null;
    currentSide = 'front';

    // Update side label
    const sideLabel = document.getElementById('grade-side-label');
    if (sideLabel) sideLabel.textContent = 'Front';

    // Load front image
    if (currentFrontUrl) {
        try {
            await viewer.loadImage(currentFrontUrl);
            enableImageControls(true);
            updateZoomDisplay();
        } catch {
            enableImageControls(false);
        }
    } else {
        enableImageControls(false);
    }

    // Enable/disable flip button based on back image availability
    const flipBtn = document.getElementById('grade-toggle-side');
    if (flipBtn) flipBtn.disabled = !currentBackUrl;

    // Add defect overlays for current side
    if (currentGradeData?.defects) {
        addDefectOverlays(currentGradeData.defects);
    }
}

async function flipSide() {
    if (!viewer) return;

    const newSide = currentSide === 'front' ? 'back' : 'front';
    const url = newSide === 'front' ? currentFrontUrl : currentBackUrl;

    if (!url) return;

    try {
        await viewer.loadImage(url);
        currentSide = newSide;

        // Update side label
        const sideLabel = document.getElementById('grade-side-label');
        if (sideLabel) sideLabel.textContent = newSide === 'front' ? 'Front' : 'Back';

        // Re-apply defect overlays filtered by side
        if (currentGradeData?.defects) {
            addDefectOverlays(currentGradeData.defects);
        }
        updateZoomDisplay();
    } catch {
        showToast(`Failed to load ${newSide} image`, 'error');
    }
}

function updateZoomDisplay() {
    const el = document.getElementById('grade-zoom-level');
    if (el && viewer) el.textContent = viewer.getZoomPercent() + '%';
}

async function loadProfiles() {
    try {
        const data = await api.get('/grading/profiles/list');
        const select = document.getElementById('grade-profile-select');
        if (select && data.profiles) {
            select.innerHTML = data.profiles.map(p =>
                `<option value="${p.name}">${p.label}</option>`
            ).join('');
        }
    } catch {
        // Use defaults already in the HTML
    }
}

// ----- Rendering -----

function renderGradeData(data) {
    // Card info (expanded metadata)
    renderCardInfo(data);

    // Status badge
    const statusEl = document.getElementById('grade-status-badge');
    if (statusEl) statusEl.innerHTML = createStatusBadge(data.status);

    // Final grade badge + grade name label
    const badgeEl = document.getElementById('grade-badge-container');
    const nameLabelEl = document.getElementById('grade-name-label');
    const grade = data.override_grade || data.final_grade || 0;
    if (badgeEl) badgeEl.innerHTML = createGradeBadge(grade, 'lg');
    if (nameLabelEl) nameLabelEl.textContent = getGradeLabel(grade);

    // Summary text (raw score + profile)
    const summaryEl = document.getElementById('grade-summary-text');
    if (summaryEl) {
        const parts = [];
        if (data.raw_grade != null) {
            parts.push(`<span class="text-muted">Raw:</span> <span class="fw-bold">${data.raw_grade.toFixed(2)}</span>`);
        }
        if (data.auto_grade && data.override_grade) {
            parts.push(`<span class="text-muted">Auto:</span> ${data.auto_grade.toFixed(1)}`);
            parts.push(`<span class="text-warning fw-bold">Override: ${data.override_grade.toFixed(1)}</span>`);
        }
        if (data.sensitivity_profile) {
            parts.push(`<span class="badge bg-light text-dark border">${data.sensitivity_profile}</span>`);
        }
        summaryEl.innerHTML = parts.join(' <span class="text-muted mx-1">|</span> ') || 'Graded';
    }

    // Authenticity status
    loadAuthenticityStatus(data.card_record_id);

    // Sub-grades (with progress bars + front/back split)
    const subEl = document.getElementById('grade-sub-grades');
    if (subEl) subEl.innerHTML = buildSubGradeRows(data);

    // Grade caps
    renderGradeCaps(data.grade_caps);

    // Centering diagram
    renderCenteringDiagram(data);

    // Grading confidence
    renderConfidence(data.grading_confidence);

    // Grade history
    loadGradeHistory(data.card_record_id);

    // Population report
    if (data.pokewallet_card_id) loadPopulation(data.pokewallet_card_id);

    // Defects
    renderDefectList(data.defects || []);
    renderDefectSeveritySummary(data.defects || []);
    renderZoneHeatmap(data.defects || []);

    // AI Review
    renderAIReview(data.ai_review);

    // Enable action buttons based on status
    const isGraded = ['graded', 'overridden'].includes(data.status);
    enableActionButtons(isGraded);
    enableRunButton(true);
}

function renderCardInfo(data) {
    const infoEl = document.getElementById('grade-card-info');
    const nameEl = document.getElementById('grade-card-name');
    const metaEl = document.getElementById('grade-card-meta');
    if (!infoEl || !nameEl || !metaEl) return;

    if (!data.card_name) {
        infoEl.style.display = 'none';
        return;
    }

    infoEl.style.display = '';
    nameEl.textContent = data.card_name;

    const badges = [];
    if (data.set_name) {
        badges.push(`<span class="badge bg-primary-subtle text-primary-emphasis"><i class="bi bi-collection me-1"></i>${data.set_name}${data.set_code ? ' (' + data.set_code + ')' : ''}</span>`);
    }
    if (data.collector_number) {
        badges.push(`<span class="badge bg-secondary-subtle text-secondary-emphasis">#${data.collector_number}</span>`);
    }
    if (data.rarity) {
        badges.push(`<span class="badge bg-warning-subtle text-warning-emphasis"><i class="bi bi-star me-1"></i>${data.rarity}</span>`);
    }
    if (data.language) {
        const langLabel = LANGUAGE_LABELS[data.language] || data.language.toUpperCase();
        badges.push(`<span class="badge bg-info-subtle text-info-emphasis"><i class="bi bi-translate me-1"></i>${langLabel}</span>`);
    }
    if (data.card_type) {
        badges.push(`<span class="badge bg-light text-dark border">${data.card_type}</span>`);
    }
    if (data.serial_number) {
        badges.push(`<span class="badge bg-dark-subtle text-dark-emphasis"><i class="bi bi-upc-scan me-1"></i>${data.serial_number}</span>`);
    }
    metaEl.innerHTML = badges.join('');
}

function renderCenteringDiagram(data) {
    const el = document.getElementById('grade-centering-detail');
    if (!el) return;

    if (!data.centering_ratio_lr || !data.centering_ratio_tb) {
        el.innerHTML = '<div class="text-center text-muted small">No centering data</div>';
        return;
    }

    const [lrLeft, lrRight] = data.centering_ratio_lr.split('/').map(Number);
    const [tbTop, tbBottom] = data.centering_ratio_tb.split('/').map(Number);
    const score = data.centering_score || 0;

    // Border pixel measurements from grading details
    const details = data.centering_details || {};
    const bLeft = details.border_left || 0;
    const bRight = details.border_right || 0;
    const bTop = details.border_top || 0;
    const bBottom = details.border_bottom || 0;

    // PSA-style proportional border diagram
    const sz = 160;
    const pad = 15;
    const cardW = sz - pad * 2;
    const cardH = cardW * 1.4; // Card aspect ratio
    const svgH = cardH + pad * 2;

    // Calculate proportional border widths for the diagram
    const maxBorder = 20; // max visual border width in SVG
    const totalLR = bLeft + bRight || 100;
    const totalTB = bTop + bBottom || 100;
    const vLeft = Math.max(3, (bLeft / totalLR) * maxBorder * 2);
    const vRight = Math.max(3, (bRight / totalLR) * maxBorder * 2);
    const vTop = Math.max(3, (bTop / totalTB) * maxBorder * 2);
    const vBottom = Math.max(3, (bBottom / totalTB) * maxBorder * 2);

    // Colors based on balance
    const lrBalance = Math.abs(lrLeft - 50);
    const tbBalance = Math.abs(tbTop - 50);
    const lrColor = lrBalance <= 5 ? '#22c55e' : lrBalance <= 10 ? '#3b82f6' : lrBalance <= 15 ? '#f59e0b' : '#ef4444';
    const tbColor = tbBalance <= 5 ? '#22c55e' : tbBalance <= 10 ? '#3b82f6' : tbBalance <= 15 ? '#f59e0b' : '#ef4444';

    // Artwork area (inner card)
    const artX = pad + vLeft;
    const artY = pad + vTop;
    const artW = cardW - vLeft - vRight;
    const artH = cardH - vTop - vBottom;

    el.innerHTML = `
        <div class="d-flex gap-3 align-items-start">
            <!-- PSA-Style Border Diagram -->
            <div>
                <svg width="${sz}" height="${svgH}" viewBox="0 0 ${sz} ${svgH}"
                     style="border:1px solid var(--bs-border-color);border-radius:8px;background:var(--bs-tertiary-bg);">
                    <!-- Card outline -->
                    <rect x="${pad}" y="${pad}" width="${cardW}" height="${cardH}" rx="4"
                          fill="none" stroke="var(--bs-border-color)" stroke-width="1.5"/>

                    <!-- Left border (filled proportionally) -->
                    <rect x="${pad}" y="${pad}" width="${vLeft}" height="${cardH}" rx="4"
                          fill="${lrColor}" opacity="0.2"/>
                    <!-- Right border -->
                    <rect x="${pad + cardW - vRight}" y="${pad}" width="${vRight}" height="${cardH}" rx="4"
                          fill="${lrColor}" opacity="0.2"/>
                    <!-- Top border -->
                    <rect x="${pad}" y="${pad}" width="${cardW}" height="${vTop}" rx="4"
                          fill="${tbColor}" opacity="0.2"/>
                    <!-- Bottom border -->
                    <rect x="${pad}" y="${pad + cardH - vBottom}" width="${cardW}" height="${vBottom}" rx="4"
                          fill="${tbColor}" opacity="0.2"/>

                    <!-- Artwork area outline -->
                    <rect x="${artX}" y="${artY}" width="${artW}" height="${artH}" rx="2"
                          fill="none" stroke="var(--bs-secondary-color)" stroke-width="0.5" stroke-dasharray="3,3"/>

                    <!-- Center crosshair -->
                    <line x1="${sz/2}" y1="${pad + 5}" x2="${sz/2}" y2="${pad + cardH - 5}"
                          stroke="var(--bs-secondary-color)" stroke-width="0.5" stroke-dasharray="2,4"/>
                    <line x1="${pad + 5}" y1="${svgH/2}" x2="${pad + cardW - 5}" y2="${svgH/2}"
                          stroke="var(--bs-secondary-color)" stroke-width="0.5" stroke-dasharray="2,4"/>

                    <!-- Border measurement labels -->
                    <text x="${pad + vLeft/2}" y="${svgH/2}" text-anchor="middle" font-size="8"
                          fill="${lrColor}" font-weight="bold" transform="rotate(-90,${pad + vLeft/2},${svgH/2})">${bLeft}px</text>
                    <text x="${pad + cardW - vRight/2}" y="${svgH/2}" text-anchor="middle" font-size="8"
                          fill="${lrColor}" font-weight="bold" transform="rotate(90,${pad + cardW - vRight/2},${svgH/2})">${bRight}px</text>
                    <text x="${sz/2}" y="${pad + vTop - 2}" text-anchor="middle" font-size="8"
                          fill="${tbColor}" font-weight="bold">${bTop}px</text>
                    <text x="${sz/2}" y="${pad + cardH - 2}" text-anchor="middle" font-size="8"
                          fill="${tbColor}" font-weight="bold">${bBottom}px</text>
                </svg>
            </div>

            <!-- Centering Stats -->
            <div class="flex-grow-1">
                <div class="mb-2">
                    <div class="d-flex justify-content-between align-items-center mb-1">
                        <span class="text-muted small">Left / Right</span>
                        <span class="fw-bold" style="color:${lrColor}">${data.centering_ratio_lr}</span>
                    </div>
                    <div class="progress" style="height:6px;">
                        <div class="progress-bar" style="width:${lrLeft}%;background:${lrColor};"></div>
                    </div>
                </div>
                <div class="mb-2">
                    <div class="d-flex justify-content-between align-items-center mb-1">
                        <span class="text-muted small">Top / Bottom</span>
                        <span class="fw-bold" style="color:${tbColor}">${data.centering_ratio_tb}</span>
                    </div>
                    <div class="progress" style="height:6px;">
                        <div class="progress-bar" style="width:${tbTop}%;background:${tbColor};"></div>
                    </div>
                </div>
                <div class="d-flex justify-content-between align-items-center mb-2">
                    <span class="text-muted small">Score</span>
                    ${createGradeBadge(score, 'sm')}
                </div>
                ${bLeft ? `
                <div class="small text-muted mt-1 border-top pt-1">
                    <div class="d-flex justify-content-between">
                        <span>L: ${bLeft}px</span><span>R: ${bRight}px</span>
                    </div>
                    <div class="d-flex justify-content-between">
                        <span>T: ${bTop}px</span><span>B: ${bBottom}px</span>
                    </div>
                </div>` : ''}
            </div>
        </div>
    `;

    // Add centering overlay to the card image viewer
    _addCenteringOverlayToViewer(bLeft, bRight, bTop, bBottom, lrLeft, tbTop);
}

function _addCenteringOverlayToViewer(bLeft, bRight, bTop, bBottom, lrLeft, tbTop) {
    // Add centering guide lines on the card image via the viewer
    if (!window._gradeViewer || !bLeft) return;

    const viewer = window._gradeViewer;
    // Store centering data for toggle
    viewer._centeringData = { bLeft, bRight, bTop, bBottom, lrLeft, tbTop };

    // Add toggle button if not already present
    if (!document.getElementById('btn-centering-overlay')) {
        const toolbar = document.querySelector('.card-image-toolbar, .btn-group');
        if (toolbar) {
            const btn = document.createElement('button');
            btn.id = 'btn-centering-overlay';
            btn.className = 'btn btn-outline-secondary btn-sm';
            btn.innerHTML = '<i class="bi bi-grid-3x3"></i> Centering';
            btn.title = 'Toggle centering guides';
            btn.addEventListener('click', () => {
                btn.classList.toggle('active');
                if (btn.classList.contains('active')) {
                    viewer.addCenteringOverlay(bLeft, bRight, bTop, bBottom);
                } else {
                    viewer.removeCenteringOverlay();
                }
            });
            toolbar.appendChild(btn);
        }
    }
}

function renderGradeCaps(caps) {
    const card = document.getElementById('grade-caps-card');
    const body = document.getElementById('grade-caps-body');
    if (!card || !body) return;

    if (!caps || caps.length === 0) {
        card.style.display = 'none';
        return;
    }

    const reasonMap = {
        'defect_hard_cap': 'Defect severity limit',
        'centering_cap': 'Centering out of tolerance',
    };

    card.style.display = '';
    body.innerHTML = `
        <div class="list-group list-group-flush">
            ${caps.map(c => `
                <div class="list-group-item d-flex justify-content-between align-items-center py-2 px-3">
                    <div>
                        <div class="small fw-semibold text-danger">
                            <i class="bi bi-arrow-down-circle me-1"></i>Capped at ${c.cap?.toFixed(1) || '?'}
                        </div>
                        <div class="text-muted" style="font-size:0.7rem;">
                            ${reasonMap[c.reason] || c.reason?.replace(/_/g, ' ') || 'Unknown'}
                            ${c.original_score ? ' (was ' + c.original_score.toFixed(2) + ')' : ''}
                        </div>
                    </div>
                    ${createGradeBadge(c.cap || 0, 'sm')}
                </div>
            `).join('')}
        </div>
    `;
}

async function loadAuthenticityStatus(cardId) {
    const card = document.getElementById('grade-auth-card');
    if (!card) return;

    try {
        const data = await api.get(`/authenticity/${cardId}`);
        card.style.display = '';

        const badgeEl = document.getElementById('grade-auth-badge');
        if (badgeEl) badgeEl.innerHTML = createAuthBadge(data.overall_status);

        const bodyEl = document.getElementById('grade-auth-body');
        if (bodyEl) {
            const confPct = Math.round((data.confidence || 0) * 100);
            const confColor = confPct >= 80 ? 'bg-success' : confPct >= 60 ? 'bg-warning' : 'bg-danger';
            bodyEl.innerHTML = `
                <div class="d-flex justify-content-between align-items-center mb-2">
                    <span class="small text-muted">Checks</span>
                    <span class="small">
                        <span class="text-success fw-semibold">${data.checks_passed || 0} passed</span> /
                        <span class="text-danger fw-semibold">${data.checks_failed || 0} failed</span>
                        <span class="text-muted"> of ${data.checks_total || 0}</span>
                    </span>
                </div>
                <div class="d-flex justify-content-between align-items-center mb-1">
                    <span class="small text-muted">Confidence</span>
                    <span class="small fw-semibold">${confPct}%</span>
                </div>
                <div class="progress" style="height:5px;">
                    <div class="progress-bar ${confColor}" style="width:${confPct}%"></div>
                </div>
            `;
        }
    } catch {
        card.style.display = 'none';
    }
}

function renderDefectSeveritySummary(defects) {
    const el = document.getElementById('grade-severity-summary');
    if (!el) return;

    const real = defects.filter(d => !d.is_noise);
    if (real.length === 0) { el.innerHTML = ''; return; }

    const counts = { minor: 0, moderate: 0, major: 0, severe: 0 };
    for (const d of real) {
        if (counts[d.severity] !== undefined) counts[d.severity]++;
    }

    const colorMap = { minor: '#ffc107', moderate: '#fd7e14', major: '#dc3545', severe: '#8b0000' };
    const pills = Object.entries(counts)
        .filter(([, count]) => count > 0)
        .map(([sev, count]) =>
            `<span class="badge rounded-pill text-white" style="background:${colorMap[sev]};">${count} ${sev}</span>`
        );

    el.innerHTML = `<div class="d-flex flex-wrap gap-1 mb-2">${pills.join('')}</div>`;
}

function renderZoneHeatmap(defects) {
    const card = document.getElementById('grade-zone-card');
    const el = document.getElementById('grade-zone-summary');
    if (!card || !el) return;

    const real = defects.filter(d => !d.is_noise);
    if (real.length === 0) { card.style.display = 'none'; return; }

    const zones = {};
    for (const d of real) {
        const zone = d.details?.zone || 'general';
        zones[zone] = (zones[zone] || 0) + 1;
    }

    if (Object.keys(zones).length === 0) { card.style.display = 'none'; return; }

    const zoneMeta = {
        artwork_center: { label: 'Artwork Center', icon: 'bi-image', color: '#ef4444' },
        border:         { label: 'Border',         icon: 'bi-border-outer', color: '#f59e0b' },
        text_box:       { label: 'Text Box',       icon: 'bi-card-text', color: '#3b82f6' },
        general:        { label: 'General',         icon: 'bi-grid', color: '#94a3b8' },
    };

    card.style.display = '';
    el.innerHTML = Object.entries(zones).map(([zone, count]) => {
        const meta = zoneMeta[zone] || zoneMeta.general;
        return `
            <div class="d-flex align-items-center gap-2 py-1">
                <i class="bi ${meta.icon}" style="color:${meta.color};font-size:0.9rem;"></i>
                <span class="small flex-grow-1">${meta.label}</span>
                <span class="badge rounded-pill text-white" style="background:${meta.color};min-width:24px;">${count}</span>
            </div>`;
    }).join('');
}

async function loadPopulation(pokewallet_card_id) {
    const card = document.getElementById('grade-population-card');
    if (!card || !pokewallet_card_id) return;

    try {
        const data = await api.get(`/grading/population/${pokewallet_card_id}`);
        if (!data.total_graded || data.total_graded === 0) {
            card.style.display = 'none';
            return;
        }

        card.style.display = '';
        const body = document.getElementById('grade-population-body');
        if (!body) return;

        const maxCount = Math.max(...Object.values(data.distribution));
        const bars = Object.entries(data.distribution)
            .sort(([a], [b]) => parseFloat(b) - parseFloat(a))
            .map(([grade, count]) => {
                const pct = (count / maxCount) * 100;
                return `
                    <div class="d-flex align-items-center gap-2 mb-1">
                        <span class="text-end small fw-semibold" style="min-width:30px;">${parseFloat(grade).toFixed(1)}</span>
                        <div class="progress flex-grow-1" style="height:12px;">
                            <div class="progress-bar bg-primary" style="width:${pct}%"></div>
                        </div>
                        <span class="small text-muted" style="min-width:25px;">${count}</span>
                    </div>`;
            }).join('');

        body.innerHTML = `
            <div class="small text-muted mb-2">Total graded: <span class="fw-semibold">${data.total_graded}</span></div>
            ${bars}
        `;
    } catch {
        card.style.display = 'none';
    }
}

function renderConfidence(confidence) {
    const card = document.getElementById('grade-confidence-card');
    const val = document.getElementById('grade-confidence-value');
    const bar = document.getElementById('grade-confidence-bar');
    if (!card) return;

    if (confidence == null) {
        card.style.display = 'none';
        return;
    }

    card.style.display = '';
    const pct = Math.round(confidence);
    if (val) val.textContent = pct + '%';
    if (bar) {
        bar.style.width = pct + '%';
        bar.className = 'progress-bar ' + (pct >= 80 ? 'bg-success' : pct >= 60 ? 'bg-warning' : 'bg-danger');
    }
}

async function loadGradeHistory(cardId) {
    const card = document.getElementById('grade-history-card');
    const list = document.getElementById('grade-history-list');
    const count = document.getElementById('grade-history-count');
    if (!card || !list) return;

    try {
        const data = await api.get(`/grading/history/${cardId}`);
        if (!data.history || data.history.length === 0) {
            card.style.display = 'none';
            return;
        }
        card.style.display = '';
        if (count) count.textContent = data.history.length;
        list.innerHTML = data.history.map(h => {
            const date = h.graded_at ? new Date(h.graded_at).toLocaleString() : 'Unknown';
            return `<div class="list-group-item d-flex justify-content-between align-items-center py-1 px-3">
                <small class="text-muted">${date}</small>
                <span class="fw-semibold">${h.final_grade?.toFixed(1) || '--'}</span>
                <small class="text-muted">${h.sensitivity_profile || ''}</small>
            </div>`;
        }).join('');
    } catch {
        card.style.display = 'none';
    }
}

function renderAIReview(aiReview) {
    const card = document.getElementById('grade-ai-review-card');
    const body = document.getElementById('grade-ai-review-body');
    if (!card || !body) return;

    if (!aiReview) {
        card.style.display = 'none';
        return;
    }

    card.style.display = '';
    body.innerHTML = `
        <div class="d-flex align-items-center justify-content-between mb-2">
            <span class="fw-semibold">${aiReview.agrees_with_grade
                ? '<i class="bi bi-check-circle text-success me-1"></i>Agrees with grade'
                : '<i class="bi bi-exclamation-circle text-warning me-1"></i>Suggests adjustment'}</span>
            ${aiReview.suggested_grade ? `<span class="badge bg-warning text-dark">Suggested: ${aiReview.suggested_grade}</span>` : ''}
        </div>
        <p class="small text-muted mb-2">${aiReview.overall_assessment || ''}</p>
        ${aiReview.missed_defects?.length ? `<div class="small"><strong>Possible missed:</strong> ${aiReview.missed_defects.join(', ')}</div>` : ''}
        ${aiReview.over_penalised?.length ? `<div class="small"><strong>Over-penalised:</strong> ${aiReview.over_penalised.join(', ')}</div>` : ''}
        <div class="mt-1"><small class="text-muted">Confidence: ${((aiReview.confidence || 0) * 100).toFixed(0)}%</small></div>
    `;
}

function renderEmptyGrade() {
    const badgeEl = document.getElementById('grade-badge-container');
    if (badgeEl) badgeEl.innerHTML = createGradeBadge(0, 'lg');

    const nameLabel = document.getElementById('grade-name-label');
    if (nameLabel) nameLabel.textContent = '';

    const summaryEl = document.getElementById('grade-summary-text');
    if (summaryEl) summaryEl.textContent = 'No grade calculated yet';

    const statusEl = document.getElementById('grade-status-badge');
    if (statusEl) statusEl.innerHTML = createStatusBadge('pending');

    // Card info
    const cardInfoEl = document.getElementById('grade-card-info');
    if (cardInfoEl) cardInfoEl.style.display = 'none';

    // Sub-grades
    const subEl = document.getElementById('grade-sub-grades');
    if (subEl) subEl.innerHTML = buildSubGradeRows(null);

    // Grade caps
    const capsCard = document.getElementById('grade-caps-card');
    if (capsCard) capsCard.style.display = 'none';

    // Centering
    const centEl = document.getElementById('grade-centering-detail');
    if (centEl) centEl.innerHTML = '<div class="text-center text-muted small">No centering data</div>';

    // Authenticity
    const authCard = document.getElementById('grade-auth-card');
    if (authCard) authCard.style.display = 'none';

    // Confidence
    const confCard = document.getElementById('grade-confidence-card');
    if (confCard) confCard.style.display = 'none';

    // History
    const histCard = document.getElementById('grade-history-card');
    if (histCard) histCard.style.display = 'none';

    // Population
    const popCard = document.getElementById('grade-population-card');
    if (popCard) popCard.style.display = 'none';

    // AI review
    const aiCard = document.getElementById('grade-ai-review-card');
    if (aiCard) aiCard.style.display = 'none';

    // Zone summary
    const zoneCard = document.getElementById('grade-zone-card');
    if (zoneCard) zoneCard.style.display = 'none';

    // Severity summary
    const sevEl = document.getElementById('grade-severity-summary');
    if (sevEl) sevEl.innerHTML = '';

    renderDefectList([]);
    enableActionButtons(false);
}

function renderDefectList(defects) {
    const listEl = document.getElementById('grade-defect-list');
    const countEl = document.getElementById('grade-defect-count');

    // Filter out noise
    const real = defects.filter(d => !d.is_noise);

    if (countEl) countEl.textContent = real.length;

    if (!listEl) return;

    if (real.length === 0) {
        listEl.innerHTML = createEmptyState('No defects detected', 'bi-check-circle');
        return;
    }

    listEl.innerHTML = real.map((d, i) => {
        const sevClass = SEVERITY_CLASS_MAP[d.severity] || 'defect-minor';
        const sevColor = {
            minor: '#ffc107',
            moderate: '#fd7e14',
            major: '#dc3545',
            severe: '#8b0000',
        }[d.severity] || '#6c757d';

        return `
            <button class="list-group-item list-group-item-action d-flex align-items-center gap-2 defect-item"
                    data-defect-index="${i}"
                    data-bbox-x="${d.bbox?.x || 0}" data-bbox-y="${d.bbox?.y || 0}"
                    data-bbox-w="${d.bbox?.w || 0}" data-bbox-h="${d.bbox?.h || 0}">
                <span class="badge rounded-pill" style="background:${sevColor};min-width:70px;">
                    ${d.severity}
                </span>
                <div class="flex-grow-1">
                    <div class="fw-semibold small">${d.defect_type}</div>
                    <div class="text-muted" style="font-size:0.7rem;">${d.location || d.category}</div>
                </div>
                <div class="text-end">
                    <div class="small text-danger">-${d.score_impact?.toFixed(1) || '?'}</div>
                    ${d.confidence ? `<div class="text-muted" style="font-size:0.6rem;">${(d.confidence * 100).toFixed(0)}%</div>` : ''}
                </div>
                <i class="bi bi-zoom-in text-muted"></i>
            </button>
        `;
    }).join('');

    // Attach click-to-zoom handlers
    listEl.querySelectorAll('.defect-item').forEach(el => {
        el.addEventListener('click', () => {
            const x = parseInt(el.dataset.bboxX) || 0;
            const y = parseInt(el.dataset.bboxY) || 0;
            const w = parseInt(el.dataset.bboxW) || 50;
            const h = parseInt(el.dataset.bboxH) || 50;
            if (viewer && w > 0 && h > 0) {
                // Add padding around the defect
                const pad = Math.max(w, h) * 0.5;
                viewer.zoomToRegion(
                    Math.max(0, x - pad), Math.max(0, y - pad),
                    w + pad * 2, h + pad * 2,
                );
            }
        });
    });
}

function addDefectOverlays(defects) {
    if (!viewer) return;
    viewer.clearOverlays();

    // Filter out noise and defects without bounding boxes, and match current side
    const real = defects.filter(d => {
        if (d.is_noise || !d.bbox) return false;
        // If defect has a side field, only show defects for the current side
        if (d.side && d.side !== currentSide) return false;
        return true;
    });

    for (const d of real) {
        const bbox = d.bbox;
        if (!bbox || (!bbox.w && !bbox.h)) continue;

        const className = SEVERITY_CLASS_MAP[d.severity] || 'defect-minor';
        const label = `${d.defect_type} (${d.severity})`;

        viewer.addOverlay(bbox.x, bbox.y, bbox.w, bbox.h, className, label, d.id);
    }
}

// ----- Actions -----

async function runGrading() {
    if (!currentCardId) return;

    const profile = document.getElementById('grade-profile-select')?.value || 'standard';
    const runBtn = document.getElementById('grade-run-btn');

    try {
        if (runBtn) {
            runBtn.disabled = true;
            runBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Grading...';
        }

        const result = await api.post(`/grading/${currentCardId}/run`, { profile });
        showToast(`Grading complete: ${result.final_grade}`, 'success');

        // Reload grade data
        await loadCard(currentCardId);
    } catch (err) {
        showToast(`Grading failed: ${err.message}`, 'error');
    } finally {
        if (runBtn) {
            runBtn.disabled = false;
            runBtn.innerHTML = '<i class="bi bi-cpu me-1"></i>Run Grading';
        }
    }
}

async function approveGrade() {
    if (!currentCardId) return;

    try {
        const result = await api.post(`/grading/${currentCardId}/approve`, { operator: 'operator' });
        showToast(`Grade ${result.final_grade} approved`, 'success');
        await loadCard(currentCardId);
    } catch (err) {
        showToast(`Approval failed: ${err.message}`, 'error');
    }
}

function openOverrideModal() {
    const currentEl = document.getElementById('override-current-grade');
    if (currentEl && currentGradeData) {
        currentEl.textContent = currentGradeData.final_grade?.toFixed(1) || '--';
    }

    // Pre-select the current grade in the dropdown
    const select = document.getElementById('override-grade-select');
    if (select && currentGradeData?.final_grade) {
        select.value = currentGradeData.final_grade.toString();
    }

    // Clear reason
    const reason = document.getElementById('override-reason');
    if (reason) reason.value = '';

    // Show modal
    const modal = document.getElementById('grade-override-modal');
    if (modal && typeof bootstrap !== 'undefined') {
        const bsModal = new bootstrap.Modal(modal);
        bsModal.show();
    }
}

async function submitOverride() {
    if (!currentCardId) return;

    const grade = parseFloat(document.getElementById('override-grade-select')?.value);
    const reason = document.getElementById('override-reason')?.value?.trim();

    if (!reason || reason.length < 5) {
        showToast('Please provide a reason (minimum 5 characters)', 'warning');
        return;
    }

    try {
        const result = await api.post(`/grading/${currentCardId}/override`, {
            grade,
            reason,
            operator: 'operator',
        });

        showToast(`Grade overridden to ${result.final_grade}`, 'success');

        // Close modal
        const modal = document.getElementById('grade-override-modal');
        if (modal && typeof bootstrap !== 'undefined') {
            const bsModal = bootstrap.Modal.getInstance(modal);
            bsModal?.hide();
        }

        await loadCard(currentCardId);
    } catch (err) {
        showToast(`Override failed: ${err.message}`, 'error');
    }
}

async function requestRescan() {
    if (!currentCardId) return;

    const btn = document.getElementById('grade-rescan-btn');
    try {
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Rescanning...';
        }
        const result = await api.post(`/scan/${currentCardId}/rescan`);
        showToast(`Rescan complete — new grade: ${result.final_grade || 'pending'}`, 'success');
        await loadCard(currentCardId);
    } catch (err) {
        showToast(`Rescan failed: ${err.message}`, 'error');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '<i class="bi bi-arrow-return-left me-2"></i>Request Rescan';
        }
    }
}

function handleOverlayClick(overlay) {
    if (!overlay) return;
    // Zoom to the defect
    viewer?.zoomToRegion(overlay.x, overlay.y, overlay.w, overlay.h);
}

// ----- UI Helpers -----

function enableImageControls(enabled) {
    const ids = ['grade-reset-zoom', 'grade-toggle-overlays', 'grade-zoom-in', 'grade-zoom-out'];
    for (const id of ids) {
        const el = document.getElementById(id);
        if (el) el.disabled = !enabled;
    }
    // Flip button depends on back image availability, not just enabled state
    const flipBtn = document.getElementById('grade-toggle-side');
    if (flipBtn) flipBtn.disabled = !enabled || !currentBackUrl;
}

function enableActionButtons(enabled) {
    const ids = ['grade-approve-btn', 'grade-override-btn', 'grade-rescan-btn'];
    for (const id of ids) {
        const el = document.getElementById(id);
        if (el) el.disabled = !enabled;
    }
    // PDF report link
    const pdfBtn = document.getElementById('grade-pdf-btn');
    if (pdfBtn) {
        if (enabled && currentCardId) {
            pdfBtn.href = `/api/reports/card/${currentCardId}/pdf`;
            pdfBtn.style.pointerEvents = '';
            pdfBtn.style.opacity = '1';
        } else {
            pdfBtn.href = '#';
            pdfBtn.style.pointerEvents = 'none';
            pdfBtn.style.opacity = '0.5';
        }
    }
}

function enableRunButton(enabled) {
    const el = document.getElementById('grade-run-btn');
    if (el) el.disabled = !enabled;
}
