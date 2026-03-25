/**
 * Dashboard page module.
 *
 * Fetches summary stats and recent activity from the API and renders
 * a top-level overview with quick-action shortcuts and system status.
 */
import { api } from '../api.js';
import { createStatCard, createEmptyState, createLoadingSpinner, formatDate, createStatusBadge, escapeHtml } from '../components.js';

function buildStatusRow(label, statusText, isOk) {
    const bg = isOk ? 'bg-success-subtle text-success' : 'bg-warning-subtle text-warning';
    return `<div class="d-flex justify-content-between mb-2">
        <span>${label}</span>
        <span class="badge ${bg}">
            <i class="bi bi-circle-fill me-1" style="font-size: 0.5rem;"></i>${statusText}
        </span>
    </div>`;
}

export async function init(container) {
    container.innerHTML = createLoadingSpinner('Loading dashboard...');

    try {
        const [summary, activity] = await Promise.all([
            api.get('/dashboard/summary'),
            api.get('/dashboard/recent-activity'),
        ]);

        container.innerHTML = `
            <div class="px-4 py-3">
                <!-- Stat Cards -->
                <div class="row mb-4">
                    ${createStatCard('Total Scans',    summary.total_scans,    '', 'bi-camera',             'primary')}
                    ${createStatCard('Graded',         summary.total_graded,   '', 'bi-clipboard-check',    'success')}
                    ${createStatCard('Pending Review', summary.pending_review, '', 'bi-hourglass-split',    'warning')}
                    ${createStatCard('Auth Alerts',    summary.auth_alerts,    '', 'bi-shield-exclamation', 'danger')}
                </div>

                <div class="row">
                    <!-- Recent Activity -->
                    <div class="col-lg-8 mb-4">
                        <div class="card">
                            <div class="card-header d-flex justify-content-between align-items-center">
                                <h6 class="mb-0">Recent Activity</h6>
                                <a href="#/audit-log" class="btn btn-sm btn-outline-secondary">View All</a>
                            </div>
                            <div class="card-body p-0">
                                ${activity.length > 0 ? `
                                    <div class="table-responsive">
                                        <table class="table table-hover mb-0">
                                            <thead class="table-light">
                                                <tr>
                                                    <th>Action</th>
                                                    <th>Type</th>
                                                    <th>Operator</th>
                                                    <th>Time</th>
                                                </tr>
                                            </thead>
                                            <tbody>
                                                ${activity.map(e => `
                                                    <tr>
                                                        <td>${escapeHtml(e.action)}</td>
                                                        <td><span class="badge bg-light text-dark">${escapeHtml(e.event_type || '\u2014')}</span></td>
                                                        <td>${escapeHtml(e.operator || '\u2014')}</td>
                                                        <td class="text-muted small">${formatDate(e.created_at)}</td>
                                                    </tr>
                                                `).join('')}
                                            </tbody>
                                        </table>
                                    </div>
                                ` : createEmptyState('No recent activity yet.', 'bi-clock-history')}
                            </div>
                        </div>
                    </div>

                    <!-- Sidebar: Quick Actions + System Status -->
                    <div class="col-lg-4 mb-4">
                        <div class="card mb-3">
                            <div class="card-header"><h6 class="mb-0">Quick Actions</h6></div>
                            <div class="card-body">
                                <a href="#/scan" class="btn btn-primary w-100 mb-2">
                                    <i class="bi bi-camera me-2"></i>Start New Scan
                                </a>
                                <a href="#/queue" class="btn btn-outline-primary w-100 mb-2">
                                    <i class="bi bi-list-task me-2"></i>Review Queue
                                </a>
                            </div>
                        </div>

                        <div class="card">
                            <div class="card-header"><h6 class="mb-0">System Status</h6></div>
                            <div class="card-body">
                                ${buildStatusRow('Scanner', (() => {
                                    const ss = summary.system_status;
                                    if (ss?.scanner_mock && ss?.scanner_connected) return 'Mock Mode (Scanner Available)';
                                    if (ss?.scanner_mock && !ss?.scanner_connected) return 'Mock Mode (No Scanner)';
                                    if (!ss?.scanner_mock && ss?.scanner_connected) return 'Connected';
                                    return 'Not Connected';
                                })(), summary.system_status?.scanner_connected)}
                                ${buildStatusRow('Database', 'Connected', true)}
                                ${buildStatusRow('PokeWallet API', summary.system_status?.pokewallet_ready ? 'Ready' : 'No Key', summary.system_status?.pokewallet_ready)}
                                ${buildStatusRow('OpenRouter AI', summary.system_status?.openrouter_ready ? 'Active' : (summary.system_status?.openrouter_enabled ? 'No Key' : 'Disabled'), summary.system_status?.openrouter_ready)}
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;
    } catch (err) {
        container.innerHTML = `
            <div class="alert alert-danger m-4">
                <i class="bi bi-exclamation-triangle me-2"></i>
                Failed to load dashboard: ${escapeHtml(err.message)}
            </div>`;
    }
}

export function destroy() {}
