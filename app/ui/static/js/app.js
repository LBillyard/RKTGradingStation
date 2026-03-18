/**
 * RKT Grading Station - Main Application Controller
 *
 * Hash-based SPA router that lazy-loads page modules and manages sidebar
 * active state.  Every page module must export an `init(container)` function
 * and may optionally export a `destroy()` for cleanup.
 */
import { api, agent, isCloudMode } from './api.js';
import { showToast } from './components.js';

// ---------------------------------------------------------------- Routes
const routes = {
    '/dashboard':            { module: './pages/dashboard.js',            title: 'Dashboard',            icon: 'bi-speedometer2' },
    '/scan':                 { module: './pages/new-scan.js',             title: 'New Scan',             icon: 'bi-camera' },
    '/queue':                { module: './pages/queue.js',                title: 'Graded Cards',         icon: 'bi-collection' },
    '/grade-review':         { module: './pages/grade-review.js',         title: 'Grade Review',         icon: 'bi-clipboard-check' },
    '/authenticity-review':  { module: './pages/authenticity-review.js',  title: 'Authenticity Review',  icon: 'bi-shield-check' },
    '/security-templates':   { module: './pages/security-templates.js',   title: 'Security Templates',   icon: 'bi-lock' },
    '/reference-library':    { module: './pages/reference-library.js',    title: 'Reference Library',    icon: 'bi-book' },
    '/reports':              { module: './pages/reports.js',              title: 'Reports',              icon: 'bi-graph-up' },
    '/settings':             { module: './pages/settings.js',             title: 'Settings',             icon: 'bi-gear' },
    '/audit-log':            { module: './pages/audit-log.js',            title: 'Audit Log',            icon: 'bi-journal-text' },
    '/login':                { module: './pages/login.js',                title: 'Operator Login',       icon: 'bi-person-lock' },
    '/admin':                { module: './pages/admin.js',               title: 'Admin',                icon: 'bi-people-fill' },
    '/slab-assembly':        { module: './pages/slab-assembly.js',       title: 'Slab Assembly',        icon: 'bi-box-seam' },
    '/training':             { module: './pages/training.js',           title: 'Training Mode',        icon: 'bi-mortarboard' },
    '/calibration':          { module: './pages/calibration.js',       title: 'Calibration',          icon: 'bi-sliders' },
    '/agent-changelog':      { module: './pages/agent-changelog.js',    title: 'Agent Changelog',      icon: 'bi-journal-text' },
};

let currentModule = null;

// ---------------------------------------------------------------- App Shell
function setAppShellVisible(visible) {
    const navbar = document.getElementById('app-navbar');
    const sidebar = document.getElementById('sidebarDesktop');
    const content = document.getElementById('app-content');
    if (visible) {
        if (navbar) navbar.style.display = '';
        if (sidebar) { sidebar.classList.remove('d-none'); sidebar.classList.add('d-lg-flex'); }
        if (content) content.classList.add('main-content');
    } else {
        if (navbar) navbar.style.display = 'none';
        if (sidebar) { sidebar.classList.add('d-none'); sidebar.classList.remove('d-lg-flex'); }
        if (content) content.classList.remove('main-content');
    }
}

// ---------------------------------------------------------------- Router
class AppRouter {
    constructor() {
        window.addEventListener('hashchange', () => this.handleRoute());

        // Always start at login if no token, dashboard if token exists
        const token = localStorage.getItem('rkt-auth-token');
        if (!token) {
            window.location.hash = '#/login';
        } else if (!window.location.hash) {
            window.location.hash = '#/dashboard';
        } else {
            this.handleRoute();
        }
    }

    async handleRoute() {
        const hash  = window.location.hash.slice(1) || '/login';
        const route = routes[hash];

        if (!route) {
            document.getElementById('app-content').innerHTML = `
                <div class="text-center py-5">
                    <i class="bi bi-question-circle fs-1 text-muted d-block mb-3"></i>
                    <h5 class="text-muted">Page not found</h5>
                    <a href="#/dashboard" class="btn btn-primary mt-3">Go to Dashboard</a>
                </div>`;
            return;
        }

        // Redirect to login if not authenticated (except for the login page itself)
        const token = localStorage.getItem('rkt-auth-token');
        if (!token && hash !== '/login') {
            window.location.hash = '#/login';
            return;
        }

        // Show/hide app shell based on whether this is the login page
        const isLoginPage = (hash === '/login' && !token);
        setAppShellVisible(!isLoginPage);

        // ---- Teardown previous module ---------------------------------
        if (currentModule?.destroy) {
            try { currentModule.destroy(); } catch (e) { console.warn('Module destroy error:', e); }
        }

        // ---- Update sidebar active state (desktop + mobile) -----------
        document.querySelectorAll('.sidebar-nav .nav-link').forEach(link => {
            link.classList.toggle('active', link.getAttribute('href') === '#' + hash);
        });

        // ---- Update top-bar title -------------------------------------
        const titleEl = document.getElementById('page-title');
        if (titleEl) titleEl.textContent = route.title;

        // ---- Loading indicator ----------------------------------------
        const content = document.getElementById('app-content');
        content.innerHTML = `
            <div class="text-center py-5">
                <div class="spinner-border text-primary" role="status"></div>
            </div>`;

        // ---- Lazy-load the page module --------------------------------
        try {
            const mod = await import(route.module);
            currentModule = mod;
            content.innerHTML = '';
            if (mod.init) {
                await mod.init(content);
            }
        } catch (err) {
            console.error('Failed to load page module:', err);
            content.innerHTML = `
                <div class="alert alert-danger m-4">
                    <i class="bi bi-exclamation-triangle me-2"></i>
                    Failed to load page: ${err.message}
                </div>`;
        }
    }
}

