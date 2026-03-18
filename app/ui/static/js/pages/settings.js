/**
 * Settings page module.
 *
 * Full tabbed settings page for calibration, material/jig profiles,
 * scanner, grading, authenticity, API, security, and system.
 */
import { api } from '../api.js';
import { showToast, createLoadingSpinner, createEmptyState, formatDate } from '../components.js';

/* global bootstrap */

// ------------------------------------------------------- Module state
let _container = null;
let _calibrationMatrix = null;  // current generated matrix data

// ------------------------------------------------------- Tab definitions
const TABS = [
    { id: 'scanner',       label: 'Scanner',          icon: 'bi-camera',           desc: 'Hardware & mock mode' },
    { id: 'grading',       label: 'Grading Engine',   icon: 'bi-clipboard-check',  desc: 'Weights & sensitivity' },
    { id: 'authenticity',  label: 'Authenticity',     icon: 'bi-shield-check',     desc: 'Thresholds & auto-approve' },
    { id: 'apikeys',       label: 'API Keys',         icon: 'bi-key',              desc: 'PokeWallet & OpenRouter' },
    { id: 'security',      label: 'Security',         icon: 'bi-lock',             desc: 'Patterns & engraving' },
    { id: 'slab',          label: 'NFC / Printer',    icon: 'bi-box-seam',         desc: 'Tag type & label config' },
    { id: 'system',        label: 'System',           icon: 'bi-pc-display',       desc: 'Storage, logs & database' },
    { id: 'changelog',     label: 'Changelog',        icon: 'bi-clock-history',    desc: 'Platform update history' },
];

// ------------------------------------------------------- Init
export async function init(container) {
    _container = container;
    container.innerHTML = `
        <div class="px-4 py-3">
            <h5 class="mb-3"><i class="bi bi-gear me-2"></i>Settings</h5>
            <div class="row">
                <!-- Sidebar Navigation -->
                <div class="col-lg-3 mb-4">
                    <div class="card">
                        <div class="card-body p-2">
                            <div class="nav flex-column nav-pills" id="settings-tabs" role="tablist">
                                ${TABS.map((t, i) => `
                                    <button class="nav-link text-start ${i === 0 ? 'active' : ''}"
                                            id="tab-btn-${t.id}" type="button"
                                            data-bs-toggle="pill" data-bs-target="#tab-${t.id}"
                                            role="tab" aria-controls="tab-${t.id}" aria-selected="${i === 0}"
                                            style="padding: 8px 12px;">
                                        <div class="d-flex align-items-center">
                                            <i class="bi ${t.icon} me-2" style="width:18px;"></i>
                                            <div>
                                                <div class="fw-medium" style="font-size:0.85rem;">${t.label}</div>
                                                <div class="text-muted" style="font-size:0.7rem; line-height:1.2;">${t.desc}</div>
                                            </div>
                                        </div>
                                    </button>
                                `).join('')}
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Tab Content -->
                <div class="col-lg-9 mb-4">
                    <div class="tab-content" id="settings-tab-content">
                        ${TABS.map((t, i) => `
                            <div class="tab-pane fade ${i === 0 ? 'show active' : ''}"
                                 id="tab-${t.id}" role="tabpanel">
                                ${createLoadingSpinner('Loading...')}
                            </div>
                        `).join('')}
                    </div>
                </div>
            </div>
        </div>
    `;

    // Load the first tab immediately, others on demand
    await loadScannerTab();

    // Lazy-load tabs when shown
    const tabEls = container.querySelectorAll('[data-bs-toggle="pill"]');
    tabEls.forEach(btn => {
        btn.addEventListener('shown.bs.tab', (e) => {
            const targetId = e.target.getAttribute('data-bs-target').replace('#tab-', '');
            loadTab(targetId);
        });
    });
}

export function destroy() {
    _container = null;
    _calibrationMatrix = null;
}

// ------------------------------------------------------- Tab loader
const _loadedTabs = new Set();

async function loadTab(tabId) {
    if (_loadedTabs.has(tabId)) return;
    _loadedTabs.add(tabId);
    try {
        switch (tabId) {
            case 'scanner':       await loadScannerTab(); break;
            case 'grading':       await loadGradingTab(); break;
            case 'authenticity':  await loadAuthenticityTab(); break;
            case 'apikeys':       await loadApiTab(); break;
            case 'security':      await loadSecurityTab(); break;
            case 'slab':          await loadSlabTab(); break;
            case 'system':        await loadSystemTab(); break;
            case 'changelog':     await loadChangelogTab(); break;
        }
    } catch (err) {
        const pane = _container.querySelector(`#tab-${tabId}`);
        if (pane) pane.innerHTML = `<div class="alert alert-danger m-3">Failed to load: ${err.message}</div>`;
    }
}

// ------------------------------------------------------- Scanner Tab
async function loadScannerTab() {
    const data = await api.get('/settings/scanner');
    const pane = _container.querySelector('#tab-scanner');
    pane.innerHTML = `
        <div class="card">
            <div class="card-header"><h6 class="mb-0">Scanner Settings</h6></div>
            <div class="card-body">
                <div class="row">
                    <div class="col-md-6 mb-3">
                        <div class="form-check form-switch">
                            <input class="form-check-input" type="checkbox" id="scannerMockMode"
                                   ${data.mock_mode ? 'checked' : ''}>
                            <label class="form-check-label" for="scannerMockMode">
                                Mock Scanner Mode
                            </label>
                        </div>
                        <small class="text-muted">When enabled, uses sample images instead of real scanner.</small>
                    </div>
                    <div class="col-md-6 mb-3">
                        <label class="form-label">Default DPI</label>
                        <select class="form-select" id="scannerDpi">
                            ${[150, 300, 600, 1200].map(d => `
                                <option value="${d}" ${data.default_dpi === d ? 'selected' : ''}>${d} DPI</option>
                            `).join('')}
                        </select>
                    </div>
                    <div class="col-md-6 mb-3">
                        <label class="form-label">Mock Image Directory</label>
                        <input type="text" class="form-control" value="${data.mock_image_dir || ''}" disabled>
                        <small class="text-muted">Read-only. Configure via RKT_SCANNER_MOCK_IMAGE_DIR env var.</small>
                    </div>
                </div>
                <hr>
                <button class="btn btn-primary" id="btnSaveScanner">
                    <i class="bi bi-save me-1"></i>Save Scanner Settings
                </button>
            </div>
        </div>
    `;
    pane.querySelector('#btnSaveScanner').addEventListener('click', async () => {
        try {
            await api.put('/settings/scanner', {
                mock_mode: pane.querySelector('#scannerMockMode').checked,
                default_dpi: parseInt(pane.querySelector('#scannerDpi').value),
            });
            showToast('Scanner settings saved.', 'success');
        } catch (err) {
            showToast('Failed to save scanner settings: ' + err.message, 'error');
        }
    });
    _loadedTabs.add('scanner');
}

// ------------------------------------------------------- Grading Tab
async function loadGradingTab() {
    const data = await api.get('/settings/grading');
    const pane = _container.querySelector('#tab-grading');
    const profiles = data.available_profiles || [];

    pane.innerHTML = `
        <div class="card">
            <div class="card-header"><h6 class="mb-0">Grading Settings</h6></div>
            <div class="card-body">
                <h6 class="text-muted mb-3">Sub-Grade Weights</h6>
                <p class="small text-muted mb-3">Weights must sum to 1.00. Adjust the relative importance of each grading factor.</p>
                <div class="row">
                    ${['centering', 'corners', 'edges', 'surface'].map(k => `
                        <div class="col-md-6 mb-3">
                            <label class="form-label d-flex justify-content-between">
                                <span>${k.charAt(0).toUpperCase() + k.slice(1)} Weight</span>
                                <span class="badge bg-primary" id="label-${k}">${data[k + '_weight']}</span>
                            </label>
                            <input type="range" class="form-range weight-slider" id="weight-${k}"
                                   min="0" max="1" step="0.01" value="${data[k + '_weight']}"
                                   data-key="${k}">
                        </div>
                    `).join('')}
                </div>
                <div class="mb-3">
                    <span class="small">Total: <strong id="weightTotal">${
                        (data.centering_weight + data.corners_weight + data.edges_weight + data.surface_weight).toFixed(2)
                    }</strong></span>
                    <span id="weightWarning" class="small text-danger ms-2 d-none">Weights must sum to 1.00</span>
                </div>
                <hr>
                <div class="row">
                    <div class="col-md-6 mb-3">
                        <label class="form-label">Sensitivity Profile</label>
                        <select class="form-select" id="gradingSensitivity">
                            ${profiles.map(p => `
                                <option value="${p.name}" ${data.sensitivity_profile === p.name ? 'selected' : ''}>
                                    ${p.label} -- ${p.description}
                                </option>
                            `).join('')}
                        </select>
                    </div>
                    <div class="col-md-6 mb-3">
                        <label class="form-label d-flex justify-content-between">
                            <span>Noise Threshold (px)</span>
                            <span class="badge bg-secondary" id="label-noise">${data.noise_threshold_px}</span>
                        </label>
                        <input type="range" class="form-range" id="gradingNoise"
                               min="1" max="10" step="1" value="${data.noise_threshold_px}">
                    </div>
                </div>
                <hr>
                <button class="btn btn-primary" id="btnSaveGrading">
                    <i class="bi bi-save me-1"></i>Save Grading Settings
                </button>
            </div>
        </div>
    `;

    // Weight slider live update
    const sliders = pane.querySelectorAll('.weight-slider');
    const updateWeightDisplay = () => {
        let total = 0;
        sliders.forEach(s => {
            const key = s.dataset.key;
            const val = parseFloat(s.value);
            pane.querySelector(`#label-${key}`).textContent = val.toFixed(2);
            total += val;
        });
        const totalEl = pane.querySelector('#weightTotal');
        const warnEl = pane.querySelector('#weightWarning');
        totalEl.textContent = total.toFixed(2);
        if (Math.abs(total - 1.0) > 0.01) {
            totalEl.classList.add('text-danger');
            warnEl.classList.remove('d-none');
        } else {
            totalEl.classList.remove('text-danger');
            warnEl.classList.add('d-none');
        }
    };
    sliders.forEach(s => s.addEventListener('input', updateWeightDisplay));

    // Noise slider label
    pane.querySelector('#gradingNoise').addEventListener('input', (e) => {
        pane.querySelector('#label-noise').textContent = e.target.value;
    });

    pane.querySelector('#btnSaveGrading').addEventListener('click', async () => {
        try {
            await api.put('/settings/grading', {
                centering_weight: parseFloat(pane.querySelector('#weight-centering').value),
                corners_weight: parseFloat(pane.querySelector('#weight-corners').value),
                edges_weight: parseFloat(pane.querySelector('#weight-edges').value),
                surface_weight: parseFloat(pane.querySelector('#weight-surface').value),
                sensitivity_profile: pane.querySelector('#gradingSensitivity').value,
                noise_threshold_px: parseInt(pane.querySelector('#gradingNoise').value),
            });
            showToast('Grading settings saved.', 'success');
        } catch (err) {
            showToast('Failed to save: ' + err.message, 'error');
        }
    });
}

