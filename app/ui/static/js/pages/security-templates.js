/**
 * Security Templates page module.
 *
 * Manages the library of security templates used for laser label generation.
 * Allows creating, editing, previewing template layouts,
 * generating pattern previews, and verifying serial numbers.
 */
import { api } from '../api.js';
import { createEmptyState, createLoadingSpinner, showToast, formatDate } from '../components.js';

// ------------------------------------------------------------------ State
let _templates = [];
let _selectedTemplate = null;
let _container = null;

// ------------------------------------------------------------------ Init / Destroy

export async function init(container) {
    _container = container;
    _render(container);
    await _loadTemplates();
}

export function destroy() {
    _templates = [];
    _selectedTemplate = null;
    _container = null;
}

// ------------------------------------------------------------------ Main Render

function _render(container) {
    container.innerHTML = `
        <div class="px-4 py-3">
            <div class="row">
                <!-- Template List (left) -->
                <div class="col-lg-4 mb-4">
                    <div class="card h-100">
                        <div class="card-header d-flex justify-content-between align-items-center">
                            <h6 class="mb-0"><i class="bi bi-shield-lock me-2"></i>Security Templates</h6>
                            <button class="btn btn-sm btn-primary" id="btn-new-template">
                                <i class="bi bi-plus-lg me-1"></i>New
                            </button>
                        </div>
                        <div class="card-body p-0" id="template-list-body">
                            ${createLoadingSpinner('Loading templates...')}
                        </div>
                    </div>
                </div>

                <!-- Template Editor + Preview (right) -->
                <div class="col-lg-8 mb-4">
                    <!-- Template Editor -->
                    <div class="card mb-3">
                        <div class="card-header"><h6 class="mb-0"><i class="bi bi-gear me-2"></i>Template Configuration</h6></div>
                        <div class="card-body" id="template-editor">
                            <div class="text-center text-muted py-4">
                                <i class="bi bi-arrow-left-circle fs-3 d-block mb-2"></i>
                                <p>Select a template or create a new one.</p>
                            </div>
                        </div>
                    </div>

                    <!-- Pattern Preview -->
                    <div class="card mb-3">
                        <div class="card-header d-flex justify-content-between align-items-center">
                            <h6 class="mb-0"><i class="bi bi-eye me-2"></i>Pattern Preview</h6>
                        </div>
                        <div class="card-body" id="pattern-preview-panel">
                            <div class="row mb-3">
                                <div class="col-md-8">
                                    <label class="form-label">Serial Number</label>
                                    <input type="text" class="form-control" id="preview-serial"
                                           placeholder="e.g. RKT-240308-A1B2C3" value="RKT-240308-A1B2C3">
                                </div>
                                <div class="col-md-4 d-flex align-items-end">
                                    <button class="btn btn-primary w-100" id="btn-generate-preview">
                                        <i class="bi bi-lightning me-1"></i>Generate Preview
                                    </button>
                                </div>
                            </div>
                            <div id="preview-output">
                                <div class="text-center text-muted py-4">
                                    <i class="bi bi-image fs-3 d-block mb-2"></i>
                                    <small>Enter a serial number and click Generate to preview patterns.</small>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- Verification Tool -->
                    <div class="card">
                        <div class="card-header">
                            <h6 class="mb-0"><i class="bi bi-shield-check me-2"></i>Verification Tool</h6>
                        </div>
                        <div class="card-body">
                            <div class="row mb-3">
                                <div class="col-md-8">
                                    <label class="form-label">Serial Number to Verify</label>
                                    <input type="text" class="form-control" id="verify-serial"
                                           placeholder="Enter serial number...">
                                </div>
                                <div class="col-md-4 d-flex align-items-end">
                                    <button class="btn btn-outline-success w-100" id="btn-verify">
                                        <i class="bi bi-check-circle me-1"></i>Verify
                                    </button>
                                </div>
                            </div>
                            <div id="verification-output"></div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `;

    // Bind events
    container.querySelector('#btn-new-template').addEventListener('click', _showNewTemplateForm);
    container.querySelector('#btn-generate-preview').addEventListener('click', _generatePreview);
    container.querySelector('#btn-verify').addEventListener('click', _runVerification);
}

// ------------------------------------------------------------------ Template List

async function _loadTemplates() {
    const listBody = _container.querySelector('#template-list-body');
    try {
        _templates = await api.get('/security/templates');
        _renderTemplateList(listBody);
    } catch (err) {
        listBody.innerHTML = createEmptyState('Failed to load templates.', 'bi-exclamation-triangle');
        showToast('Failed to load security templates: ' + err.message, 'error');
    }
}

