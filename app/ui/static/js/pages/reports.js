/**
 * Reports page module.
 *
 * Dashboard-style analytics with Chart.js charts: grade distribution,
 * daily volume, authenticity results, top defects, override rate,
 * and processing time.
 */
import { api } from '../api.js';
import { createStatCard, createLoadingSpinner, showToast } from '../components.js';

const CHART_CDN = 'https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js';

/** Chart instances for cleanup on destroy. */
let _charts = {};
let _container = null;

// ------------------------------------------------------------------
// Chart.js dynamic loader
// ------------------------------------------------------------------

function loadChartJs() {
    return new Promise((resolve, reject) => {
        if (window.Chart) { resolve(window.Chart); return; }
        const existing = document.querySelector(`script[src="${CHART_CDN}"]`);
        if (existing) {
            existing.addEventListener('load', () => resolve(window.Chart));
            existing.addEventListener('error', reject);
            return;
        }
        const script = document.createElement('script');
        script.src = CHART_CDN;
        script.onload = () => resolve(window.Chart);
        script.onerror = () => reject(new Error('Failed to load Chart.js'));
        document.head.appendChild(script);
    });
}

// ------------------------------------------------------------------
// Lifecycle
// ------------------------------------------------------------------

export async function init(container) {
    _container = container;
    container.innerHTML = buildLayout();
    bindEvents();
    try {
        await loadChartJs();
        await refreshAll();
    } catch (err) {
        console.error('Reports init error:', err);
        showToast('Failed to load reports: ' + err.message, 'error');
    }
}

export function destroy() {
    Object.values(_charts).forEach(c => { try { c.destroy(); } catch { /* noop */ } });
    _charts = {};
    _container = null;
}

// ------------------------------------------------------------------
// Layout
// ------------------------------------------------------------------

function buildLayout() {
    return `
        <div class="px-4 py-3">
            <!-- Date Filter Bar -->
            <div class="card mb-4">
                <div class="card-header d-flex justify-content-between align-items-center flex-wrap gap-2">
                    <h6 class="mb-0"><i class="bi bi-graph-up me-2"></i>Reports Dashboard</h6>
                    <div class="d-flex gap-2 align-items-center flex-wrap">
                        <label class="form-label mb-0 small text-muted">From</label>
                        <input type="date" id="report-date-start" class="form-control form-control-sm" style="width:150px;">
                        <label class="form-label mb-0 small text-muted">To</label>
                        <input type="date" id="report-date-end" class="form-control form-control-sm" style="width:150px;">
                        <button id="btn-apply-dates" class="btn btn-sm btn-primary">
                            <i class="bi bi-funnel me-1"></i>Apply
                        </button>
                        <button id="btn-refresh-reports" class="btn btn-sm btn-outline-secondary">
                            <i class="bi bi-arrow-clockwise me-1"></i>Refresh
                        </button>
                    </div>
                </div>
            </div>

            <!-- Summary Stat Cards -->
            <div class="row" id="summary-cards">
                ${createStatCard('Total Cards', '--', 'in date range', 'bi-clipboard-check', 'primary')}
                ${createStatCard('Avg Grade', '--', '', 'bi-bar-chart', 'success')}
                ${createStatCard('Pass Rate', '--', 'grade >= 7.0', 'bi-check-circle', 'info')}
                ${createStatCard('Avg Processing', '--', 'scan to grade', 'bi-clock', 'warning')}
            </div>

            <!-- Charts Row 1 -->
            <div class="row">
                <div class="col-lg-6 mb-4">
                    <div class="card h-100">
                        <div class="card-header"><h6 class="mb-0">Grade Distribution</h6></div>
                        <div class="card-body">
                            <canvas id="chart-grade-dist"></canvas>
                        </div>
                    </div>
                </div>
                <div class="col-lg-6 mb-4">
                    <div class="card h-100">
                        <div class="card-header"><h6 class="mb-0">Daily Volume (Last 30 Days)</h6></div>
                        <div class="card-body">
                            <canvas id="chart-daily-volume"></canvas>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Charts Row 2 -->
            <div class="row">
                <div class="col-lg-4 mb-4">
                    <div class="card h-100">
                        <div class="card-header"><h6 class="mb-0">Authenticity Results</h6></div>
                        <div class="card-body d-flex justify-content-center align-items-center">
                            <canvas id="chart-auth-rate" style="max-height:280px;"></canvas>
                        </div>
                    </div>
                </div>
                <div class="col-lg-4 mb-4">
                    <div class="card h-100">
                        <div class="card-header"><h6 class="mb-0">Override Rate</h6></div>
                        <div class="card-body d-flex justify-content-center align-items-center">
                            <canvas id="chart-override" style="max-height:280px;"></canvas>
                        </div>
                    </div>
                </div>
                <div class="col-lg-4 mb-4">
                    <div class="card h-100">
                        <div class="card-header"><h6 class="mb-0">Processing Time</h6></div>
                        <div class="card-body d-flex justify-content-center align-items-center">
                            <canvas id="chart-processing" style="max-height:280px;"></canvas>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Charts Row 3 -->
            <div class="row">
                <div class="col-lg-12 mb-4">
                    <div class="card">
                        <div class="card-header"><h6 class="mb-0">Top Defects</h6></div>
                        <div class="card-body">
                            <canvas id="chart-top-defects" style="max-height:350px;"></canvas>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `;
}