// ------------------------------------------------------- Authenticity Tab
async function loadAuthenticityTab() {
    const data = await api.get('/settings/authenticity');
    const pane = _container.querySelector('#tab-authenticity');
    pane.innerHTML = `
        <div class="card">
            <div class="card-header"><h6 class="mb-0">Authenticity Settings</h6></div>
            <div class="card-body">
                <p class="small text-muted mb-3">Configure the confidence thresholds for automatic authenticity decisions.</p>
                <div class="row">
                    <div class="col-md-6 mb-3">
                        <label class="form-label d-flex justify-content-between">
                            <span>Auto-Approve Threshold</span>
                            <span class="badge bg-success" id="label-autoApprove">${data.auto_approve_threshold}</span>
                        </label>
                        <input type="range" class="form-range" id="authAutoApprove"
                               min="0" max="1" step="0.01" value="${data.auto_approve_threshold}">
                        <small class="text-muted">Cards above this confidence are auto-approved as authentic.</small>
                    </div>
                    <div class="col-md-6 mb-3">
                        <label class="form-label d-flex justify-content-between">
                            <span>Never Auto-Approve Below</span>
                            <span class="badge bg-warning text-dark" id="label-neverBelow">${data.never_auto_approve_below}</span>
                        </label>
                        <input type="range" class="form-range" id="authNeverBelow"
                               min="0" max="1" step="0.01" value="${data.never_auto_approve_below}">
                        <small class="text-muted">Hard floor: cards below this always require manual review.</small>
                    </div>
                    <div class="col-md-6 mb-3">
                        <label class="form-label d-flex justify-content-between">
                            <span>Suspect Threshold</span>
                            <span class="badge bg-warning text-dark" id="label-suspect">${data.suspect_threshold}</span>
                        </label>
                        <input type="range" class="form-range" id="authSuspect"
                               min="0" max="1" step="0.01" value="${data.suspect_threshold}">
                        <small class="text-muted">Cards below this are flagged as suspect.</small>
                    </div>
                    <div class="col-md-6 mb-3">
                        <label class="form-label d-flex justify-content-between">
                            <span>Reject Threshold</span>
                            <span class="badge bg-danger" id="label-reject">${data.reject_threshold}</span>
                        </label>
                        <input type="range" class="form-range" id="authReject"
                               min="0" max="1" step="0.01" value="${data.reject_threshold}">
                        <small class="text-muted">Cards below this are auto-rejected.</small>
                    </div>
                </div>
                <hr>
                <button class="btn btn-primary" id="btnSaveAuth">
                    <i class="bi bi-save me-1"></i>Save Authenticity Settings
                </button>
            </div>
        </div>
    `;

    // Live label updates
    ['autoApprove', 'neverBelow', 'suspect', 'reject'].forEach(key => {
        const inputId = {autoApprove:'authAutoApprove', neverBelow:'authNeverBelow', suspect:'authSuspect', reject:'authReject'}[key];
        pane.querySelector(`#${inputId}`).addEventListener('input', (e) => {
            pane.querySelector(`#label-${key}`).textContent = parseFloat(e.target.value).toFixed(2);
        });
    });

    pane.querySelector('#btnSaveAuth').addEventListener('click', async () => {
        try {
            await api.put('/settings/authenticity', {
                auto_approve_threshold: parseFloat(pane.querySelector('#authAutoApprove').value),
                suspect_threshold: parseFloat(pane.querySelector('#authSuspect').value),
                reject_threshold: parseFloat(pane.querySelector('#authReject').value),
                never_auto_approve_below: parseFloat(pane.querySelector('#authNeverBelow').value),
            });
            showToast('Authenticity settings saved.', 'success');
        } catch (err) {
            showToast('Failed to save: ' + err.message, 'error');
        }
    });
}

