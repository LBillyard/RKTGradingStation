/**
 * Agent Changelog — detailed release history for the RKT Station Agent.
 */
import { api } from '../api.js';

const CATEGORY_BADGES = {
    feature:     { label: 'New',         bg: 'bg-success' },
    improvement: { label: 'Improved',    bg: 'bg-primary' },
    fix:         { label: 'Fixed',       bg: 'bg-danger' },
    security:    { label: 'Security',    bg: 'bg-warning text-dark' },
    deprecated:  { label: 'Deprecated',  bg: 'bg-secondary' },
    removed:     { label: 'Removed',     bg: 'bg-dark' },
};

const TYPE_LABELS = {
    release: 'Release',
    patch:   'Patch',
    hotfix:  'Hotfix',
};

export async function init(container) {
    container.innerHTML = `
        <div class="px-4 py-3">
            <div class="d-flex justify-content-between align-items-center mb-3">
                <h5 class="mb-0"><i class="bi bi-journal-text me-2"></i>Station Agent Changelog</h5>
                <a href="/api/agent/download" class="btn btn-sm btn-primary">
                    <i class="bi bi-download me-1"></i>Download Latest
                </a>
            </div>
            <div id="changelog-content">
                <div class="text-center py-4">
                    <div class="spinner-border text-primary" role="status"></div>
                </div>
            </div>
        </div>`;

    try {
        const changelog = await api.get('/agent/changelog');
        const content = document.getElementById('changelog-content');

        if (!changelog || changelog.length === 0) {
            content.innerHTML = '<div class="text-center text-muted py-4">No changelog entries yet.</div>';
            return;
        }

        content.innerHTML = changelog.map((release, idx) => {
            const typeBadge = TYPE_LABELS[release.type] || 'Update';
            const isLatest = idx === 0;

            const changesHtml = release.changes.map(change => {
                const cat = CATEGORY_BADGES[change.category] || CATEGORY_BADGES.feature;
                return `
                    <div class="d-flex align-items-start gap-2 mb-2">
                        <span class="badge ${cat.bg} mt-1" style="min-width: 70px; font-size: 0.7rem;">${cat.label}</span>
                        <span class="small">${change.description}</span>
                    </div>`;
            }).join('');

            return `
                <div class="card mb-3 ${isLatest ? 'border-primary' : ''}">
                    <div class="card-header d-flex justify-content-between align-items-center ${isLatest ? 'bg-primary bg-opacity-10' : ''}">
                        <div>
                            <strong class="me-2">v${release.version}</strong>
                            <span class="badge bg-secondary me-2">${typeBadge}</span>
                            ${isLatest ? '<span class="badge bg-primary">Latest</span>' : ''}
                        </div>
                        <small class="text-muted">${release.date}</small>
                    </div>
                    <div class="card-body">
                        <h6 class="card-title mb-3">${release.title}</h6>
                        ${changesHtml}
                    </div>
                </div>`;
        }).join('');

    } catch (e) {
        document.getElementById('changelog-content').innerHTML =
            `<div class="alert alert-warning"><i class="bi bi-exclamation-triangle me-2"></i>Could not load changelog: ${e.message}</div>`;
    }
}

export function destroy() {}
