/**
 * Admin page module.
 *
 * User management panel for administrators. Allows creating, editing,
 * and toggling active status of operators.
 */
import { api } from '../api.js';
import { showToast } from '../components.js';

let _container = null;
let _modal = null;
let _editingId = null;

export async function init(container) {
    _container = container;

    // Check admin access
    const operator = getCurrentOperator();
    if (!operator || operator.role !== 'admin') {
        container.innerHTML = `
            <div class="text-center py-5">
                <i class="bi bi-shield-exclamation fs-1 text-danger d-block mb-3"></i>
                <h5 class="text-muted">Access denied — admin only</h5>
                <a href="#/dashboard" class="btn btn-primary mt-3">Go to Dashboard</a>
            </div>`;
        return;
    }

    container.innerHTML = buildLayout();
    _modal = new bootstrap.Modal(document.getElementById('user-modal'));
    attachListeners();
    await loadUsers();
}

export function destroy() {
    if (_modal) {
        try { _modal.hide(); } catch { /* ignore */ }
        _modal = null;
    }
    _container = null;
    _editingId = null;
}

// ------------------------------------------------------------------
// Helpers
// ------------------------------------------------------------------

function getCurrentOperator() {
    try {
        return JSON.parse(localStorage.getItem('rkt-operator'));
    } catch {
        return null;
    }
}

// ------------------------------------------------------------------
// Layout
// ------------------------------------------------------------------

function buildLayout() {
    return `
        <div class="container-fluid py-4">
            <div class="card">
                <div class="card-header d-flex justify-content-between align-items-center">
                    <h5 class="mb-0"><i class="bi bi-people-fill me-2"></i>User Management</h5>
                    <button class="btn btn-primary btn-sm" id="admin-add-user">
                        <i class="bi bi-plus-lg me-1"></i>Add User
                    </button>
                </div>
                <div class="card-body p-0">
                    <div class="table-responsive">
                        <table class="table table-hover align-middle mb-0">
                            <thead>
                                <tr>
                                    <th>Name</th>
                                    <th>Role</th>
                                    <th>Status</th>
                                    <th>Created</th>
                                    <th class="text-end">Actions</th>
                                </tr>
                            </thead>
                            <tbody id="admin-users-tbody">
                                <tr>
                                    <td colspan="5" class="text-center py-4">
                                        <div class="spinner-border spinner-border-sm text-primary" role="status"></div>
                                        <span class="ms-2 text-muted">Loading users...</span>
                                    </td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>

        <!-- User Modal -->
        <div class="modal fade" id="user-modal" tabindex="-1" aria-labelledby="user-modal-label" aria-hidden="true">
            <div class="modal-dialog">
                <div class="modal-content">
                    <div class="modal-header">
                        <h6 class="modal-title" id="user-modal-label">Add User</h6>
                        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                    </div>
                    <div class="modal-body">
                        <div class="mb-3">
                            <label for="user-name" class="form-label">Username</label>
                            <input type="text" id="user-name" class="form-control" required placeholder="Enter username">
                        </div>
                        <div class="mb-3">
                            <label for="user-password" class="form-label">Password</label>
                            <input type="password" id="user-password" class="form-control" minlength="6" placeholder="Minimum 6 characters">
                        </div>
                        <div class="mb-3">
                            <label for="user-role" class="form-label">Role</label>
                            <select id="user-role" class="form-select">
                                <option value="operator">Operator</option>
                                <option value="admin">Admin</option>
                            </select>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                        <button type="button" class="btn btn-primary" id="user-save">Save</button>
                    </div>
                </div>
            </div>
        </div>
    `;
}

// ------------------------------------------------------------------
// Event listeners
// ------------------------------------------------------------------

function attachListeners() {
    document.getElementById('admin-add-user')?.addEventListener('click', openAddModal);
    document.getElementById('user-save')?.addEventListener('click', saveUser);

    // Delegate click events on the table body
    document.getElementById('admin-users-tbody')?.addEventListener('click', (e) => {
        const editBtn = e.target.closest('[data-action="edit"]');
        const toggleBtn = e.target.closest('[data-action="toggle"]');

        if (editBtn) {
            const id = editBtn.dataset.id;
            const name = editBtn.dataset.name;
            const role = editBtn.dataset.role;
            openEditModal(id, name, role);
        }

        if (toggleBtn) {
            const id = toggleBtn.dataset.id;
            const active = toggleBtn.dataset.active === 'true';
            toggleActive(id, active);
        }
    });
}

// ------------------------------------------------------------------
// Modal operations
// ------------------------------------------------------------------