// ------------------------------------------------------- API Tab
async function loadApiTab() {
    const [data, orData, whData] = await Promise.all([
        api.get('/settings/api'),
        api.get('/settings/openrouter'),
        api.get('/settings/webhook'),
    ]);
    const pane = _container.querySelector('#tab-apikeys');
    pane.innerHTML = `
        <div class="card mb-4">
            <div class="card-header"><h6 class="mb-0"><i class="bi bi-credit-card me-2"></i>PokeWallet API Settings</h6></div>
            <div class="card-body">
                <div class="row">
                    <div class="col-md-8 mb-3">
                        <label class="form-label">API Key</label>
                        <div class="input-group">
                            <input type="password" class="form-control" id="apiKey"
                                   placeholder="${data.has_api_key ? data.api_key_masked : 'Enter API key...'}"
                                   value="">
                            <button class="btn btn-outline-secondary" type="button" id="btnToggleApiKey">
                                <i class="bi bi-eye"></i>
                            </button>
                        </div>
                        <small class="text-muted">
                            ${data.has_api_key ? 'Key is set. Enter a new value to replace it, or leave blank to keep current.' : 'No API key configured.'}
                        </small>
                    </div>
                    <div class="col-md-8 mb-3">
                        <label class="form-label">Base URL</label>
                        <input type="url" class="form-control" id="apiBaseUrl" value="${data.base_url}">
                    </div>
                    <div class="col-md-4 mb-3">
                        <label class="form-label">Rate Limit Buffer</label>
                        <input type="number" class="form-control" id="apiRateLimit" value="${data.rate_limit_buffer}" min="0">
                    </div>
                    <div class="col-md-4 mb-3">
                        <label class="form-label">Cache TTL (seconds)</label>
                        <input type="number" class="form-control" id="apiCacheTtl" value="${data.cache_ttl_seconds}" min="0">
                    </div>
                    <div class="col-md-4 mb-3">
                        <label class="form-label">Request Timeout (s)</label>
                        <input type="number" class="form-control" id="apiTimeout" value="${data.request_timeout}" min="1" step="0.5">
                    </div>
                </div>
                <hr>
                <div class="d-flex gap-2">
                    <button class="btn btn-primary" id="btnSaveApi">
                        <i class="bi bi-save me-1"></i>Save PokeWallet Settings
                    </button>
                    <button class="btn btn-outline-secondary" id="btnTestApi">
                        <i class="bi bi-plug me-1"></i>Test Connection
                    </button>
                </div>
            </div>
        </div>

        <div class="card">
            <div class="card-header d-flex justify-content-between align-items-center">
                <h6 class="mb-0"><i class="bi bi-robot me-2"></i>OpenRouter AI Settings</h6>
                <div class="form-check form-switch mb-0">
                    <input class="form-check-input" type="checkbox" id="orEnabled" ${orData.enabled ? 'checked' : ''}>
                    <label class="form-check-label small" for="orEnabled">AI Enabled</label>
                </div>
            </div>
            <div class="card-body">
                <p class="small text-muted mb-3">AI-powered OCR enhancement, card identification disambiguation, and grading second opinion via OpenRouter.ai.</p>
                <div class="row">
                    <div class="col-md-8 mb-3">
                        <label class="form-label">API Key</label>
                        <div class="input-group">
                            <input type="password" class="form-control" id="orApiKey"
                                   placeholder="${orData.has_api_key ? orData.api_key_masked : 'Enter OpenRouter API key...'}"
                                   value="">
                            <button class="btn btn-outline-secondary" type="button" id="btnToggleOrKey">
                                <i class="bi bi-eye"></i>
                            </button>
                        </div>
                        <small class="text-muted">
                            ${orData.has_api_key ? 'Key is set. Enter a new value to replace it.' : 'Get a key at <a href="https://openrouter.ai/keys" target="_blank">openrouter.ai/keys</a>'}
                        </small>
                    </div>
                    <div class="col-md-8 mb-3">
                        <label class="form-label">Model</label>
                        <select class="form-select" id="orModel">
                            <option value="google/gemini-2.0-flash-001" ${orData.model === 'google/gemini-2.0-flash-001' ? 'selected' : ''}>Gemini 2.0 Flash (Recommended)</option>
                            <option value="google/gemini-2.5-flash-preview" ${orData.model === 'google/gemini-2.5-flash-preview' ? 'selected' : ''}>Gemini 2.5 Flash Preview</option>
                            <option value="anthropic/claude-3.5-sonnet" ${orData.model === 'anthropic/claude-3.5-sonnet' ? 'selected' : ''}>Claude 3.5 Sonnet</option>
                            <option value="openai/gpt-4o-mini" ${orData.model === 'openai/gpt-4o-mini' ? 'selected' : ''}>GPT-4o Mini</option>
                        </select>
                        <small class="text-muted">Vision-capable model for card analysis. Flash models are cheapest.</small>
                    </div>
                </div>
                <hr>
                <div class="d-flex gap-2">
                    <button class="btn btn-primary" id="btnSaveOr">
                        <i class="bi bi-save me-1"></i>Save AI Settings
                    </button>
                    <button class="btn btn-outline-secondary" id="btnTestOr">
                        <i class="bi bi-plug me-1"></i>Test Connection
                    </button>
                </div>
                <div id="orTestResult" class="mt-3"></div>
            </div>
        </div>

        <div class="card mt-4">
            <div class="card-header d-flex justify-content-between align-items-center">
                <h6 class="mb-0"><i class="bi bi-broadcast me-2"></i>Webhook Notifications</h6>
                <div class="form-check form-switch mb-0">
                    <input class="form-check-input" type="checkbox" id="whEnabled" ${whData.enabled ? 'checked' : ''}>
                    <label class="form-check-label small" for="whEnabled">Enabled</label>
                </div>
            </div>
            <div class="card-body">
                <p class="small text-muted mb-3">Send HTTP POST notifications when grades are approved, overridden, or authenticity flags are raised.</p>
                <div class="row">
                    <div class="col-md-8 mb-3">
                        <label class="form-label">Webhook URL</label>
                        <input type="url" class="form-control" id="whUrl" value="${whData.url}" placeholder="https://your-server.com/webhook">
                    </div>
                    <div class="col-md-8 mb-3">
                        <label class="form-label">Secret</label>
                        <div class="input-group">
                            <input type="password" class="form-control" id="whSecret"
                                   placeholder="${whData.has_secret ? whData.secret_masked : 'Optional signing secret'}"
                                   value="">
                            <button class="btn btn-outline-secondary" type="button" id="btnToggleWhSecret">
                                <i class="bi bi-eye"></i>
                            </button>
                        </div>
                        <small class="text-muted">Sent as X-Webhook-Secret header for request verification.</small>
                    </div>
                    <div class="col-12 mb-3">
                        <label class="form-label">Events</label>
                        <div class="d-flex flex-wrap gap-3">
                            <div class="form-check">
                                <input class="form-check-input wh-event" type="checkbox" id="whEvtGradeApproved" value="grade.approved"
                                    ${whData.events.includes('grade.approved') ? 'checked' : ''}>
                                <label class="form-check-label small" for="whEvtGradeApproved">Grade Approved</label>
                            </div>
                            <div class="form-check">
                                <input class="form-check-input wh-event" type="checkbox" id="whEvtGradeOverridden" value="grade.overridden"
                                    ${whData.events.includes('grade.overridden') ? 'checked' : ''}>
                                <label class="form-check-label small" for="whEvtGradeOverridden">Grade Overridden</label>
                            </div>
                            <div class="form-check">
                                <input class="form-check-input wh-event" type="checkbox" id="whEvtAuthFlagged" value="auth.flagged"
                                    ${whData.events.includes('auth.flagged') ? 'checked' : ''}>
                                <label class="form-check-label small" for="whEvtAuthFlagged">Auth Flagged</label>
                            </div>
                        </div>
                    </div>
                </div>
                <hr>
                <div class="d-flex gap-2">
                    <button class="btn btn-primary" id="btnSaveWebhook">
                        <i class="bi bi-save me-1"></i>Save Webhook Settings
                    </button>
                    <button class="btn btn-outline-secondary" id="btnTestWebhook">
                        <i class="bi bi-plug me-1"></i>Test Webhook
                    </button>
                </div>
                <div id="whTestResult" class="mt-3"></div>
            </div>
        </div>
    `;

    // Toggle PokeWallet key visibility
    const keyInput = pane.querySelector('#apiKey');
    pane.querySelector('#btnToggleApiKey').addEventListener('click', () => {
        const isPassword = keyInput.type === 'password';
        keyInput.type = isPassword ? 'text' : 'password';
        pane.querySelector('#btnToggleApiKey i').className = isPassword ? 'bi bi-eye-slash' : 'bi bi-eye';
    });

    // Toggle OpenRouter key visibility
    const orKeyInput = pane.querySelector('#orApiKey');
    pane.querySelector('#btnToggleOrKey').addEventListener('click', () => {
        const isPassword = orKeyInput.type === 'password';
        orKeyInput.type = isPassword ? 'text' : 'password';
        pane.querySelector('#btnToggleOrKey i').className = isPassword ? 'bi bi-eye-slash' : 'bi bi-eye';
    });

    // Save PokeWallet
    pane.querySelector('#btnSaveApi').addEventListener('click', async () => {
        try {
            const payload = {
                base_url: pane.querySelector('#apiBaseUrl').value,
                rate_limit_buffer: parseInt(pane.querySelector('#apiRateLimit').value),
                cache_ttl_seconds: parseInt(pane.querySelector('#apiCacheTtl').value),
                request_timeout: parseFloat(pane.querySelector('#apiTimeout').value),
            };
            const newKey = keyInput.value.trim();
            if (newKey) payload.api_key = newKey;
            await api.put('/settings/api', payload);
            showToast('PokeWallet settings saved.', 'success');
        } catch (err) {
            showToast('Failed to save: ' + err.message, 'error');
        }
    });

    pane.querySelector('#btnTestApi').addEventListener('click', async () => {
        const btn = pane.querySelector('#btnTestApi');
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Testing...';
        try {
            const res = await api.post('/settings/api/test');
            showToast(`PokeWallet API connected (HTTP ${res.http_status}).`, 'success');
        } catch (err) {
            showToast('Connection failed: ' + err.message, 'error');
        } finally {
            btn.disabled = false;
            btn.innerHTML = '<i class="bi bi-plug me-1"></i>Test Connection';
        }
    });

    // Save OpenRouter
    pane.querySelector('#btnSaveOr').addEventListener('click', async () => {
        try {
            const payload = {
                model: pane.querySelector('#orModel').value,
                enabled: pane.querySelector('#orEnabled').checked,
            };
            const newKey = orKeyInput.value.trim();
            if (newKey) payload.api_key = newKey;
            await api.put('/settings/openrouter', payload);
            showToast('AI settings saved.', 'success');
        } catch (err) {
            showToast('Failed to save: ' + err.message, 'error');
        }
    });

    // Test OpenRouter
    pane.querySelector('#btnTestOr').addEventListener('click', async () => {
        const btn = pane.querySelector('#btnTestOr');
        const result = pane.querySelector('#orTestResult');
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Testing...';
        result.innerHTML = '';
        try {
            const res = await api.post('/settings/openrouter/test');
            result.innerHTML = `<div class="alert alert-success py-2 small mb-0"><i class="bi bi-check-circle me-1"></i>Connected! Model: ${res.model}</div>`;
        } catch (err) {
            result.innerHTML = `<div class="alert alert-danger py-2 small mb-0"><i class="bi bi-x-circle me-1"></i>${err.message}</div>`;
        } finally {
            btn.disabled = false;
            btn.innerHTML = '<i class="bi bi-plug me-1"></i>Test Connection';
        }
    });

    // Toggle webhook secret visibility
    const whSecretInput = pane.querySelector('#whSecret');
    pane.querySelector('#btnToggleWhSecret')?.addEventListener('click', () => {
        const isPassword = whSecretInput.type === 'password';
        whSecretInput.type = isPassword ? 'text' : 'password';
        pane.querySelector('#btnToggleWhSecret i').className = isPassword ? 'bi bi-eye-slash' : 'bi bi-eye';
    });

    // Save Webhook
    pane.querySelector('#btnSaveWebhook')?.addEventListener('click', async () => {
        try {
            const events = [...pane.querySelectorAll('.wh-event:checked')].map(cb => cb.value);
            const payload = {
                enabled: pane.querySelector('#whEnabled').checked,
                url: pane.querySelector('#whUrl').value,
                events,
            };
            const newSecret = whSecretInput.value.trim();
            if (newSecret) payload.secret = newSecret;
            await api.put('/settings/webhook', payload);
            showToast('Webhook settings saved.', 'success');
        } catch (err) {
            showToast('Failed to save: ' + err.message, 'error');
        }
    });

    // Test Webhook
    pane.querySelector('#btnTestWebhook')?.addEventListener('click', async () => {
        const btn = pane.querySelector('#btnTestWebhook');
        const result = pane.querySelector('#whTestResult');
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Sending...';
        result.innerHTML = '';
        try {
            const res = await api.post('/settings/webhook/test');
            result.innerHTML = `<div class="alert alert-success py-2 small mb-0"><i class="bi bi-check-circle me-1"></i>Webhook responded (HTTP ${res.http_status})</div>`;
        } catch (err) {
            result.innerHTML = `<div class="alert alert-danger py-2 small mb-0"><i class="bi bi-x-circle me-1"></i>${err.message}</div>`;
        } finally {
            btn.disabled = false;
            btn.innerHTML = '<i class="bi bi-plug me-1"></i>Test Webhook';
        }
    });
}