// ------------------------------------------------------------------
// Events
// ------------------------------------------------------------------

function bindEvents() {
    _container.querySelector('#btn-apply-dates')?.addEventListener('click', refreshAll);
    _container.querySelector('#btn-refresh-reports')?.addEventListener('click', refreshAll);
}

function getDateParams() {
    const start = _container.querySelector('#report-date-start')?.value;
    const end = _container.querySelector('#report-date-end')?.value;
    const params = new URLSearchParams();
    if (start) params.set('date_start', start);
    if (end) params.set('date_end', end);
    const qs = params.toString();
    return qs ? '?' + qs : '';
}

// ------------------------------------------------------------------
// Data loading & chart rendering
// ------------------------------------------------------------------

async function refreshAll() {
    if (!_container) return;
    const qs = getDateParams();

    try {
        const [summary, gradeDist, volume, authRate, override, processing, defects] =
            await Promise.all([
                api.get('/reports/summary' + qs),
                api.get('/reports/grade-distribution' + qs),
                api.get('/reports/daily-volume' + qs),
                api.get('/reports/authenticity-rate' + qs),
                api.get('/reports/override-rate' + qs),
                api.get('/reports/processing-time' + qs),
                api.get('/reports/defect-frequency' + qs),
            ]);

        updateSummaryCards(summary);
        renderBarChart('chart-grade-dist', 'gradeDist', gradeDist, 'Grade Distribution');
        renderLineChart('chart-daily-volume', 'dailyVol', volume, 'Cards per Day');
        renderDoughnutChart('chart-auth-rate', 'authRate', authRate, 'Authenticity');
        renderPieChart('chart-override', 'override', override, 'Override Rate');
        renderBarChart('chart-processing', 'processing', processing, 'Avg Minutes');
        renderHorizontalBarChart('chart-top-defects', 'defects', defects, 'Defect Frequency');
    } catch (err) {
        console.error('Reports refresh error:', err);
        showToast('Error refreshing reports: ' + err.message, 'error');
    }
}

function updateSummaryCards(data) {
    const cards = _container.querySelectorAll('.stat-card');
    if (cards.length >= 4) {
        cards[0].querySelector('.stat-value').textContent = data.total_cards ?? '--';
        cards[1].querySelector('.stat-value').textContent = data.avg_grade ?? '--';
        cards[2].querySelector('.stat-value').textContent = data.pass_rate != null ? data.pass_rate + '%' : '--';
        cards[3].querySelector('.stat-value').textContent =
            data.avg_processing_minutes != null ? data.avg_processing_minutes + ' min' : '--';
    }
}

// ------------------------------------------------------------------
// Chart factories
// ------------------------------------------------------------------

function getOrCreateChart(canvasId, key, type, config) {
    if (_charts[key]) { _charts[key].destroy(); }
    const ctx = _container.querySelector('#' + canvasId);
    if (!ctx) return null;
    _charts[key] = new Chart(ctx, { type, ...config });
    return _charts[key];
}

function renderBarChart(canvasId, key, chartData, title) {
    getOrCreateChart(canvasId, key, 'bar', {
        data: chartData,
        options: {
            responsive: true,
            maintainAspectRatio: true,
            plugins: {
                legend: { display: false },
                title: { display: false },
            },
            scales: {
                y: { beginAtZero: true, ticks: { precision: 0 } },
            },
        },
    });
}

function renderLineChart(canvasId, key, chartData, title) {
    getOrCreateChart(canvasId, key, 'line', {
        data: chartData,
        options: {
            responsive: true,
            maintainAspectRatio: true,
            plugins: {
                legend: { display: false },
            },
            scales: {
                y: { beginAtZero: true, ticks: { precision: 0 } },
                x: {
                    ticks: {
                        maxTicksLimit: 15,
                        maxRotation: 45,
                    },
                },
            },
        },
    });
}

function renderDoughnutChart(canvasId, key, chartData, title) {
    getOrCreateChart(canvasId, key, 'doughnut', {
        data: chartData,
        options: {
            responsive: true,
            maintainAspectRatio: true,
            plugins: {
                legend: { position: 'bottom' },
            },
        },
    });
}

function renderPieChart(canvasId, key, chartData, title) {
    getOrCreateChart(canvasId, key, 'pie', {
        data: chartData,
        options: {
            responsive: true,
            maintainAspectRatio: true,
            plugins: {
                legend: { position: 'bottom' },
            },
        },
    });
}

function renderHorizontalBarChart(canvasId, key, chartData, title) {
    getOrCreateChart(canvasId, key, 'bar', {
        data: chartData,
        options: {
            indexAxis: 'y',
            responsive: true,
            maintainAspectRatio: true,
            plugins: {
                legend: { display: false },
            },
            scales: {
                x: { beginAtZero: true, ticks: { precision: 0 } },
            },
        },
    });
}