function _renderTemplateList(listBody) {
    if (!_templates.length) {
        listBody.innerHTML = createEmptyState('No security templates yet.', 'bi-shield-lock');
        return;
    }

    let html = '<div class="list-group list-group-flush">';
    for (const t of _templates) {
        const activeClass = (_selectedTemplate && _selectedTemplate.id === t.id) ? 'active' : '';
        const defaultBadge = t.is_default
            ? '<span class="badge bg-success ms-1">Default</span>'
            : '';
        const enabledCount = t.pattern_types
            ? Object.values(t.pattern_types).filter(Boolean).length
            : 0;

        html += `
            <a href="#" class="list-group-item list-group-item-action ${activeClass}"
               data-template-id="${t.id}">
                <div class="d-flex justify-content-between align-items-start">
                    <div>
                        <div class="fw-bold">${_esc(t.name)} ${defaultBadge}</div>
                        <small class="text-muted">${_esc(t.description || 'No description')}</small>
                    </div>
                    <span class="badge bg-primary rounded-pill">${enabledCount} patterns</span>
                </div>
                <small class="text-muted">${formatDate(t.created_at)}</small>
            </a>
        `;
    }
    html += '</div>';
    listBody.innerHTML = html;

    // Click handlers
    listBody.querySelectorAll('[data-template-id]').forEach(el => {
        el.addEventListener('click', (e) => {
            e.preventDefault();
            const id = el.dataset.templateId;
            _selectTemplate(id);
        });
    });
}

async function _selectTemplate(id) {
    try {
        _selectedTemplate = await api.get(`/security/templates/${id}`);
        _renderEditor(_selectedTemplate);
        // Re-render list to show active state
        _renderTemplateList(_container.querySelector('#template-list-body'));
    } catch (err) {
        showToast('Failed to load template details: ' + err.message, 'error');
    }
}

// ------------------------------------------------------------------ Template Editor

function _showNewTemplateForm() {
    _selectedTemplate = null;
    _renderEditor({
        name: '',
        description: '',
        pattern_types: {
            microtext: true,
            dot_pattern: true,
            serial_encoding: true,
            qr_code: true,
            witness_marks: true,
        },
        microtext_height_mm: 0.4,
        dot_count: 64,
        dot_radius_mm: 0.1,
        qr_enabled: true,
        witness_marks_enabled: true,
        is_default: false,
    });
    _renderTemplateList(_container.querySelector('#template-list-body'));
}

function _renderEditor(t) {
    const editor = _container.querySelector('#template-editor');
    const pt = t.pattern_types || {};

    editor.innerHTML = `
        <form id="template-form">
            <div class="row mb-3">
                <div class="col-md-6">
                    <label class="form-label">Template Name</label>
                    <input type="text" class="form-control" id="tpl-name"
                           value="${_esc(t.name || '')}" placeholder="e.g. Standard Slab V2" required>
                </div>
                <div class="col-md-4">
                    <label class="form-label">Default Template</label>
                    <div class="form-check form-switch mt-2">
                        <input class="form-check-input" type="checkbox" id="tpl-default"
                               ${t.is_default ? 'checked' : ''}>
                        <label class="form-check-label" for="tpl-default">Set as default</label>
                    </div>
                </div>
            </div>
            <div class="mb-3">
                <label class="form-label">Description</label>
                <textarea class="form-control" id="tpl-description" rows="2"
                          placeholder="Template description...">${_esc(t.description || '')}</textarea>
            </div>

            <h6 class="border-bottom pb-2 mb-3">Pattern Types</h6>
            <div class="row mb-3">
                <div class="col-md-4">
                    <div class="form-check form-switch">
                        <input class="form-check-input" type="checkbox" id="pt-microtext"
                               ${pt.microtext !== false ? 'checked' : ''}>
                        <label class="form-check-label" for="pt-microtext">Microtext</label>
                    </div>
                </div>
                <div class="col-md-4">
                    <div class="form-check form-switch">
                        <input class="form-check-input" type="checkbox" id="pt-dot-pattern"
                               ${(pt.dot_pattern !== false && pt.dots !== false) ? 'checked' : ''}>
                        <label class="form-check-label" for="pt-dot-pattern">Dot Constellation</label>
                    </div>
                </div>
                <div class="col-md-4">
                    <div class="form-check form-switch">
                        <input class="form-check-input" type="checkbox" id="pt-serial-encoding"
                               ${pt.serial_encoding !== false ? 'checked' : ''}>
                        <label class="form-check-label" for="pt-serial-encoding">Serial Encoding</label>
                    </div>
                </div>
            </div>
            <div class="row mb-3">
                <div class="col-md-4">
                    <div class="form-check form-switch">
                        <input class="form-check-input" type="checkbox" id="pt-qr-code"
                               ${pt.qr_code !== false ? 'checked' : ''}>
                        <label class="form-check-label" for="pt-qr-code">QR Code</label>
                    </div>
                </div>
                <div class="col-md-4">
                    <div class="form-check form-switch">
                        <input class="form-check-input" type="checkbox" id="pt-witness-marks"
                               ${pt.witness_marks !== false ? 'checked' : ''}>
                        <label class="form-check-label" for="pt-witness-marks">Witness Marks</label>
                    </div>
                </div>
            </div>

            <h6 class="border-bottom pb-2 mb-3">Pattern Parameters</h6>
            <div class="row mb-3">
                <div class="col-md-4">
                    <label class="form-label">Microtext Height (mm)</label>
                    <input type="number" class="form-control" id="tpl-microtext-height"
                           value="${t.microtext_height_mm || 0.4}" min="0.2" max="1.0" step="0.05">
                </div>
                <div class="col-md-4">
                    <label class="form-label">Dot Count</label>
                    <input type="number" class="form-control" id="tpl-dot-count"
                           value="${t.dot_count || 64}" min="16" max="256" step="8">
                </div>
                <div class="col-md-4">
                    <label class="form-label">Dot Radius (mm)</label>
                    <input type="number" class="form-control" id="tpl-dot-radius"
                           value="${t.dot_radius_mm || 0.1}" min="0.05" max="0.5" step="0.01">
                </div>
            </div>

            <div class="d-flex gap-2">
                <button type="submit" class="btn btn-primary">
                    <i class="bi bi-save me-1"></i>Save Template
                </button>
                <button type="button" class="btn btn-outline-secondary" id="btn-cancel-edit">
                    Cancel
                </button>
            </div>
        </form>
    `;

    editor.querySelector('#template-form').addEventListener('submit', _saveTemplate);
    editor.querySelector('#btn-cancel-edit').addEventListener('click', () => {
        _selectedTemplate = null;
        editor.innerHTML = `
            <div class="text-center text-muted py-4">
                <i class="bi bi-arrow-left-circle fs-3 d-block mb-2"></i>
                <p>Select a template or create a new one.</p>
            </div>
        `;
        _renderTemplateList(_container.querySelector('#template-list-body'));
    });
}