// ------------------------------------------------------- Laser tab removed (handled by LightBurn directly)
async function _removed_loadLaserTab() {
    const [materials, jigs, calHistory] = await Promise.all([
        api.get('/settings/materials'),
        api.get('/settings/jigs'),
        api.get('/settings/calibration/history'),
    ]);

    const pane = _container.querySelector('#tab-laser');
    pane.innerHTML = `
        <!-- Material Profiles -->
        <div class="card mb-4">
            <div class="card-header d-flex justify-content-between align-items-center">
                <h6 class="mb-0">Material Profiles</h6>
                <button class="btn btn-sm btn-primary" id="btnAddMaterial">
                    <i class="bi bi-plus-lg me-1"></i>Add Material
                </button>
            </div>
            <div class="card-body p-0">
                <div class="table-responsive">
                    <table class="table table-hover mb-0">
                        <thead class="table-light">
                            <tr>
                                <th>Name</th>
                                <th>Type</th>
                                <th>Power (%)</th>
                                <th>Speed (mm/s)</th>
                                <th>Passes</th>
                                <th>Interval (mm)</th>
                                <th class="text-end">Actions</th>
                            </tr>
                        </thead>
                        <tbody id="materialTableBody">
                            ${materials.length > 0 ? materials.map(m => _materialRow(m)).join('') :
                              `<tr><td colspan="7">${createEmptyState('No material profiles yet.', 'bi-palette')}</td></tr>`}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <!-- Jig Profiles -->
        <div class="card mb-4">
            <div class="card-header d-flex justify-content-between align-items-center">
                <h6 class="mb-0">Jig Profiles</h6>
                <button class="btn btn-sm btn-primary" id="btnAddJig">
                    <i class="bi bi-plus-lg me-1"></i>Add Jig
                </button>
            </div>
            <div class="card-body p-0">
                <div class="table-responsive">
                    <table class="table table-hover mb-0">
                        <thead class="table-light">
                            <tr>
                                <th>Name</th>
                                <th>Work Area (mm)</th>
                                <th>Slab Position (mm)</th>
                                <th>Camera Offset (mm)</th>
                                <th class="text-end">Actions</th>
                            </tr>
                        </thead>
                        <tbody id="jigTableBody">
                            ${jigs.length > 0 ? jigs.map(j => _jigRow(j)).join('') :
                              `<tr><td colspan="5">${createEmptyState('No jig profiles yet.', 'bi-grid-3x3')}</td></tr>`}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <!-- Calibration Section -->
        <div class="card mb-4">
            <div class="card-header"><h6 class="mb-0">Calibration</h6></div>
            <div class="card-body">
                <p class="small text-muted mb-3">
                    Generate a test matrix, engrave it on a physical sample, rate each cell (1-5 stars), and save.
                    The best-rated setting (4+) will auto-update the material profile.
                </p>
                <div class="row mb-3">
                    <div class="col-md-6">
                        <label class="form-label">Material Profile</label>
                        <select class="form-select" id="calMaterialSelect">
                            <option value="">-- Select material --</option>
                            ${materials.map(m => `<option value="${m.id}">${m.name} (${m.material_type})</option>`).join('')}
                        </select>
                    </div>
                    <div class="col-md-6 d-flex align-items-end">
                        <button class="btn btn-outline-primary" id="btnGenerateMatrix">
                            <i class="bi bi-grid-3x3 me-1"></i>Generate Test Matrix
                        </button>
                    </div>
                </div>
                <div id="calibrationMatrixArea"></div>
                <hr>
                <h6 class="text-muted mb-2">Calibration History</h6>
                ${calHistory.length > 0 ? `
                    <div class="table-responsive">
                        <table class="table table-sm table-hover mb-0">
                            <thead class="table-light">
                                <tr>
                                    <th>Date</th>
                                    <th>Material</th>
                                    <th>Best Power</th>
                                    <th>Best Speed</th>
                                    <th>Quality</th>
                                    <th>Notes</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${calHistory.map(r => `
                                    <tr>
                                        <td class="small">${formatDate(r.created_at)}</td>
                                        <td>${r.material_profile_id ? r.material_profile_id.substring(0, 8) + '...' : '--'}</td>
                                        <td>${r.best_power_pct != null ? r.best_power_pct + '%' : '--'}</td>
                                        <td>${r.best_speed_mm_s != null ? r.best_speed_mm_s + ' mm/s' : '--'}</td>
                                        <td>${r.result_quality != null ? _starRating(r.result_quality) : '--'}</td>
                                        <td class="small text-muted">${r.result_notes || ''}</td>
                                    </tr>
                                `).join('')}
                            </tbody>
                        </table>
                    </div>
                ` : createEmptyState('No calibration runs yet.', 'bi-bullseye')}
            </div>
        </div>

        <!-- Material Edit Modal -->
        <div class="modal fade" id="materialModal" tabindex="-1">
            <div class="modal-dialog modal-lg">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title" id="materialModalTitle">Add Material Profile</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <input type="hidden" id="matEditId">
                        <div class="row">
                            <div class="col-md-6 mb-3">
                                <label class="form-label">Name</label>
                                <input type="text" class="form-control" id="matName" required>
                            </div>
                            <div class="col-md-6 mb-3">
                                <label class="form-label">Material Type</label>
                                <select class="form-select" id="matType">
                                    <option value="acrylic">Acrylic</option>
                                    <option value="polycarbonate">Polycarbonate</option>
                                    <option value="abs">ABS</option>
                                    <option value="petg">PETG</option>
                                    <option value="other">Other</option>
                                </select>
                            </div>
                            <div class="col-md-4 mb-3">
                                <label class="form-label">Thickness (mm)</label>
                                <input type="number" class="form-control" id="matThickness" value="3.0" step="0.1" min="0.1">
                            </div>
                            <div class="col-md-4 mb-3">
                                <label class="form-label">Mask Type</label>
                                <input type="text" class="form-control" id="matMask" placeholder="e.g. paper, vinyl">
                            </div>
                            <div class="col-md-4 mb-3">
                                <label class="form-label">Coating Method</label>
                                <input type="text" class="form-control" id="matCoating" placeholder="e.g. spray, film">
                            </div>
                        </div>
                        <hr>
                        <h6 class="text-muted mb-3">Laser Parameters</h6>
                        <div class="row">
                            <div class="col-md-4 mb-3">
                                <label class="form-label">Min Power (%)</label>
                                <input type="number" class="form-control" id="matPowerMin" value="15" min="0" max="100" step="0.5">
                            </div>
                            <div class="col-md-4 mb-3">
                                <label class="form-label">Max Power (%)</label>
                                <input type="number" class="form-control" id="matPowerMax" value="20" min="0" max="100" step="0.5">
                            </div>
                            <div class="col-md-4 mb-3">
                                <label class="form-label">Speed (mm/s)</label>
                                <input type="number" class="form-control" id="matSpeed" value="1000" min="1" step="10">
                            </div>
                            <div class="col-md-4 mb-3">
                                <label class="form-label">Passes</label>
                                <input type="number" class="form-control" id="matPasses" value="1" min="1" max="10">
                            </div>
                            <div class="col-md-4 mb-3">
                                <label class="form-label">Interval (mm)</label>
                                <input type="number" class="form-control" id="matInterval" value="0.08" min="0.01" max="1" step="0.01">
                            </div>
                        </div>
                        <hr>
                        <h6 class="text-muted mb-3">Security Layer Parameters</h6>
                        <div class="row">
                            <div class="col-md-6 mb-3">
                                <label class="form-label">Security Speed (mm/s)</label>
                                <input type="number" class="form-control" id="matSecSpeed" value="800" min="1" step="10">
                            </div>
                            <div class="col-md-6 mb-3">
                                <label class="form-label">Security Power (%)</label>
                                <input type="number" class="form-control" id="matSecPower" value="12" min="0" max="100" step="0.5">
                            </div>
                        </div>
                        <div class="mb-3">
                            <label class="form-label">Cleanup Notes</label>
                            <textarea class="form-control" id="matNotes" rows="2" placeholder="Post-processing cleanup steps..."></textarea>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                        <button type="button" class="btn btn-primary" id="btnSaveMaterial">
                            <i class="bi bi-save me-1"></i>Save Material
                        </button>
                    </div>
                </div>
            </div>
        </div>

        <!-- Jig Edit Modal -->
        <div class="modal fade" id="jigModal" tabindex="-1">
            <div class="modal-dialog modal-lg">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title" id="jigModalTitle">Add Jig Profile</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <input type="hidden" id="jigEditId">
                        <div class="row">
                            <div class="col-md-6 mb-3">
                                <label class="form-label">Name</label>
                                <input type="text" class="form-control" id="jigName" required>
                            </div>
                            <div class="col-md-6 mb-3">
                                <label class="form-label">Description</label>
                                <input type="text" class="form-control" id="jigDesc" placeholder="Optional description">
                            </div>
                        </div>
                        <hr>
                        <h6 class="text-muted mb-3">Work Area</h6>
                        <div class="row">
                            <div class="col-md-6 mb-3">
                                <label class="form-label">Width (mm)</label>
                                <input type="number" class="form-control" id="jigAreaW" value="200" step="0.1">
                            </div>
                            <div class="col-md-6 mb-3">
                                <label class="form-label">Height (mm)</label>
                                <input type="number" class="form-control" id="jigAreaH" value="200" step="0.1">
                            </div>
                        </div>
                        <h6 class="text-muted mb-3">Slab Position Offset</h6>
                        <div class="row">
                            <div class="col-md-6 mb-3">
                                <label class="form-label">X Offset (mm)</label>
                                <input type="number" class="form-control" id="jigPosX" value="0" step="0.1">
                            </div>
                            <div class="col-md-6 mb-3">
                                <label class="form-label">Y Offset (mm)</label>
                                <input type="number" class="form-control" id="jigPosY" value="0" step="0.1">
                            </div>
                        </div>
                        <h6 class="text-muted mb-3">Camera Offset</h6>
                        <div class="row">
                            <div class="col-md-6 mb-3">
                                <label class="form-label">Camera X Offset (mm)</label>
                                <input type="number" class="form-control" id="jigCamX" value="0" step="0.1">
                            </div>
                            <div class="col-md-6 mb-3">
                                <label class="form-label">Camera Y Offset (mm)</label>
                                <input type="number" class="form-control" id="jigCamY" value="0" step="0.1">
                            </div>
                        </div>
                        <div class="mb-3">
                            <label class="form-label">Fiducial Positions (JSON)</label>
                            <textarea class="form-control" id="jigFiducials" rows="2"
                                placeholder='[{"x": 10, "y": 10}, {"x": 190, "y": 10}]'></textarea>
                            <small class="text-muted">Array of {x, y} coordinate objects for alignment marks.</small>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                        <button type="button" class="btn btn-primary" id="btnSaveJig">
                            <i class="bi bi-save me-1"></i>Save Jig
                        </button>
                    </div>
                </div>
            </div>
        </div>
    `;

    // ---- Material CRUD handlers
    pane.querySelector('#btnAddMaterial').addEventListener('click', () => {
        _resetMaterialForm(pane);
        pane.querySelector('#materialModalTitle').textContent = 'Add Material Profile';
        new bootstrap.Modal(pane.querySelector('#materialModal')).show();
    });

    pane.querySelector('#btnSaveMaterial').addEventListener('click', () => _saveMaterial(pane, materials));

    pane.querySelectorAll('.btn-edit-material').forEach(btn => {
        btn.addEventListener('click', () => _editMaterial(pane, btn.dataset.id));
    });
    pane.querySelectorAll('.btn-delete-material').forEach(btn => {
        btn.addEventListener('click', () => _deleteMaterial(pane, btn.dataset.id));
    });

    // ---- Jig CRUD handlers
    pane.querySelector('#btnAddJig').addEventListener('click', () => {
        _resetJigForm(pane);
        pane.querySelector('#jigModalTitle').textContent = 'Add Jig Profile';
        new bootstrap.Modal(pane.querySelector('#jigModal')).show();
    });

    pane.querySelector('#btnSaveJig').addEventListener('click', () => _saveJig(pane, jigs));

    pane.querySelectorAll('.btn-edit-jig').forEach(btn => {
        btn.addEventListener('click', () => _editJig(pane, btn.dataset.id));
    });
    pane.querySelectorAll('.btn-delete-jig').forEach(btn => {
        btn.addEventListener('click', () => _deleteJig(pane, btn.dataset.id));
    });

    // ---- Calibration handlers
    pane.querySelector('#btnGenerateMatrix').addEventListener('click', () => _generateCalibrationMatrix(pane));
}

