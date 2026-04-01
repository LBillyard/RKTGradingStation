/**
 * Operator Login page module.
 *
 * Pixel-perfect match of the rktgrading.com login screen.
 * Password-based authentication for operators, stores JWT in localStorage.
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
        <div class="rkt-login-wrapper">
            <div class="rkt-login-card">
                <!-- Logo -->
                <div class="rkt-login-header">
                    <a href="#/login" class="rkt-login-logo"><span class="rkt-logo-text">RKT</span><span class="rkt-dot">.</span></a>
                    <p class="rkt-login-subtitle">Sign in to your account</p>
                </div>

                <!-- Error message -->
                <div id="login-error" class="rkt-login-error" style="display:none;"></div>

                <!-- Login Form -->
                <form id="login-form" class="rkt-login-form">
                    <div class="rkt-form-group">
                        <label for="login-name" class="rkt-form-label">Email</label>
                        <input type="text" id="login-name" class="rkt-form-input"
                               placeholder="you@example.com" autocomplete="username">
                    </div>

                    <div class="rkt-form-group">
                        <div class="rkt-label-row">
                            <label for="login-password" class="rkt-form-label">Password</label>
                        </div>
                        <input type="password" id="login-password" class="rkt-form-input"
                               placeholder="Enter your password" autocomplete="current-password">
                    </div>

                    <button type="submit" id="login-submit" class="rkt-login-btn">
                        Sign In
                    </button>
                </form>

                <!-- Logged In State -->
                <div id="login-status" style="display:none;">
                    <div style="text-align:center;">
                        <div class="rkt-login-avatar">
                            <svg width="32" height="32" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                                <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
                                <circle cx="12" cy="7" r="4"/>
                            </svg>
                        </div>
                        <h6 class="rkt-login-opname" id="login-operator-name"></h6>
                        <span class="rkt-login-badge" id="login-operator-role"></span>
                    </div>
                    <div class="rkt-login-divider"></div>
                    <button id="login-dashboard-btn" class="rkt-login-btn" style="margin-bottom:0.75rem;">
                        Go to Dashboard
                    </button>
                    <button id="login-logout" class="rkt-logout-btn">
                        Sign Out
                    </button>
                </div>
            </div>
        </div>

        <style>
            .rkt-login-wrapper {
                min-height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 1rem;
                background: #f6f7f9;
            }

            .rkt-login-card {
                width: 100%;
                max-width: 420px;
                background: #fff;
                border: 1px solid #e3e7ee;
                border-radius: 14px;
                padding: 32px;
                box-shadow: rgba(11,18,32,0.04) 0px 1px 3px 0px, rgba(11,18,32,0.02) 0px 1px 2px 0px;
            }

            .rkt-login-header {
                text-align: center;
                margin-bottom: 2rem;
            }

            .rkt-login-logo {
                font-size: 2rem;
                font-weight: 700;
                letter-spacing: -0.5px;
                text-decoration: none;
            }

            .rkt-logo-text {
                color: #0b1f3a;
            }

            .rkt-dot {
                color: #c9a227;
            }

            .rkt-login-subtitle {
                color: #3a4250;
                margin-top: 0.5rem;
                font-size: 0.9rem;
            }

            .rkt-login-error {
                margin-bottom: 1.5rem;
                padding: 0.75rem;
                border-radius: 8px;
                background: rgba(239,68,68,0.08);
                border: 1px solid rgba(239,68,68,0.15);
                color: #dc2626;
                font-size: 0.875rem;
                text-align: center;
            }

            .rkt-login-form {
                display: flex;
                flex-direction: column;
                gap: 1rem;
            }

            .rkt-form-group {
                display: flex;
                flex-direction: column;
            }

            .rkt-label-row {
                display: flex;
                align-items: center;
                justify-content: space-between;
                margin-bottom: 6px;
            }

            .rkt-form-label {
                font-size: 14px;
                font-weight: 500;
                color: #3a4250;
                margin-bottom: 6px;
            }

            .rkt-label-row .rkt-form-label {
                margin-bottom: 0;
            }

            .rkt-form-input {
                width: 100%;
                background: #fff;
                border: 1px solid #e3e7ee;
                border-radius: 8px;
                padding: 12px 16px;
                font-size: 16px;
                color: #0b1f3a;
                outline: none;
                transition: border-color 0.2s, box-shadow 0.2s;
                font-family: inherit;
            }

            .rkt-form-input::placeholder {
                color: #9ca3af;
            }

            .rkt-form-input:focus {
                border-color: #0b1f3a;
                box-shadow: 0 0 0 2px rgba(11,31,58,0.1);
            }

            .rkt-login-btn {
                width: 100%;
                padding: 12px 28px;
                background: #0b1f3a;
                color: #fff;
                border: none;
                border-radius: 12px;
                font-size: 16px;
                font-weight: 500;
                cursor: pointer;
                transition: background 0.2s, opacity 0.2s;
                margin-top: 0.5rem;
                font-family: inherit;
            }

            .rkt-login-btn:hover {
                background: #162d4d;
            }

            .rkt-login-btn:disabled {
                opacity: 0.6;
                cursor: not-allowed;
            }

            .rkt-logout-btn {
                width: 100%;
                padding: 12px 28px;
                background: transparent;
                color: #3a4250;
                border: 1px solid #e3e7ee;
                border-radius: 12px;
                font-size: 16px;
                font-weight: 500;
                cursor: pointer;
                transition: all 0.2s;
                font-family: inherit;
            }

            .rkt-logout-btn:hover {
                color: #dc2626;
                border-color: #dc2626;
                background: rgba(220,38,38,0.04);
            }

            .rkt-login-avatar {
                width: 56px;
                height: 56px;
                border-radius: 50%;
                background: rgba(11,31,58,0.06);
                color: #0b1f3a;
                display: flex;
                align-items: center;
                justify-content: center;
                margin: 0 auto 0.75rem;
            }

            .rkt-login-opname {
                font-size: 1.1rem;
                font-weight: 600;
                color: #0b1f3a;
                margin: 0 0 0.25rem;
            }

            .rkt-login-badge {
                display: inline-block;
                padding: 0.2rem 0.75rem;
                font-size: 0.75rem;
                font-weight: 600;
                text-transform: uppercase;
                letter-spacing: 0.5px;
                border-radius: 20px;
                background: rgba(11,31,58,0.08);
                color: #0b1f3a;
            }

            .rkt-login-divider {
                height: 1px;
                background: #e3e7ee;
                margin: 1.5rem 0;
            }
        </style>
    `;
}

function attachListeners(container) {
    const form = container.querySelector('#login-form');
    form?.addEventListener('submit', (e) => {
        e.preventDefault();
        doLogin();
    });
    container.querySelector('#login-logout')?.addEventListener('click', doLogout);
    container.querySelector('#login-dashboard-btn')?.addEventListener('click', () => {
        window.location.hash = '#/dashboard';
    });
}

async function doLogin() {
    const name = document.getElementById('login-name')?.value?.trim();
    const password = document.getElementById('login-password')?.value?.trim();
    const submitBtn = document.getElementById('login-submit');

    if (!name || !password) {
        showError('Enter both email and password');
        return;
    }

    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = 'Signing in...';
    }

    try {
        const result = await api.post('/auth/login', { name, password });
        localStorage.setItem('rkt-auth-token', result.token);
        localStorage.setItem('rkt-operator', JSON.stringify({
            id: result.operator.id,
            name: result.operator.name,
            role: result.operator.role,
        }));
        hideError();
        showLoggedInState(result.operator);
        window.location.hash = '#/dashboard';
    } catch (err) {
        showError('Invalid email or password. Please try again.');
    } finally {
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.textContent = 'Sign In';
        }
    }
}

function showError(msg) {
    const el = document.getElementById('login-error');
    if (el) {
        el.textContent = msg;
        el.style.display = '';
    }
}

function hideError() {
    const el = document.getElementById('login-error');
    if (el) el.style.display = 'none';
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
    showLoginForm();
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
