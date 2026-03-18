/**
 * Calibration Dashboard — aggregate training stats, delta breakdowns,
 * and threshold calibration recommendations.
 */
import { api } from '../api.js';
import { showToast } from '../components.js';

export async function init(container) {
    container.innerHTML = `
        <div class="px-4 py-3">
            <div class="d-flex justify-content-between align-items-center mb-3">
                <h5 class="mb-0"><i class="bi bi-sliders me-2"></i>Calibration Dashboard</h5>
                <a href="#/training" class="btn btn-sm btn-outline-primary">
                    <i class="bi bi-mortarboard me-1"></i>Training Mode
                </a>
            </div>
            <div id="cal-content">
                <div class="text-center py-4"><div class="spinner-border spinner-border-sm text-primary"></div></div>
            </div>
        </div>`;

    await loadDashboard();
}

export function destroy() {}

async function loadDashboard() {
    const content = document.getElementById('cal-content');

    try {
        const stats = await api.get('/training/stats');

        if (stats.sample_count === 0) {
            content.innerHTML = `
                <div class="card">
                    <div class="card-body text-center py-5 text-muted">
                        <i class="bi bi-mortarboard fs-1 d-block mb-3"></i>
                        <h6>No training data yet</h6>
                        <p class="small">Go to <a href="#/training">Training Mode</a> to start grading cards. The system needs expert grades to calibrate against.</p>
                    </div>
                </div>`;
            return;
        }

        const avg = stats.avg_deltas || {};
        const std = stats.std_deltas || {};

        function deltaCard(label, icon, avgVal, stdVal) {
            const abs = Math.abs(avgVal || 0);
            const color = abs <= 0.3 ? 'success' : abs <= 0.7 ? 'warning' : 'danger';
            const direction = (avgVal || 0) > 0 ? 'AI grades higher' : (avgVal || 0) < 0 ? 'AI grades lower' : 'Aligned';
            const sign = (avgVal || 0) > 0 ? '+' : '';
            return `
                <div class="col-md-3">
                    <div class="card h-100">
                        <div class="card-body text-center">
                            <i class="bi ${icon} fs-4 text-${color} d-block mb-1"></i>
                            <div class="small text-muted">${label}</div>
                            <div class="fs-4 fw-bold text-${color}">${sign}${(avgVal || 0).toFixed(2)}</div>
                            <div class="small text-muted">&plusmn;${(stdVal || 0).toFixed(2)} std</div>
                            <div class="small text-${color}">${direction}</div>
                        </div>
                    </div>
                </div>`;
        }

        content.innerHTML = `
            <!-- Summary row -->
            <div class="row g-3 mb-3">
                <div class="col-md-3">
                    <div class="card h-100">
                        <div class="card-body text-center">
                            <div class="fs-4 fw-bold text-primary">${stats.sample_count}</div>
                            <div class="small text-muted">Training Samples</div>
                        </div>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="card h-100">
                        <div class="card-body text-center">
                            <div class="fs-4 fw-bold ${stats.match_rate >= 70 ? 'text-success' : stats.match_rate >= 50 ? 'text-warning' : 'text-danger'}">${stats.match_rate}%</div>
                            <div class="small text-muted">Grade Match Rate</div>
                            <div class="small text-muted">(within 0.5)</div>
                        </div>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="card h-100">
                        <div class="card-body text-center">
                            <div class="fs-4 fw-bold">${Math.abs(avg.final || 0).toFixed(2)}</div>
                            <div class="small text-muted">Avg Final Delta</div>
                        </div>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="card h-100">
                        <div class="card-body text-center">
                            <div class="fs-4 fw-bold">${(std.final || 0).toFixed(2)}</div>
                            <div class="small text-muted">Std Deviation</div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Sub-grade breakdown -->
            <div class="row g-3 mb-3">
                ${deltaCard('Centering', 'bi-arrows-expand', avg.centering, std.centering)}
                ${deltaCard('Corners', 'bi-border-style', avg.corners, std.corners)}
                ${deltaCard('Edges', 'bi-border-all', avg.edges, std.edges)}
                ${deltaCard('Surface', 'bi-card-image', avg.surface, std.surface)}
            </div>

            <!-- Calibration panel -->
            <div class="card mb-3">
                <div class="card-header d-flex justify-content-between align-items-center">
                    <span><i class="bi bi-wrench me-2"></i>Calibration</span>
                    <button class="btn btn-sm btn-primary" id="btn-generate-report">
                        <i class="bi bi-gear me-1"></i>Generate Report
                    </button>
                </div>
                <div class="card-body" id="cal-report-area">
                    <p class="text-muted small mb-0">Generate a calibration report to see threshold adjustment recommendations based on training data.</p>
                </div>
            </div>

            <!-- History -->
            <div class="card">
                <div class="card-header"><i class="bi bi-clock-history me-2"></i>Calibration History</div>
                <div class="card-body p-0" id="cal-history"></div>
            </div>`;

        document.getElementById('btn-generate-report')?.addEventListener('click', generateReport);
        await loadHistory();

    } catch (e) {
        content.innerHTML = `<div class="alert alert-warning">${e.message}</div>`;
    }
}