// ---- Material helpers
function _materialRow(m) {
    return `
        <tr>
            <td><strong>${m.name}</strong></td>
            <td><span class="badge bg-light text-dark">${m.material_type}</span></td>
            <td>${m.laser_power_min_pct}-${m.laser_power_max_pct}%</td>
            <td>${m.laser_speed_mm_s}</td>
            <td>${m.laser_passes}</td>
            <td>${m.laser_interval_mm}</td>
            <td class="text-end">
                <button class="btn btn-sm btn-outline-primary btn-edit-material me-1" data-id="${m.id}">
                    <i class="bi bi-pencil"></i>
                </button>
                <button class="btn btn-sm btn-outline-danger btn-delete-material" data-id="${m.id}">
                    <i class="bi bi-trash"></i>
                </button>
            </td>
        </tr>
    `;
}

function _resetMaterialForm(pane) {
    pane.querySelector('#matEditId').value = '';
    pane.querySelector('#matName').value = '';
    pane.querySelector('#matType').value = 'acrylic';
    pane.querySelector('#matThickness').value = '3.0';
    pane.querySelector('#matMask').value = '';
    pane.querySelector('#matCoating').value = '';
    pane.querySelector('#matPowerMin').value = '15';
    pane.querySelector('#matPowerMax').value = '20';
    pane.querySelector('#matSpeed').value = '1000';
    pane.querySelector('#matPasses').value = '1';
    pane.querySelector('#matInterval').value = '0.08';
    pane.querySelector('#matSecSpeed').value = '800';
    pane.querySelector('#matSecPower').value = '12';
    pane.querySelector('#matNotes').value = '';
}

function _getMaterialFormData(pane) {
    return {
        name: pane.querySelector('#matName').value.trim(),
        material_type: pane.querySelector('#matType').value,
        thickness_mm: parseFloat(pane.querySelector('#matThickness').value),
        mask_type: pane.querySelector('#matMask').value.trim() || null,
        coating_method: pane.querySelector('#matCoating').value.trim() || null,
        laser_power_min_pct: parseFloat(pane.querySelector('#matPowerMin').value),
        laser_power_max_pct: parseFloat(pane.querySelector('#matPowerMax').value),
        laser_speed_mm_s: parseFloat(pane.querySelector('#matSpeed').value),
        laser_passes: parseInt(pane.querySelector('#matPasses').value),
        laser_interval_mm: parseFloat(pane.querySelector('#matInterval').value),
        security_speed_mm_s: parseFloat(pane.querySelector('#matSecSpeed').value),
        security_power_pct: parseFloat(pane.querySelector('#matSecPower').value),
        cleanup_notes: pane.querySelector('#matNotes').value.trim() || null,
    };
}

async function _saveMaterial(pane) {
    const id = pane.querySelector('#matEditId').value;
    const data = _getMaterialFormData(pane);
    if (!data.name) { showToast('Material name is required.', 'error'); return; }
    try {
        if (id) {
            await api.put(`/settings/materials/${id}`, data);
            showToast('Material profile updated.', 'success');
        } else {
            await api.post('/settings/materials', data);
            showToast('Material profile created.', 'success');
        }
        bootstrap.Modal.getInstance(pane.querySelector('#materialModal')).hide();
        _loadedTabs.delete('laser');
        await loadLaserTab();
    } catch (err) {
        showToast('Failed to save material: ' + err.message, 'error');
    }
}

async function _editMaterial(pane, id) {
    try {
        const m = await api.get(`/settings/materials/${id}`);
        pane.querySelector('#matEditId').value = m.id;
        pane.querySelector('#materialModalTitle').textContent = 'Edit Material Profile';
        pane.querySelector('#matName').value = m.name;
        pane.querySelector('#matType').value = m.material_type;
        pane.querySelector('#matThickness').value = m.thickness_mm;
        pane.querySelector('#matMask').value = m.mask_type || '';
        pane.querySelector('#matCoating').value = m.coating_method || '';
        pane.querySelector('#matPowerMin').value = m.laser_power_min_pct;
        pane.querySelector('#matPowerMax').value = m.laser_power_max_pct;
        pane.querySelector('#matSpeed').value = m.laser_speed_mm_s;
        pane.querySelector('#matPasses').value = m.laser_passes;
        pane.querySelector('#matInterval').value = m.laser_interval_mm;
        pane.querySelector('#matSecSpeed').value = m.security_speed_mm_s;
        pane.querySelector('#matSecPower').value = m.security_power_pct;
        pane.querySelector('#matNotes').value = m.cleanup_notes || '';
        new bootstrap.Modal(pane.querySelector('#materialModal')).show();
    } catch (err) {
        showToast('Failed to load material: ' + err.message, 'error');
    }
}

async function _deleteMaterial(pane, id) {
    if (!confirm('Delete this material profile? This will soft-delete it.')) return;
    try {
        await api.delete(`/settings/materials/${id}`);
        showToast('Material profile deleted.', 'success');
        _loadedTabs.delete('laser');
        await loadLaserTab();
    } catch (err) {
        showToast('Failed to delete: ' + err.message, 'error');
    }
}

// ---- Jig helpers
function _jigRow(j) {
    return `
        <tr>
            <td><strong>${j.name}</strong></td>
            <td>${j.work_area_width_mm} x ${j.work_area_height_mm}</td>
            <td>${j.slab_position_x_mm}, ${j.slab_position_y_mm}</td>
            <td>${j.camera_offset_x_mm}, ${j.camera_offset_y_mm}</td>
            <td class="text-end">
                <button class="btn btn-sm btn-outline-primary btn-edit-jig me-1" data-id="${j.id}">
                    <i class="bi bi-pencil"></i>
                </button>
                <button class="btn btn-sm btn-outline-danger btn-delete-jig" data-id="${j.id}">
                    <i class="bi bi-trash"></i>
                </button>
            </td>
        </tr>
    `;
}

function _resetJigForm(pane) {
    pane.querySelector('#jigEditId').value = '';
    pane.querySelector('#jigName').value = '';
    pane.querySelector('#jigDesc').value = '';
    pane.querySelector('#jigAreaW').value = '200';
    pane.querySelector('#jigAreaH').value = '200';
    pane.querySelector('#jigPosX').value = '0';
    pane.querySelector('#jigPosY').value = '0';
    pane.querySelector('#jigCamX').value = '0';
    pane.querySelector('#jigCamY').value = '0';
    pane.querySelector('#jigFiducials').value = '';
}

function _getJigFormData(pane) {
    let fiducials = null;
    const fidText = pane.querySelector('#jigFiducials').value.trim();
    if (fidText) {
        try { fiducials = JSON.parse(fidText); } catch { showToast('Invalid fiducial JSON.', 'error'); return null; }
    }
    return {
        name: pane.querySelector('#jigName').value.trim(),
        description: pane.querySelector('#jigDesc').value.trim() || null,
        work_area_width_mm: parseFloat(pane.querySelector('#jigAreaW').value),
        work_area_height_mm: parseFloat(pane.querySelector('#jigAreaH').value),
        slab_position_x_mm: parseFloat(pane.querySelector('#jigPosX').value),
        slab_position_y_mm: parseFloat(pane.querySelector('#jigPosY').value),
        camera_offset_x_mm: parseFloat(pane.querySelector('#jigCamX').value),
        camera_offset_y_mm: parseFloat(pane.querySelector('#jigCamY').value),
        fiducial_positions_json: fiducials,
    };
}

async function _saveJig(pane) {
    const id = pane.querySelector('#jigEditId').value;
    const data = _getJigFormData(pane);
    if (!data) return;
    if (!data.name) { showToast('Jig name is required.', 'error'); return; }
    try {
        if (id) {
            await api.put(`/settings/jigs/${id}`, data);
            showToast('Jig profile updated.', 'success');
        } else {
            await api.post('/settings/jigs', data);
            showToast('Jig profile created.', 'success');
        }
        bootstrap.Modal.getInstance(pane.querySelector('#jigModal')).hide();
        _loadedTabs.delete('laser');
        await loadLaserTab();
    } catch (err) {
        showToast('Failed to save jig: ' + err.message, 'error');
    }
}

async function _editJig(pane, id) {
    try {
        const j = await api.get(`/settings/jigs/${id}`);
        pane.querySelector('#jigEditId').value = j.id;
        pane.querySelector('#jigModalTitle').textContent = 'Edit Jig Profile';
        pane.querySelector('#jigName').value = j.name;
        pane.querySelector('#jigDesc').value = j.description || '';
        pane.querySelector('#jigAreaW').value = j.work_area_width_mm;
        pane.querySelector('#jigAreaH').value = j.work_area_height_mm;
        pane.querySelector('#jigPosX').value = j.slab_position_x_mm;
        pane.querySelector('#jigPosY').value = j.slab_position_y_mm;
        pane.querySelector('#jigCamX').value = j.camera_offset_x_mm;
        pane.querySelector('#jigCamY').value = j.camera_offset_y_mm;
        pane.querySelector('#jigFiducials').value = j.fiducial_positions_json ? JSON.stringify(j.fiducial_positions_json, null, 2) : '';
        new bootstrap.Modal(pane.querySelector('#jigModal')).show();
    } catch (err) {
        showToast('Failed to load jig: ' + err.message, 'error');
    }
}

async function _deleteJig(pane, id) {
    if (!confirm('Delete this jig profile? This will soft-delete it.')) return;
    try {
        await api.delete(`/settings/jigs/${id}`);
        showToast('Jig profile deleted.', 'success');
        _loadedTabs.delete('laser');
        await loadLaserTab();
    } catch (err) {
        showToast('Failed to delete: ' + err.message, 'error');
    }
}