// ---------------------------------------------------------------- Theme
function initTheme() {
    const saved = localStorage.getItem('rkt-theme') || 'light';
    document.documentElement.setAttribute('data-theme', saved);
    updateThemeIcon(saved);
}

function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme') || 'light';
    const next = current === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('rkt-theme', next);
    updateThemeIcon(next);
}

function updateThemeIcon(theme) {
    const btn = document.getElementById('theme-toggle');
    if (!btn) return;
    const icon = btn.querySelector('i');
    if (icon) {
        icon.className = theme === 'dark' ? 'bi bi-sun fs-5' : 'bi bi-moon-stars fs-5';
    }
}

// ---------------------------------------------------------------- Keyboard Shortcuts
function initKeyboardShortcuts() {
    document.addEventListener('keydown', (e) => {
        // Ignore when typing in input/textarea/select
        const tag = e.target.tagName;
        if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || e.target.isContentEditable) return;

        // Ctrl+Shift+T — toggle theme
        if (e.ctrlKey && e.shiftKey && e.key === 'T') {
            e.preventDefault();
            toggleTheme();
            return;
        }

        // ? — show shortcuts help
        if (e.key === '?' && !e.ctrlKey && !e.altKey) {
            e.preventDefault();
            const modal = bootstrap.Modal.getOrCreateInstance(document.getElementById('shortcuts-modal'));
            modal.toggle();
            return;
        }

        // Page-specific shortcuts — emit custom events for page modules to handle
        const shortcutMap = {
            'Enter': 'shortcut:approve',
            'o':     'shortcut:toggle-overlays',
            'O':     'shortcut:toggle-overlays',
            'f':     'shortcut:flip-card',
            'F':     'shortcut:flip-card',
            '+':     'shortcut:zoom-in',
            '=':     'shortcut:zoom-in',
            '-':     'shortcut:zoom-out',
            '0':     'shortcut:zoom-reset',
            'ArrowLeft':  'shortcut:prev-card',
            'ArrowRight': 'shortcut:next-card',
        };

        const eventName = shortcutMap[e.key];
        if (eventName) {
            e.preventDefault();
            window.dispatchEvent(new CustomEvent(eventName));
        }
    });
}

// ---------------------------------------------------------------- Operator Badge
function updateOperatorBadge() {
    const nameEl = document.getElementById('navbar-operator-name');
    if (!nameEl) return;
    try {
        const op = JSON.parse(localStorage.getItem('rkt-operator'));
        if (op?.name) {
            nameEl.textContent = op.name;
            nameEl.classList.remove('text-muted');
            nameEl.classList.add('text-primary');
        } else {
            nameEl.textContent = 'Not logged in';
            nameEl.classList.remove('text-primary');
            nameEl.classList.add('text-muted');
        }
    } catch {
        nameEl.textContent = 'Not logged in';
    }
}

// ---------------------------------------------------------------- Scanner Status
async function updateScannerStatus() {
    const dot = document.getElementById('navbar-scanner-dot');
    const text = document.getElementById('navbar-scanner-text');
    if (!dot || !text) return;
    try {
        const res = await api.get('/scan/devices/list');
        const hasReal = res.real_devices && res.real_devices.length > 0;
        if (res.mock_mode) {
            if (hasReal) {
                dot.className = 'status-indicator status-online';
                text.textContent = 'Mock Mode (Scanner Available)';
            } else {
                dot.className = 'status-indicator status-warning';
                text.textContent = 'Mock Mode (No Scanner)';
            }
        } else {
            if (hasReal) {
                dot.className = 'status-indicator status-online';
                text.textContent = 'Scanner Ready';
            } else {
                dot.className = 'status-indicator status-offline';
                text.textContent = 'No Scanner';
            }
        }
    } catch {
        dot.className = 'status-indicator status-offline';
        text.textContent = 'Scanner Error';
    }
}

// ---------------------------------------------------------------- Agent Status
async function updateAgentStatus() {
    const dot = document.getElementById('navbar-agent-dot');
    const text = document.getElementById('navbar-agent-text');
    if (!dot || !text) return;

    // In desktop mode, agent is built-in — always show connected
    if (!isCloudMode) {
        dot.className = 'status-indicator status-online';
        text.textContent = 'Desktop Mode';
        return;
    }

    const status = await agent.checkConnection();
    if (status) {
        dot.className = 'status-indicator status-online';
        text.textContent = `Station: ${status.station_id || 'Connected'}`;
    } else {
        dot.className = 'status-indicator status-offline';
        text.textContent = 'No Station';
    }
}

// ---------------------------------------------------------------- Boot
document.addEventListener('DOMContentLoaded', () => {
    initTheme();
    initKeyboardShortcuts();

    // Wire up toolbar buttons
    document.getElementById('theme-toggle')?.addEventListener('click', toggleTheme);
    document.getElementById('shortcuts-help-btn')?.addEventListener('click', () => {
        bootstrap.Modal.getOrCreateInstance(document.getElementById('shortcuts-modal')).show();
    });

    // Show operator name in navbar
    updateOperatorBadge();

    // Check agent connection status
    updateAgentStatus();
    setInterval(updateAgentStatus, 10000);

    // Check scanner status on load and poll every 15s
    updateScannerStatus();
    setInterval(updateScannerStatus, 15000);

    // Listen for storage changes (login/logout)
    window.addEventListener('storage', () => updateOperatorBadge());
    // Also poll periodically for same-tab login updates
    setInterval(updateOperatorBadge, 2000);

    window.app = {
        router: new AppRouter(),
        api,
        showToast,
        toggleTheme,
    };
});

export { routes };
