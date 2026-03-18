/**
 * Operator Login page module.
 *
 * Simple password-based authentication for operators.
 * Stores JWT token in localStorage.
 */
import { api } from '../api.js';
import { showToast } from '../components.js';

export async function init(container) {
    container.innerHTML = buildLayout();
    attachListeners(container);
    checkExistingSession();
}

export function destroy() {}

function buildLayout() {
    return `
        <div class="d-flex justify-content-center align-items-center" style="min-height:100vh;">
            <div class="card" style="width:380px;">
                <div class="card-body p-4">
                    <div class="text-center mb-4">
                        <i class="bi bi-gem text-primary" style="font-size:2.5rem;"></i>
                        <h5 class="mt-2 mb-1">RKT Grading Station</h5>
                        <p class="text-muted small">Operator Login</p>
                    </div>

                    <!-- Login Form -->
                    <div id="login-form">
                        <div class="mb-3">
                            <label for="login-name" class="form-label">Operator Name</label>
                            <input type="text" id="login-name" class="form-control" placeholder="Enter your name" autocomplete="username">
                        </div>
                        <div class="mb-3">
                            <label for="login-password" class="form-label">Password</label>
                            <input type="password" id="login-password" class="form-control" placeholder="Enter your password"
                                   autocomplete="current-password">
                        </div>
                        <button id="login-submit" class="btn btn-primary w-100">
                            <i class="bi bi-box-arrow-in-right me-2"></i>Login
                        </button>
                    </div>

                    <!-- Logged In State -->
                    <div id="login-status" style="display:none;">
                        <div class="text-center">
                            <i class="bi bi-person-check text-success" style="font-size:2rem;"></i>
                            <h6 class="mt-2" id="login-operator-name"></h6>
                            <span class="badge bg-primary" id="login-operator-role"></span>
                        </div>
                        <hr>
                        <button id="login-logout" class="btn btn-outline-danger w-100">
                            <i class="bi bi-box-arrow-right me-2"></i>Logout
                        </button>
                    </div>
                </div>
            </div>
        </div>
    `;
}

function attachListeners(container) {
    container.querySelector('#login-submit')?.addEventListener('click', doLogin);
    container.querySelector('#login-password')?.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') doLogin();
    });
    container.querySelector('#login-logout')?.addEventListener('click', doLogout);
}

async function doLogin() {
    const name = document.getElementById('login-name')?.value?.trim();
    const password = document.getElementById('login-password')?.value?.trim();

    if (!name || !password) {
        showToast('Enter both username and password', 'warning');
        return;
    }

    try {
        const result = await api.post('/auth/login', { name, password });
        localStorage.setItem('rkt-auth-token', result.token);
        localStorage.setItem('rkt-operator', JSON.stringify({
            id: result.operator.id,
            name: result.operator.name,
            role: result.operator.role,
        }));
        showToast(`Welcome, ${result.operator.name}!`, 'success');
        showLoggedInState(result.operator);
        window.location.hash = '#/dashboard';
    } catch (err) {
        showToast(`Login failed: ${err.message}`, 'error');
    }
}

async function doLogout() {
    try {
        const token = localStorage.getItem('rkt-auth-token');
        if (token) {
            await api.post('/auth/logout', {}, {
                headers: { 'Authorization': `Bearer ${token}` }
            });
        }
    } catch { /* ignore */ }

    localStorage.removeItem('rkt-auth-token');
    localStorage.removeItem('rkt-operator');
    showToast('Logged out', 'info');
    window.location.hash = '#/login';
}

function checkExistingSession() {
    const operator = localStorage.getItem('rkt-operator');
    if (operator) {
        try {
            showLoggedInState(JSON.parse(operator));
        } catch {
            showLoginForm();
        }
    }
}

function showLoggedInState(operator) {
    const form = document.getElementById('login-form');
    const status = document.getElementById('login-status');
    if (form) form.style.display = 'none';
    if (status) {
        status.style.display = '';
        const nameEl = document.getElementById('login-operator-name');
        const roleEl = document.getElementById('login-operator-role');
        if (nameEl) nameEl.textContent = operator.name;
        if (roleEl) roleEl.textContent = operator.role;
    }
}

function showLoginForm() {
    const form = document.getElementById('login-form');
    const status = document.getElementById('login-status');
    if (form) form.style.display = '';
    if (status) status.style.display = 'none';
}