// ---- Calibration helpers
async function _generateCalibrationMatrix(pane) {
    const materialId = pane.querySelector('#calMaterialSelect').value;
    if (!materialId) { showToast('Select a material profile first.', 'warning'); return; }

    const area = pane.querySelector('#calibrationMatrixArea');
    area.innerHTML = createLoadingSpinner('Generating matrix...');

    try {
        const result = await api.post('/settings/calibration/generate', { material_id: materialId });
        _calibrationMatrix = result;

        const powerVals = result.power_values;
        const speedVals = result.speed_values;

        let html = `
            <div class="alert alert-info small">
                <i class="bi bi-info-circle me-1"></i>
                Matrix for <strong>${result.material_name}</strong>: ${result.total_cells} cells.
                Engrave this grid on a test piece, then rate each cell 1-5 stars for quality.
            </div>
            <div class="table-responsive">
                <table class="table table-bordered table-sm text-center" id="calibrationMatrix">
                    <thead class="table-light">
                        <tr>
                            <th class="text-start">Power \\ Speed</th>
                            ${speedVals.map(s => `<th>${s} mm/s</th>`).join('')}
                        </tr>
                    </thead>
                    <tbody>
        `;

        for (const power of powerVals) {
            html += `<tr><td class="text-start fw-bold">${power}%</td>`;
            for (const speed of speedVals) {
                const cellId = `cal-${power}-${speed}`;
                html += `
                    <td>
                        <div class="d-flex justify-content-center gap-1">
                            ${[1,2,3,4,5].map(star => `
                                <i class="bi bi-star cal-star" role="button"
                                   data-cell="${cellId}" data-rating="${star}"
                                   data-power="${power}" data-speed="${speed}"
                                   style="cursor:pointer; color:#ccc;"></i>
                            `).join('')}
                        </div>
                    </td>
                `;
            }
            html += `</tr>`;
        }

        html += `
                    </tbody>
                </table>
            </div>
            <div class="mb-3">
                <label class="form-label">Notes</label>
                <textarea class="form-control" id="calNotes" rows="2" placeholder="Optional notes about this calibration run..."></textarea>
            </div>
            <button class="btn btn-success" id="btnSaveCalibration">
                <i class="bi bi-save me-1"></i>Save Calibration Results
            </button>
        `;

        area.innerHTML = html;

        // Star rating click handler
        area.querySelectorAll('.cal-star').forEach(star => {
            star.addEventListener('click', (e) => {
                const cellId = e.target.dataset.cell;
                const rating = parseInt(e.target.dataset.rating);
                // Update visual state for this cell
                area.querySelectorAll(`.cal-star[data-cell="${cellId}"]`).forEach(s => {
                    const r = parseInt(s.dataset.rating);
                    s.classList.remove('bi-star-fill', 'bi-star');
                    s.classList.add(r <= rating ? 'bi-star-fill' : 'bi-star');
                    s.style.color = r <= rating ? '#f59e0b' : '#ccc';
                });
                // Store rating in matrix data
                const power = parseFloat(e.target.dataset.power);
                const speed = parseFloat(e.target.dataset.speed);
                const cell = _calibrationMatrix.matrix.find(c => c.power_pct === power && c.speed_mm_s === speed);
                if (cell) cell.rating = rating;
            });
        });

        // Save button
        area.querySelector('#btnSaveCalibration').addEventListener('click', async () => {
            const rated = _calibrationMatrix.matrix.filter(c => c.rating != null);
            if (rated.length === 0) {
                showToast('Rate at least one cell before saving.', 'warning');
                return;
            }
            try {
                const result = await api.post('/settings/calibration/save', {
                    material_id: _calibrationMatrix.material_id,
                    matrix: _calibrationMatrix.matrix,
                    notes: pane.querySelector('#calNotes')?.value || '',
                });
                let msg = 'Calibration saved.';
                if (result.material_updated) {
                    msg += ` Material profile auto-updated to ${result.best_power_pct}% power, ${result.best_speed_mm_s} mm/s.`;
                }
                showToast(msg, 'success');
                // Reload tab to show new history entry
                _loadedTabs.delete('laser');
                await loadLaserTab();
            } catch (err) {
                showToast('Failed to save calibration: ' + err.message, 'error');
            }
        });

    } catch (err) {
        area.innerHTML = `<div class="alert alert-danger">Failed to generate matrix: ${err.message}</div>`;
    }
}

function _starRating(value) {
    const max = 5;
    let html = '';
    for (let i = 1; i <= max; i++) {
        html += `<i class="bi ${i <= value ? 'bi-star-fill' : 'bi-star'}" style="color:${i <= value ? '#f59e0b' : '#ccc'};"></i>`;
    }
    return html;
}

// ------------------------------------------------------- Security Tab
async function loadSecurityTab() {
    const data = await api.get('/settings/security');
    const pane = _container.querySelector('#tab-security');
    pane.innerHTML = `
        <div class="card">
            <div class="card-header"><h6 class="mb-0">Security Pattern Settings</h6></div>
            <div class="card-body">
                <div class="row">
                    <div class="col-md-6 mb-3">
                        <div class="form-check form-switch">
                            <input class="form-check-input" type="checkbox" id="secEnableQr"
                                   ${data.enable_qr ? 'checked' : ''}>
                            <label class="form-check-label" for="secEnableQr">Enable QR Code Pattern</label>
                        </div>
                    </div>
                    <div class="col-md-6 mb-3">
                        <div class="form-check form-switch">
                            <input class="form-check-input" type="checkbox" id="secEnableWitness"
                                   ${data.enable_witness_marks ? 'checked' : ''}>
                            <label class="form-check-label" for="secEnableWitness">Enable Witness Marks</label>
                        </div>
                    </div>
                </div>
                <hr>
                <div class="row">
                    <div class="col-md-4 mb-3">
                        <label class="form-label d-flex justify-content-between">
                            <span>Microtext Height (mm)</span>
                            <span class="badge bg-secondary" id="label-microtext">${data.microtext_height_mm}</span>
                        </label>
                        <input type="range" class="form-range" id="secMicrotext"
                               min="0.3" max="0.5" step="0.01" value="${data.microtext_height_mm}">
                        <small class="text-muted">0.3 - 0.5 mm</small>
                    </div>
                    <div class="col-md-4 mb-3">
                        <label class="form-label d-flex justify-content-between">
                            <span>Dot Radius (mm)</span>
                            <span class="badge bg-secondary" id="label-dotRadius">${data.dot_radius_mm}</span>
                        </label>
                        <input type="range" class="form-range" id="secDotRadius"
                               min="0.05" max="0.2" step="0.005" value="${data.dot_radius_mm}">
                        <small class="text-muted">0.05 - 0.2 mm</small>
                    </div>
                    <div class="col-md-4 mb-3">
                        <label class="form-label">Dot Count</label>
                        <input type="number" class="form-control" id="secDotCount"
                               value="${data.dot_count}" min="16" max="256" step="1">
                    </div>
                </div>
                <hr>
                <button class="btn btn-primary" id="btnSaveSecurity">
                    <i class="bi bi-save me-1"></i>Save Security Settings
                </button>
            </div>
        </div>
    `;

    // Live slider labels
    pane.querySelector('#secMicrotext').addEventListener('input', (e) => {
        pane.querySelector('#label-microtext').textContent = parseFloat(e.target.value).toFixed(2);
    });
    pane.querySelector('#secDotRadius').addEventListener('input', (e) => {
        pane.querySelector('#label-dotRadius').textContent = parseFloat(e.target.value).toFixed(3);
    });

    pane.querySelector('#btnSaveSecurity').addEventListener('click', async () => {
        try {
            await api.put('/settings/security', {
                enable_qr: pane.querySelector('#secEnableQr').checked,
                enable_witness_marks: pane.querySelector('#secEnableWitness').checked,
                microtext_height_mm: parseFloat(pane.querySelector('#secMicrotext').value),
                dot_radius_mm: parseFloat(pane.querySelector('#secDotRadius').value),
                dot_count: parseInt(pane.querySelector('#secDotCount').value),
            });
            showToast('Security settings saved.', 'success');
        } catch (err) {
            showToast('Failed to save: ' + err.message, 'error');
        }
    });
}