function openAddModal() {
    _editingId = null;
    document.getElementById('user-modal-label').textContent = 'Add User';
    document.getElementById('user-name').value = '';
    document.getElementById('user-password').value = '';
    document.getElementById('user-password').setAttribute('placeholder', 'Minimum 6 characters');
    document.getElementById('user-role').value = 'operator';
    _modal.show();
}

function openEditModal(id, name, role) {
    _editingId = id;
    document.getElementById('user-modal-label').textContent = 'Edit User';
    document.getElementById('user-name').value = name;
    document.getElementById('user-password').value = '';
    document.getElementById('user-password').setAttribute('placeholder', 'Leave blank to keep current');
    document.getElementById('user-role').value = role;
    _modal.show();
}

async function saveUser() {
    const name = document.getElementById('user-name')?.value?.trim();
    const password = document.getElementById('user-password')?.value;
    const role = document.getElementById('user-role')?.value;

    if (!name) {
        showToast('Username is required', 'warning');
        return;
    }

    if (!_editingId && (!password || password.length < 6)) {
        showToast('Password must be at least 6 characters', 'warning');
        return;
    }

    if (_editingId && password && password.length < 6) {
        showToast('Password must be at least 6 characters', 'warning');
        return;
    }

    const payload = { name, role };
    if (password) payload.password = password;

    try {
        if (_editingId) {
            await api.put(`/auth/operators/${_editingId}`, payload);
            showToast('User updated successfully', 'success');
        } else {
            payload.password = password;
            await api.post('/auth/operators', payload);
            showToast('User created successfully', 'success');
        }
        _modal.hide();
        await loadUsers();
    } catch (err) {
        showToast(`Failed to save user: ${err.message}`, 'error');
    }
}

// ------------------------------------------------------------------
// Toggle active
// ------------------------------------------------------------------

async function toggleActive(id, currentActive) {
    try {
        await api.put(`/auth/operators/${id}`, { is_active: !currentActive });
        showToast(`User ${currentActive ? 'deactivated' : 'activated'}`, 'success');
        await loadUsers();
    } catch (err) {
        showToast(`Failed to update user: ${err.message}`, 'error');
    }
}

// ------------------------------------------------------------------
// Load and render users
// ------------------------------------------------------------------

async function loadUsers() {
    const tbody = document.getElementById('admin-users-tbody');
    if (!tbody) return;

    try {
        const users = await api.get('/auth/operators');
        const list = Array.isArray(users) ? users : (users.operators || users.items || []);

        if (list.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="5" class="text-center py-4 text-muted">No users found</td>
                </tr>`;
            return;
        }

        tbody.innerHTML = list.map(u => {
            const roleBadge = u.role === 'admin'
                ? '<span class="badge bg-primary">admin</span>'
                : '<span class="badge bg-secondary">operator</span>';

            const isActive = u.is_active !== false;
            const statusBadge = isActive
                ? '<span class="badge bg-success">Active</span>'
                : '<span class="badge bg-danger">Inactive</span>';

            const created = u.created_at
                ? new Date(u.created_at).toLocaleDateString()
                : '-';

            return `
                <tr>
                    <td>${escapeHtml(u.name)}</td>
                    <td>${roleBadge}</td>
                    <td>${statusBadge}</td>
                    <td><small class="text-muted">${created}</small></td>
                    <td class="text-end">
                        <button class="btn btn-sm btn-outline-secondary me-1"
                                data-action="edit" data-id="${u.id}" data-name="${escapeAttr(u.name)}" data-role="${u.role}"
                                title="Edit user">
                            <i class="bi bi-pencil"></i>
                        </button>
                        <button class="btn btn-sm ${isActive ? 'btn-outline-warning' : 'btn-outline-success'}"
                                data-action="toggle" data-id="${u.id}" data-active="${isActive}"
                                title="${isActive ? 'Deactivate' : 'Activate'} user">
                            <i class="bi ${isActive ? 'bi-person-dash' : 'bi-person-check'}"></i>
                        </button>
                    </td>
                </tr>`;
        }).join('');
    } catch (err) {
        tbody.innerHTML = `
            <tr>
                <td colspan="5" class="text-center py-4 text-danger">
                    <i class="bi bi-exclamation-triangle me-2"></i>Failed to load users: ${escapeHtml(err.message)}
                </td>
            </tr>`;
    }
}

// ------------------------------------------------------------------
// Utility
// ------------------------------------------------------------------

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str || '';
    return div.innerHTML;
}

function escapeAttr(str) {
    return (str || '').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