async function generateReport() {
    const area = document.getElementById('cal-report-area');
    area.innerHTML = '<div class="text-center py-3"><div class="spinner-border spinner-border-sm text-primary"></div></div>';

    try {
        const report = await api.get('/training/calibration');

        if (!report.recommendations?.length) {
            area.innerHTML = `
                <div class="alert alert-info py-2 small mb-0">
                    <i class="bi bi-check-circle me-1"></i>
                    No threshold adjustments needed (${report.sample_count} samples, confidence: ${report.confidence}).
                    All sub-grade deltas are within acceptable range (&le;0.5).
                </div>`;
            await loadHistory();
            return;
        }

        area.innerHTML = `
            <div class="alert alert-warning py-2 small mb-3">
                <i class="bi bi-exclamation-triangle me-1"></i>
                ${report.recommendations.length} recommendation(s) based on ${report.sample_count} samples (confidence: <strong>${report.confidence}</strong>)
            </div>
            <div class="table-responsive mb-3">
                <table class="table table-sm mb-0">
                    <thead><tr><th>Sub-Grade</th><th>Threshold</th><th>Direction</th><th>Current Delta</th><th>Description</th></tr></thead>
                    <tbody>
                        ${report.recommendations.map(r => `
                            <tr>
                                <td class="fw-medium">${r.sub_grade}</td>
                                <td><code>${r.threshold}</code></td>
                                <td><span class="badge bg-${r.direction === 'tighten' ? 'danger' : 'success'}">${r.direction}</span></td>
                                <td>${r.current_delta > 0 ? '+' : ''}${r.current_delta.toFixed(2)}</td>
                                <td class="small">${r.description}</td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
            <button class="btn btn-warning" id="btn-apply-cal" data-report-id="${report.id}">
                <i class="bi bi-check2-all me-1"></i>Apply Calibration
            </button>
            <div id="apply-status" class="mt-2"></div>`;

        document.getElementById('btn-apply-cal')?.addEventListener('click', async () => {
            const btn = document.getElementById('btn-apply-cal');
            const reportId = btn.dataset.reportId;
            const op = JSON.parse(localStorage.getItem('rkt-operator') || '{}');

            if (!confirm('Apply these threshold changes? This will adjust the grading engine sensitivity.')) return;

            btn.disabled = true;
            btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Applying...';

            try {
                const result = await api.post('/training/calibrate/apply', {
                    report_id: reportId,
                    operator: op.name || 'admin',
                });
                document.getElementById('apply-status').innerHTML = `
                    <div class="alert alert-success py-2 small">
                        <i class="bi bi-check-circle me-1"></i>
                        Applied ${result.changes?.length || 0} threshold change(s).
                        ${result.changes?.map(c => `<br><code>${c.threshold}</code>: ${c.old_value} → ${c.new_value}`).join('') || ''}
                    </div>`;
                showToast('Calibration applied!', 'success');
                await loadHistory();
            } catch (e) {
                document.getElementById('apply-status').innerHTML = `<div class="alert alert-danger py-2 small">${e.message}</div>`;
                btn.disabled = false;
                btn.innerHTML = '<i class="bi bi-check2-all me-1"></i>Apply Calibration';
            }
        });

        await loadHistory();

    } catch (e) {
        area.innerHTML = `<div class="alert alert-danger py-2 small">${e.message}</div>`;
    }
}

async function loadHistory() {
    const container = document.getElementById('cal-history');
    if (!container) return;

    try {
        const res = await api.get('/training/calibration/history');
        if (!res.reports?.length) {
            container.innerHTML = '<div class="text-center text-muted py-3 small">No calibration reports yet</div>';
            return;
        }

        container.innerHTML = `
            <table class="table table-sm table-hover mb-0">
                <thead><tr><th>Date</th><th>Samples</th><th>Match Rate</th><th>Avg Delta</th><th>Recommendations</th><th>Status</th></tr></thead>
                <tbody>
                    ${res.reports.map(r => `
                        <tr>
                            <td class="small">${r.created_at?.split('T')[0] || '—'}</td>
                            <td>${r.sample_count}</td>
                            <td>${r.match_rate?.toFixed(1) || '—'}%</td>
                            <td>${r.avg_delta_final?.toFixed(2) || '—'}</td>
                            <td>${r.recommendations_count}</td>
                            <td>${r.applied
                                ? `<span class="badge bg-success">Applied</span> <small class="text-muted">${r.applied_by}</small>`
                                : '<span class="badge bg-secondary">Not applied</span>'}</td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>`;
    } catch {
        container.innerHTML = '<div class="text-muted small p-3">Error loading history</div>';
    }
}