// ------------------------------------------------------- NFC / Printer Tab
async function loadSlabTab() {
    const [nfcData, printerData] = await Promise.all([
        api.get('/settings/nfc'),
        api.get('/settings/printer'),
    ]);
    const pane = _container.querySelector('#tab-slab');
    pane.innerHTML = `
        <div class="card mb-4">
            <div class="card-header"><h6 class="mb-0">NFC Tag Settings</h6></div>
            <div class="card-body">
                <div class="row">
                    <div class="col-md-6 mb-3">
                        <label class="form-label">Default NFC Tag Type</label>
                        <select class="form-select" id="nfcDefaultTagType">
                            <option value="ntag424_dna" ${nfcData.default_tag_type === 'ntag424_dna' ? 'selected' : ''}>
                                NTag424 DNA (Secure / Recommended)
                            </option>
                            <option value="ntag213" ${nfcData.default_tag_type === 'ntag213' ? 'selected' : ''}>
                                NTag213 (Basic)
                            </option>
                        </select>
                        <small class="text-muted">NTag424 DNA uses cryptographic SUN/SDM — each tap generates a unique URL that cannot be cloned. NTag213 writes a simple static URL.</small>
                    </div>
                    <div class="col-md-6 mb-3">
                        <label class="form-label">Verification Base URL</label>
                        <input type="text" class="form-control" id="nfcVerifyBaseUrl"
                               value="${nfcData.verify_base_url || ''}">
                        <small class="text-muted">Base URL written to NFC tags (e.g. https://rktgrading.com/verify).</small>
                    </div>
                    <div class="col-md-6 mb-3">
                        <div class="form-check form-switch">
                            <input class="form-check-input" type="checkbox" id="nfcMockMode"
                                   ${nfcData.mock_mode ? 'checked' : ''}>
                            <label class="form-check-label" for="nfcMockMode">
                                Mock NFC Mode
                            </label>
                        </div>
                        <small class="text-muted">When enabled, simulates NFC programming without hardware.</small>
                    </div>
                </div>
                <button class="btn btn-primary" id="btnSaveNfc">
                    <i class="bi bi-save me-1"></i>Save NFC Settings
                </button>
            </div>
        </div>

        <div class="card">
            <div class="card-header"><h6 class="mb-0">Printer Settings (Epson C6000)</h6></div>
            <div class="card-body">
                <div class="row">
                    <div class="col-md-6 mb-3">
                        <div class="form-check form-switch">
                            <input class="form-check-input" type="checkbox" id="printerMockMode"
                                   ${printerData.mock_mode ? 'checked' : ''}>
                            <label class="form-check-label" for="printerMockMode">
                                Mock Printer Mode
                            </label>
                        </div>
                        <small class="text-muted">When enabled, saves label images to disk instead of printing.</small>
                    </div>
                    <div class="col-md-6 mb-3">
                        <label class="form-label">Printer Name</label>
                        <input type="text" class="form-control" id="printerName"
                               value="${printerData.printer_name || ''}" placeholder="e.g. Epson ColorWorks C6000">
                        <small class="text-muted">Windows printer name as shown in Devices & Printers.</small>
                    </div>
                    <div class="col-md-4 mb-3">
                        <label class="form-label">Print DPI</label>
                        <select class="form-select" id="printerDpi">
                            ${[300, 600, 1200].map(d => `
                                <option value="${d}" ${printerData.dpi === d ? 'selected' : ''}>${d} DPI</option>
                            `).join('')}
                        </select>
                    </div>
                    <div class="col-md-4 mb-3">
                        <label class="form-label">Label Width (mm)</label>
                        <input type="number" class="form-control" id="printerLabelWidth"
                               value="${printerData.label_width_mm}" step="0.1">
                    </div>
                    <div class="col-md-4 mb-3">
                        <label class="form-label">Label Height (mm)</label>
                        <input type="number" class="form-control" id="printerLabelHeight"
                               value="${printerData.label_height_mm}" step="0.1">
                    </div>
                </div>
                <button class="btn btn-primary" id="btnSavePrinter">
                    <i class="bi bi-save me-1"></i>Save Printer Settings
                </button>
            </div>
        </div>
    `;

    pane.querySelector('#btnSaveNfc').addEventListener('click', async () => {
        try {
            await api.put('/settings/nfc', {
                mock_mode: pane.querySelector('#nfcMockMode').checked,
                default_tag_type: pane.querySelector('#nfcDefaultTagType').value,
                verify_base_url: pane.querySelector('#nfcVerifyBaseUrl').value,
            });
            showToast('NFC settings saved.', 'success');
        } catch (err) {
            showToast('Failed to save NFC settings: ' + err.message, 'error');
        }
    });

    pane.querySelector('#btnSavePrinter').addEventListener('click', async () => {
        try {
            await api.put('/settings/printer', {
                mock_mode: pane.querySelector('#printerMockMode').checked,
                printer_name: pane.querySelector('#printerName').value,
                dpi: parseInt(pane.querySelector('#printerDpi').value),
                label_width_mm: parseFloat(pane.querySelector('#printerLabelWidth').value),
                label_height_mm: parseFloat(pane.querySelector('#printerLabelHeight').value),
            });
            showToast('Printer settings saved.', 'success');
        } catch (err) {
            showToast('Failed to save printer settings: ' + err.message, 'error');
        }
    });
}