async function _saveTemplate(e) {
    e.preventDefault();

    const payload = {
        name: _container.querySelector('#tpl-name').value.trim(),
        description: _container.querySelector('#tpl-description').value.trim(),
        pattern_types: {
            microtext: _container.querySelector('#pt-microtext').checked,
            dot_pattern: _container.querySelector('#pt-dot-pattern').checked,
            serial_encoding: _container.querySelector('#pt-serial-encoding').checked,
            qr_code: _container.querySelector('#pt-qr-code').checked,
            witness_marks: _container.querySelector('#pt-witness-marks').checked,
        },
        microtext_height_mm: parseFloat(_container.querySelector('#tpl-microtext-height').value) || 0.4,
        dot_count: parseInt(_container.querySelector('#tpl-dot-count').value) || 64,
        dot_radius_mm: parseFloat(_container.querySelector('#tpl-dot-radius').value) || 0.1,
        qr_enabled: _container.querySelector('#pt-qr-code').checked,
        witness_marks_enabled: _container.querySelector('#pt-witness-marks').checked,
        is_default: _container.querySelector('#tpl-default').checked,
    };

    if (!payload.name) {
        showToast('Template name is required.', 'warning');
        return;
    }

    try {
        const result = await api.post('/security/templates', payload);
        showToast(`Template "${payload.name}" ${result.status}.`, 'success');
        await _loadTemplates();
        if (result.id) {
            await _selectTemplate(result.id);
        }
    } catch (err) {
        showToast('Failed to save template: ' + err.message, 'error');
    }
}

// ------------------------------------------------------------------ Pattern Preview

