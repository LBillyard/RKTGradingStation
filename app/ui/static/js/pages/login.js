/**
 * Operator Login page module.
 *
 * SSO-only authentication — users must sign in via the RKT admin panel.
 * The login form is replaced with a redirect message.
 * SSO tokens arrive via URL param and are handled in app.js.
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
                    <p class="rkt-login-subtitle">Grading Station</p>
                </div>

                <!-- Not logged in state -->
                <div id="login-prompt">
                    <div class="rkt-login-icon">
                        <svg width="40" height="40" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24">
                            <path d="M15.75 5.25a3 3 0 0 1 3 3m3 0a6 6 0 0 1-7.029 5.912c-.563-.097-1.159.026-1.563.43L10.5 17.25H8.25v2.25H6v2.25H2.25v-2.818c0-.597.237-1.17.659-1.591l6.499-6.499c.404-.404.527-1 .43-1.563A6 6 0 1 1 21.75 8.25z"/>
                        </svg>
                    </div>
                    <p class="rkt-login-message">
                        Sign in through the RKT admin panel to access the Grading Station.
                    </p>
                    <a href="https://rktgrading.com/admin" class="rkt-login-btn" target="_blank" rel="noopener noreferrer">
                        Go to Admin Panel
                    </a>
                    <p class="rkt-login-hint">
                        Click <strong>Grading Station</strong> in the admin sidebar to sign in automatically.
                    </p>
                </div>

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
                margin-bottom: 1.5rem;
            }

            .rkt-login-logo {
                font-size: 2rem;
                font-weight: 700;
                letter-spacing: -0.5px;
                text-decoration: none;
            }

            .rkt-logo-text { color: #0b1f3a; }
            .rkt-dot { color: #c9a227; }

            .rkt-login-subtitle {
                color: #3a4250;
                margin-top: 0.35rem;
                font-size: 0.9rem;
            }

            .rkt-login-icon {
                width: 64px;
                height: 64px;
                border-radius: 50%;
                background: rgba(11,31,58,0.05);
                color: #0b1f3a;
                display: flex;
                align-items: center;
                justify-content: center;
                margin: 0 auto 1.25rem;
            }

            .rkt-login-message {
                text-align: center;
                color: #3a4250;
                font-size: 0.95rem;
                line-height: 1.5;
                margin-bottom: 1.5rem;
            }

            .rkt-login-btn {
                display: block;
                width: 100%;
                padding: 12px 28px;
                background: #0b1f3a;
                color: #fff;
                border: none;
                border-radius: 12px;
                font-size: 16px;
                font-weight: 500;
                cursor: pointer;
                transition: background 0.2s;
                font-family: inherit;
                text-align: center;
                text-decoration: none;
            }

            .rkt-login-btn:hover {
                background: #162d4d;
                color: #fff;
            }

            .rkt-login-hint {
                text-align: center;
                color: #6b7280;
                font-size: 0.8rem;
                margin-top: 1.25rem;
                line-height: 1.5;
            }

            .rkt-login-hint strong {
                color: #3a4250;
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
    container.querySelector('#login-logout')?.addEventListener('click', doLogout);
    container.querySelector('#login-dashboard-btn')?.addEventListener('click', () => {
        window.location.hash = '#/dashboard';
    });
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
    showLoginPrompt();
}

function checkExistingSession() {
    const operator = localStorage.getItem('rkt-operator');
    if (operator) {
        try {
            showLoggedInState(JSON.parse(operator));
        } catch {
            showLoginPrompt();
        }
    }
}

function showLoggedInState(operator) {
    const prompt = document.getElementById('login-prompt');
    const status = document.getElementById('login-status');
    if (prompt) prompt.style.display = 'none';
    if (status) {
        status.style.display = '';
        const nameEl = document.getElementById('login-operator-name');
        const roleEl = document.getElementById('login-operator-role');
        if (nameEl) nameEl.textContent = operator.name;
        if (roleEl) roleEl.textContent = operator.role;
    }
}

function showLoginPrompt() {
    const prompt = document.getElementById('login-prompt');
    const status = document.getElementById('login-status');
    if (prompt) prompt.style.display = '';
    if (status) status.style.display = 'none';
}