// ------------------------------------------------------- System Tab
async function loadSystemTab() {
    const data = await api.get('/settings/system');
    const pane = _container.querySelector('#tab-system');

    const dirs = data.directory_sizes_mb || {};
    const tables = data.db_tables || {};

    pane.innerHTML = `
        <div class="card mb-4">
            <div class="card-header"><h6 class="mb-0">System Information</h6></div>
            <div class="card-body">
                <div class="row">
                    <div class="col-md-4 mb-3">
                        <strong>Version</strong>
                        <div class="text-muted">${data.version}</div>
                    </div>
                    <div class="col-md-4 mb-3">
                        <strong>Environment</strong>
                        <div><span class="badge bg-${data.environment === 'production' ? 'danger' : 'info'}">${data.environment}</span></div>
                    </div>
                    <div class="col-md-4 mb-3">
                        <strong>Data Directory</strong>
                        <div class="text-muted small text-break">${data.data_dir}</div>
                    </div>
                </div>
                <hr>
                <div class="row align-items-end">
                    <div class="col-md-4 mb-2">
                        <label class="form-label mb-1"><strong>Log Level</strong></label>
                        <select class="form-select form-select-sm" id="sysLogLevel">
                            <option value="DEBUG" ${data.log_level === 'DEBUG' ? 'selected' : ''}>DEBUG</option>
                            <option value="INFO" ${data.log_level === 'INFO' ? 'selected' : ''}>INFO</option>
                            <option value="WARNING" ${data.log_level === 'WARNING' ? 'selected' : ''}>WARNING</option>
                            <option value="ERROR" ${data.log_level === 'ERROR' ? 'selected' : ''}>ERROR</option>
                        </select>
                    </div>
                    <div class="col-md-4 mb-2">
                        <strong>Debug Mode</strong>
                        <div><span class="badge bg-${data.debug ? 'warning' : 'secondary'}">${data.debug ? 'ON' : 'OFF'}</span>
                        <small class="text-muted ms-1">(.env only)</small></div>
                    </div>
                </div>
            </div>
        </div>

        <div class="card mb-4">
            <div class="card-header"><h6 class="mb-0">Directory Sizes</h6></div>
            <div class="card-body p-0">
                <table class="table table-sm mb-0">
                    <thead class="table-light">
                        <tr><th>Directory</th><th class="text-end">Size (MB)</th></tr>
                    </thead>
                    <tbody>
                        ${Object.entries(dirs).map(([k, v]) => `
                            <tr><td>${k}</td><td class="text-end">${v}</td></tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
        </div>

        <div class="card mb-4">
            <div class="card-header"><h6 class="mb-0">Database Statistics</h6></div>
            <div class="card-body p-0">
                <table class="table table-sm mb-0">
                    <thead class="table-light">
                        <tr><th>Table</th><th class="text-end">Records</th></tr>
                    </thead>
                    <tbody>
                        ${Object.entries(tables).map(([k, v]) => `
                            <tr><td>${k.replace(/_/g, ' ')}</td><td class="text-end">${v}</td></tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
        </div>

        <div class="card mb-4">
            <div class="card-header d-flex justify-content-between align-items-center">
                <h6 class="mb-0">Database Backups</h6>
                <button class="btn btn-sm btn-primary" id="btnCreateBackup">
                    <i class="bi bi-download me-1"></i>Create Backup
                </button>
            </div>
            <div class="card-body p-0">
                <div id="backup-list-container">
                    <div class="text-center py-3 text-muted small">Loading backups...</div>
                </div>
            </div>
        </div>

        <div class="card">
            <div class="card-header"><h6 class="mb-0">Maintenance</h6></div>
            <div class="card-body">
                <div class="d-flex gap-2">
                    <button class="btn btn-outline-warning" id="btnClearDebug">
                        <i class="bi bi-trash me-1"></i>Clear Debug Images
                    </button>
                    <button class="btn btn-outline-warning" id="btnClearCache">
                        <i class="bi bi-trash me-1"></i>Clear Scan Cache
                    </button>
                </div>
            </div>
        </div>
    `;

    // Load backups list
    loadBackupsList();

    // Log level change
    pane.querySelector('#sysLogLevel')?.addEventListener('change', async (e) => {
        try {
            await api.put('/settings/system/log-level', { log_level: e.target.value });
            showToast(`Log level set to ${e.target.value}.`, 'success');
        } catch (err) {
            showToast('Failed: ' + err.message, 'error');
        }
    });

    pane.querySelector('#btnCreateBackup')?.addEventListener('click', async () => {
        try {
            const btn = pane.querySelector('#btnCreateBackup');
            btn.disabled = true;
            btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Creating...';
            const result = await api.post('/backup/create');
            showToast(`Backup created: ${result.filename}`, 'success');
            loadBackupsList();
        } catch (err) {
            showToast('Backup failed: ' + err.message, 'error');
        } finally {
            const btn = pane.querySelector('#btnCreateBackup');
            if (btn) { btn.disabled = false; btn.innerHTML = '<i class="bi bi-download me-1"></i>Create Backup'; }
        }
    });

    pane.querySelector('#btnClearDebug').addEventListener('click', async () => {
        if (!confirm('Clear all debug images? This cannot be undone.')) return;
        try {
            const result = await api.post('/settings/system/clear-debug');
            showToast(`Cleared ${result.files_removed} debug files.`, 'success');
            _loadedTabs.delete('system');
            await loadSystemTab();
        } catch (err) {
            showToast('Failed: ' + err.message, 'error');
        }
    });

    pane.querySelector('#btnClearCache').addEventListener('click', async () => {
        if (!confirm('Clear scan cache? Mock images will be preserved.')) return;
        try {
            const result = await api.post('/settings/system/clear-scan-cache');
            showToast(`Cleared ${result.files_removed} cached files.`, 'success');
            _loadedTabs.delete('system');
            await loadSystemTab();
        } catch (err) {
            showToast('Failed: ' + err.message, 'error');
        }
    });
}

// ------------------------------------------------------- Platform Changelog Tab
async function loadChangelogTab() {
    const pane = _container.querySelector('#tab-changelog');

    // Platform changelog — non-software development updates
    const entries = [
        {
            date: '2026-03-18',
            version: 'Platform v1.3',
            title: 'Training Mode & AI Calibration System',
            items: [
                { tag: 'Feature', color: '#22c55e', text: 'Training Mode page — experts enter manual grades, AI grades independently, system shows side-by-side comparison with colour-coded deltas' },
                { tag: 'Feature', color: '#22c55e', text: 'Calibration Dashboard — aggregate stats, sub-grade delta breakdown, threshold recommendation engine with admin-approved calibration' },
                { tag: 'Feature', color: '#22c55e', text: 'Ongoing training — every card an expert grades becomes a permanent training datapoint, the system continuously improves' },
                { tag: 'Analytics', color: '#3b82f6', text: 'Population reports, grade distribution stats, defect heatmaps, and per-operator bias detection via /api/analytics/*' },
                { tag: 'Analytics', color: '#3b82f6', text: 'Calibration reports with confidence levels (insufficient/low/moderate/high) based on sample count thresholds' },
                { tag: 'Architecture', color: '#8b5cf6', text: 'Profile override persistence — calibration changes saved to data/calibration/profile_overrides.json, survives restarts' },
                { tag: 'Architecture', color: '#8b5cf6', text: 'Auto-linking via event subscription — when AI grades a card, training data is automatically matched and deltas computed' },
                { tag: 'UI', color: '#06b6d4', text: 'Settings page redesigned — removed Laser/Material tab, added Platform Changelog tab, improved sidebar with descriptions' },
                { tag: 'UI', color: '#06b6d4', text: 'Agent changelog redesigned with collapsible category groups matching panel-style design' },
            ],
        },
        {
            date: '2026-03-18',
            version: 'Platform v1.2',
            title: 'Agent Telemetry, Security & Monitoring Suite',
            items: [
                { tag: 'Agent', color: '#ef4444', text: 'Station Agent v1.2.1 with system tray, rocket icon, auto-start, auto-update, and Windows toast notifications' },
                { tag: 'Telemetry', color: '#8b5cf6', text: 'Session timing, scanner quality monitoring, image tamper detection (SHA-256 + HMAC), chain of custody logging' },
                { tag: 'Telemetry', color: '#8b5cf6', text: 'Print job tracking with ink usage estimates and offline card cache for connectivity drops' },
                { tag: 'Infrastructure', color: '#3b82f6', text: 'Agent download via S3 presigned URL with versioned filenames (RKTStationAgent-v1.2.1.exe)' },
                { tag: 'UI', color: '#06b6d4', text: 'Agent changelog page with version history and download link in sidebar footer' },
            ],
        },
        {
            date: '2026-03-18',
            version: 'Platform v1.1',
            title: 'Slab Assembly & NFC Integration',
            items: [
                { tag: 'Workflow', color: '#22c55e', text: 'Slab Assembly page — 4-step wizard: Select Card, Print Insert, Program NFC, Complete' },
                { tag: 'Hardware', color: '#22c55e', text: 'Epson C6000 printer and NTag213/NTag424 DNA NFC tag support with configurable default tag type' },
                { tag: 'UI', color: '#06b6d4', text: 'NFC/Printer settings tab in Settings page for tag type, mock mode, and printer configuration' },
            ],
        },
        {
            date: '2026-03-18',
            version: 'Platform v1.0',
            title: 'Cloud Migration & Multi-Station Architecture',
            items: [
                { tag: 'Architecture', color: '#8b5cf6', text: 'Migrated from Windows desktop app to cloud-hosted web application at rktgradingstation.co.uk' },
                { tag: 'Architecture', color: '#8b5cf6', text: 'Split into cloud server (FastAPI + PostgreSQL on AWS EC2) and local Station Agent for hardware' },
                { tag: 'Infrastructure', color: '#3b82f6', text: 'EC2 t3.micro instance deployed in eu-west-2 (London) with Nginx + SSL (Lets Encrypt)' },
                { tag: 'Infrastructure', color: '#3b82f6', text: 'S3 bucket (rkt-grading-images) for card image storage with IAM role-based access' },
                { tag: 'Infrastructure', color: '#3b82f6', text: 'PostgreSQL database on same instance — WAL mode, auto-creates all 23 tables' },
                { tag: 'Security', color: '#f59e0b', text: 'HTTPS enforced with auto-redirect, X-Robots-Tag noindex to prevent search engine indexing' },
                { tag: 'Security', color: '#f59e0b', text: 'Bcrypt password hashing replacing SHA-256, with auto-upgrade on login for existing accounts' },
                { tag: 'Security', color: '#f59e0b', text: 'HMAC-SHA256 session tokens with 24-hour TTL, auth middleware on all /api/* routes' },
                { tag: 'Hardware', color: '#22c55e', text: 'Epson C6000 label printer integration — GDI printing via pywin32 at up to 1200 DPI' },
                { tag: 'Hardware', color: '#22c55e', text: 'NFC tag programming — NTag213 (basic URL) and NTag424 DNA (SUN/SDM cryptographic verification)' },
                { tag: 'Hardware', color: '#22c55e', text: 'ACR1252U NFC reader support via PC/SC (pyscard), with configurable default tag type in settings' },
                { tag: 'Domain', color: '#06b6d4', text: 'rktgradingstation.co.uk live with DNS A records pointing to Elastic IP 3.8.27.8' },
            ],
        },
        {
            date: '2026-03-18',
            version: 'Station Agent v1.2.1',
            title: 'Agent Telemetry & Monitoring Suite',
            items: [
                { tag: 'Agent', color: '#ef4444', text: 'Station Agent packaged as single 37MB Windows exe (PyInstaller --onefile) with auto-update' },
                { tag: 'Agent', color: '#ef4444', text: 'System tray with custom rocket icon, hardware status menu, and "Start with Windows" toggle' },
                { tag: 'Telemetry', color: '#8b5cf6', text: 'Session timing — tracks scan/grade/print/NFC duration per card with operator productivity stats' },
                { tag: 'Telemetry', color: '#8b5cf6', text: 'Scanner quality monitoring — brightness, contrast, sharpness, noise analysis on every scan' },
                { tag: 'Telemetry', color: '#8b5cf6', text: 'Image tamper detection — SHA-256 hash + HMAC signing on capture for cryptographic proof of origin' },
                { tag: 'Telemetry', color: '#8b5cf6', text: 'Chain of custody logging — full audit trail per card serial (station, operator, scanner, timestamp)' },
                { tag: 'Telemetry', color: '#8b5cf6', text: 'Print job tracking with ink usage estimates and cartridge remaining predictions' },
                { tag: 'Analytics', color: '#3b82f6', text: 'Cloud analytics — population reports, grade distribution, defect heatmaps, operator bias detection' },
            ],
        },
        {
            date: '2026-03-18',
            version: 'Slab Assembly v1.0',
            title: 'Slab Insert Printing & NFC Workflow',
            items: [
                { tag: 'Workflow', color: '#22c55e', text: 'Four-step slab assembly wizard: Select Card → Print Insert → Program NFC → Complete' },
                { tag: 'Workflow', color: '#22c55e', text: 'Configurable NFC tag type (NTag424 DNA default) — selectable in Settings → NFC / Printer' },
                { tag: 'Workflow', color: '#22c55e', text: 'Assembly queue with status tracking (graded → printed → NFC programmed → complete)' },
                { tag: 'Design', color: '#06b6d4', text: 'Label renderer using Pillow — serial, grade, card name at configurable DPI and dimensions' },
                { tag: 'Design', color: '#06b6d4', text: 'NFC verification endpoint (/api/slab/verify) for customer tap — decrypts PICCData, validates CMAC' },
            ],
        },
    ];

    const entriesHtml = entries.map((entry, idx) => {
        const itemsHtml = entry.items.map(item =>
            `<div class="d-flex align-items-start gap-2 mb-2">
                <span class="badge mt-1" style="background:${item.color}15; color:${item.color}; font-size:0.65rem; min-width:75px;">${item.tag}</span>
                <span class="small">${item.text}</span>
            </div>`
        ).join('');

        return `
            <div class="${idx < entries.length - 1 ? 'border-bottom pb-3 mb-3' : ''}">
                <div class="d-flex align-items-center gap-2 mb-2">
                    <span class="badge bg-primary" style="font-size:0.7rem;">${entry.version}</span>
                    <span class="text-muted small">${entry.date}</span>
                    <span class="fw-medium">${entry.title}</span>
                </div>
                ${itemsHtml}
            </div>`;
    }).join('');

    pane.innerHTML = `
        <div class="card">
            <div class="card-header">
                <h6 class="mb-0"><i class="bi bi-clock-history me-2"></i>Platform Changelog</h6>
            </div>
            <div class="card-body">
                <p class="text-muted small mb-3">Development milestones, infrastructure changes, and non-software updates.</p>
                ${entriesHtml}
            </div>
        </div>
    `;
}


async function loadBackupsList() {
    const container = document.getElementById('backup-list-container');
    if (!container) return;

    try {
        const data = await api.get('/backup/list');
        if (!data.backups || data.backups.length === 0) {
            container.innerHTML = '<div class="text-center py-3 text-muted small">No backups yet</div>';
            return;
        }
        container.innerHTML = `
            <table class="table table-sm mb-0">
                <thead class="table-light">
                    <tr><th>Filename</th><th class="text-end">Size</th><th class="text-end">Created</th><th></th></tr>
                </thead>
                <tbody>
                    ${data.backups.map(b => {
                        const sizeMB = (b.size_bytes / 1024 / 1024).toFixed(2);
                        const date = new Date(b.created_at).toLocaleString();
                        return `<tr>
                            <td class="small">${b.filename}</td>
                            <td class="text-end small">${sizeMB} MB</td>
                            <td class="text-end small">${date}</td>
                            <td class="text-end">
                                <a href="/api/backup/download/${b.filename}" class="btn btn-sm btn-outline-primary py-0 me-1" download>
                                    <i class="bi bi-download"></i>
                                </a>
                                <button class="btn btn-sm btn-outline-danger py-0 backup-delete-btn" data-filename="${b.filename}">
                                    <i class="bi bi-trash"></i>
                                </button>
                            </td>
                        </tr>`;
                    }).join('')}
                </tbody>
            </table>
        `;

        container.querySelectorAll('.backup-delete-btn').forEach(btn => {
            btn.addEventListener('click', async () => {
                const fn = btn.dataset.filename;
                if (!confirm(`Delete backup ${fn}?`)) return;
                try {
                    await api.delete(`/backup/${fn}`);
                    showToast('Backup deleted', 'success');
                    loadBackupsList();
                } catch (err) {
                    showToast('Delete failed: ' + err.message, 'error');
                }
            });
        });
    } catch (err) {
        container.innerHTML = `<div class="text-center py-3 text-danger small">${err.message}</div>`;
    }
}