async function _generatePreview() {
    const serial = _container.querySelector('#preview-serial').value.trim();
    if (!serial) {
        showToast('Enter a serial number to preview.', 'warning');
        return;
    }

    const output = _container.querySelector('#preview-output');
    output.innerHTML = createLoadingSpinner('Generating patterns...');

    try {
        const templateId = _selectedTemplate ? _selectedTemplate.id : undefined;
        const url = templateId
            ? `/security/preview/${encodeURIComponent(serial)}?template_id=${templateId}`
            : `/security/preview/${encodeURIComponent(serial)}`;
        const result = await api.get(url);

        let html = '';

        // Combined SVG preview
        html += `
            <div class="mb-3">
                <h6 class="text-muted">Combined Security Layer</h6>
                <div class="border rounded p-2 bg-white text-center" style="overflow:auto; max-height:300px;">
                    ${result.combined_svg}
                </div>
                <small class="text-muted">
                    Verification hash: <code>${_esc(result.verification_hash || '')}</code>
                </small>
            </div>
        `;

        // Individual pattern previews
        if (result.patterns && result.patterns.length) {
            html += '<h6 class="text-muted mb-2">Individual Patterns</h6>';
            html += '<div class="row">';
            for (const p of result.patterns) {
                const label = _patternLabel(p.pattern_type);
                html += `
                    <div class="col-md-6 mb-3">
                        <div class="card">
                            <div class="card-header py-1">
                                <small class="fw-bold">${label}</small>
                                <span class="badge bg-secondary float-end">${p.pattern_type}</span>
                            </div>
                            <div class="card-body p-2">
                                <div class="border rounded bg-white text-center p-1"
                                     style="overflow:auto; max-height:150px; font-size:0;">
                                    <svg xmlns="http://www.w3.org/2000/svg"
                                         width="${p.width_mm || 50}mm" height="${p.height_mm || 20}mm"
                                         viewBox="0 0 ${p.width_mm || 50} ${p.height_mm || 20}"
                                         style="max-width:100%; height:auto;">
                                        ${p.svg}
                                    </svg>
                                </div>
                            </div>
                        </div>
                    </div>
                `;
            }
            html += '</div>';
        }

        output.innerHTML = html;
    } catch (err) {
        output.innerHTML = `
            <div class="alert alert-danger">
                <i class="bi bi-exclamation-triangle me-2"></i>
                Preview failed: ${_esc(err.message)}
            </div>
        `;
    }
}

// ------------------------------------------------------------------ Verification

async function _runVerification() {
    const serial = _container.querySelector('#verify-serial').value.trim();
    if (!serial) {
        showToast('Enter a serial number to verify.', 'warning');
        return;
    }

    const output = _container.querySelector('#verification-output');
    output.innerHTML = createLoadingSpinner('Verifying...');

    try {
        const result = await api.post('/security/verify', { serial_number: serial });

        const validClass = result.is_valid ? 'success' : 'danger';
        const validIcon = result.is_valid ? 'bi-check-circle-fill' : 'bi-x-circle-fill';
        const validLabel = result.is_valid ? 'VALID' : 'INVALID';

        let html = `
            <div class="alert alert-${validClass} d-flex align-items-center">
                <i class="bi ${validIcon} fs-4 me-3"></i>
                <div>
                    <strong>${validLabel}</strong> --
                    Overall match: ${(result.overall_match_pct || 0).toFixed(1)}%
                    <br>
                    <small>Verification code: <code>${_esc(result.verification_code || '')}</code>
                    | Hash: <code>${_esc((result.verification_hash || '').substring(0, 16))}...</code></small>
                </div>
            </div>
        `;

        // Pattern match details
        if (result.pattern_matches && result.pattern_matches.length) {
            html += '<table class="table table-sm">';
            html += '<thead><tr><th>Pattern</th><th>Match</th><th>Expected</th><th>Matched</th><th>Details</th></tr></thead>';
            html += '<tbody>';
            for (const m of result.pattern_matches) {
                const rowClass = m.match_percentage >= 80 ? 'table-success'
                              : m.match_percentage >= 50 ? 'table-warning'
                              : 'table-danger';
                html += `
                    <tr class="${rowClass}">
                        <td>${_patternLabel(m.pattern_type)}</td>
                        <td><strong>${m.match_percentage.toFixed(1)}%</strong></td>
                        <td>${m.expected_count}</td>
                        <td>${m.matched_count}</td>
                        <td><small>${_esc(m.details)}</small></td>
                    </tr>
                `;
            }
            html += '</tbody></table>';
        }

        // Errors
        if (result.errors && result.errors.length) {
            html += '<div class="alert alert-warning"><strong>Warnings:</strong><ul class="mb-0">';
            for (const e of result.errors) {
                html += `<li>${_esc(e)}</li>`;
            }
            html += '</ul></div>';
        }

        output.innerHTML = html;
    } catch (err) {
        output.innerHTML = `
            <div class="alert alert-danger">
                <i class="bi bi-exclamation-triangle me-2"></i>
                Verification failed: ${_esc(err.message)}
            </div>
        `;
    }
}

// ------------------------------------------------------------------ Helpers

function _patternLabel(type) {
    const labels = {
        microtext: 'Microtext',
        dot_pattern: 'Dot Constellation',
        serial_encoding: 'Serial Encoding',
        qr_code: 'QR Code',
        qr_fallback: 'QR Code (Fallback)',
        qr_placeholder: 'QR Placeholder',
        datamatrix: 'DataMatrix',
        witness_seam: 'Seam Witnesses',
        witness_alignment: 'Alignment Marks',
        witness_hidden: 'Hidden Pattern',
        combined: 'Combined',
    };
    return labels[type] || type;
}

function _esc(str) {
    if (!str) return '';
    const el = document.createElement('span');
    el.textContent = str;
    return el.innerHTML;
}
