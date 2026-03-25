/**
 * Agent Changelog — detailed release history for the RKT Station Agent.
 * Design inspired by panel-style changelog with collapsible category groups.
 */
import { api } from '../api.js';
import { escapeHtml } from '../components.js';

const CATEGORIES = {
    feature:     { label: 'Features',      color: '#22c55e', bg: 'rgba(34,197,94,0.1)' },
    improvement: { label: 'Improvements',  color: '#3b82f6', bg: 'rgba(59,130,246,0.1)' },
    fix:         { label: 'Bug Fixes',     color: '#ef4444', bg: 'rgba(239,68,68,0.1)' },
    security:    { label: 'Security',      color: '#f59e0b', bg: 'rgba(245,158,11,0.1)' },
    architecture:{ label: 'Architecture',  color: '#8b5cf6', bg: 'rgba(139,92,246,0.1)' },
    ui:          { label: 'UI',            color: '#06b6d4', bg: 'rgba(6,182,212,0.1)' },
    deprecated:  { label: 'Deprecated',    color: '#6b7280', bg: 'rgba(107,114,128,0.1)' },
    removed:     { label: 'Removed',       color: '#374151', bg: 'rgba(55,65,81,0.1)' },
};

export async function init(container) {
    container.innerHTML = `
        <div class="px-4 py-3">
            <div class="d-flex justify-content-between align-items-center mb-2">
                <div>
                    <h5 class="mb-1"><i class="bi bi-journal-text me-2"></i>Station Agent Changelog</h5>
                    <small class="text-muted">Version history and detailed change log.</small>
                </div>
                <div class="d-flex align-items-center gap-2">
                    <span class="badge bg-primary" id="cl-current-version">v0.0.0</span>
                    <a href="/api/agent/download" class="btn btn-sm btn-primary">
                        <i class="bi bi-download me-1"></i>Download Latest
                    </a>
                </div>
            </div>
            <div class="card mt-3">
                <div class="card-body" id="changelog-content">
                    <div class="text-center py-4">
                        <div class="spinner-border spinner-border-sm text-primary" role="status"></div>
                    </div>
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

        // Set current version badge
        document.getElementById('cl-current-version').textContent = 'v' + changelog[0].version;

        content.innerHTML = changelog.map((release, idx) => {
            // Group changes by category
            const groups = {};
            for (const change of release.changes) {
                const cat = change.category || 'feature';
                if (!groups[cat]) groups[cat] = [];
                groups[cat].push(change.description);
            }

            const groupsHtml = Object.entries(groups).map(([cat, items]) => {
                const info = CATEGORIES[cat] || CATEGORIES.feature;
                const groupId = `cl-${release.version.replace(/\./g, '')}-${cat}`;
                return `
                    <div class="cl-group mb-2">
                        <div class="cl-group-header" data-bs-toggle="collapse" data-bs-target="#${groupId}" role="button" aria-expanded="false">
                            <i class="bi bi-chevron-right cl-chevron me-1"></i>
                            <span class="cl-cat-badge" style="background:${info.bg};color:${info.color};">${info.label}</span>
                            <span class="cl-cat-label">${info.label}</span>
                            <span class="text-muted ms-1">(${items.length} ${items.length === 1 ? 'change' : 'changes'})</span>
                        </div>
                        <div class="collapse" id="${groupId}">
                            <ul class="cl-change-list">
                                ${items.map(desc => `<li>${escapeHtml(desc)}</li>`).join('')}
                            </ul>
                        </div>
                    </div>`;
            }).join('');

            return `
                <div class="cl-release ${idx < changelog.length - 1 ? 'cl-release-border' : ''}">
                    <div class="d-flex align-items-center gap-2 mb-2">
                        <span class="cl-version-badge">v${escapeHtml(release.version)}</span>
                        <span class="text-muted small">${escapeHtml(release.date)}</span>
                        <span class="fw-medium">${escapeHtml(release.title)}</span>
                        ${idx === 0 ? '<span class="badge bg-primary ms-auto" style="font-size:0.65rem;">LATEST</span>' : ''}
                    </div>
                    ${groupsHtml}
                </div>`;
        }).join('');

        // Wire up chevron rotation on collapse toggle
        content.querySelectorAll('.cl-group-header').forEach(header => {
            const target = document.querySelector(header.dataset.bsTarget);
            if (target) {
                target.addEventListener('show.bs.collapse', () => header.classList.add('open'));
                target.addEventListener('hide.bs.collapse', () => header.classList.remove('open'));
            }
        });

    } catch (e) {
        document.getElementById('changelog-content').innerHTML =
            `<div class="alert alert-warning"><i class="bi bi-exclamation-triangle me-2"></i>Could not load changelog: ${escapeHtml(e.message)}</div>`;
    }
}

export function destroy() {}
