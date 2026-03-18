/**
 * RKT Grading Station API Client
 *
 * Centralised HTTP helper that every page module imports.
 * Supports JSON requests, file uploads, and typed error handling.
 */

class ApiClient {
    constructor(baseUrl = '/api') {
        this.baseUrl = baseUrl;
    }

    /**
     * Generic fetch wrapper with JSON handling and error normalisation.
     */
    async request(method, path, data = null, options = {}) {
        const url = `${this.baseUrl}${path}`;
        const config = {
            method,
            headers: { 'Content-Type': 'application/json' },
            ...options,
        };

        // Attach auth token if available
        const token = localStorage.getItem('rkt-auth-token');
        if (token) {
            config.headers['Authorization'] = `Bearer ${token}`;
        }

        if (data && method !== 'GET') {
            config.body = JSON.stringify(data);
        }

        const response = await fetch(url, config);
        if (!response.ok) {
            // On 401, clear stale token and redirect to login
            if (response.status === 401 && !path.startsWith('/auth/')) {
                localStorage.removeItem('rkt-auth-token');
                localStorage.removeItem('rkt-operator');
                if (window.location.hash !== '#/login') {
                    window.location.hash = '#/login';
                }
            }
            let detail = `HTTP ${response.status}`;
            try {
                const err = await response.json();
                detail = err.detail || err.message || detail;
            } catch { /* response body was not JSON */ }
            throw new ApiError(response.status, detail);
        }

        // Some endpoints return 204 No Content
        if (response.status === 204) return null;
        return response.json();
    }

    // Convenience methods
    get(path)        { return this.request('GET', path); }
    post(path, data) { return this.request('POST', path, data); }
    put(path, data)  { return this.request('PUT', path, data); }
    patch(path, data){ return this.request('PATCH', path, data); }
    delete(path)     { return this.request('DELETE', path); }

    /**
     * Upload a file via multipart/form-data.
     * Extra query-string parameters can be passed through `params`.
     */
    async uploadFile(path, file, params = {}) {
        const formData = new FormData();
        formData.append('file', file);

        const queryStr = new URLSearchParams(params).toString();
        const url = `${this.baseUrl}${path}${queryStr ? '?' + queryStr : ''}`;

        const headers = {};
        const token = localStorage.getItem('rkt-auth-token');
        if (token) headers['Authorization'] = `Bearer ${token}`;

        const response = await fetch(url, {
            method: 'POST',
            body: formData,
            headers,
            // Do NOT set Content-Type; the browser sets the correct multipart boundary
        });

        if (!response.ok) {
            let detail = `HTTP ${response.status}`;
            try {
                const err = await response.json();
                detail = err.detail || detail;
            } catch { /* not JSON */ }
            throw new ApiError(response.status, detail);
        }
        return response.json();
    }
}

/**
 * Typed API error with HTTP status code.
 */
class ApiError extends Error {
    constructor(status, message) {
        super(message);
        this.status = status;
        this.name = 'ApiError';
    }
}

/**
 * Agent client for communicating with the local hardware agent.
 *
 * In cloud mode, the browser talks to a local agent on localhost:8742
 * for hardware operations (scan, print, NFC). In desktop mode, hardware
 * calls go to the same server via the main api client.
 */
class AgentClient {
    constructor(baseUrl = 'http://localhost:8742/agent') {
        this.baseUrl = baseUrl;
        this.connected = false;
        this._ws = null;
        this._statusCallbacks = [];
    }

    /**
     * Check if the local agent is reachable.
     */
    async checkConnection() {
        try {
            const resp = await fetch(`${this.baseUrl}/status`, {
                method: 'GET',
                signal: AbortSignal.timeout(2000),
            });
            if (resp.ok) {
                const data = await resp.json();
                this.connected = true;
                this._notifyStatus(data);
                return data;
            }
        } catch { /* agent not running */ }
        this.connected = false;
        this._notifyStatus(null);
        return null;
    }

    /**
     * Register a callback for agent status changes.
     */
    onStatus(callback) {
        this._statusCallbacks.push(callback);
    }

    _notifyStatus(data) {
        for (const cb of this._statusCallbacks) {
            try { cb(this.connected, data); } catch { /* ignore */ }
        }
    }

    /**
     * Make a request to the agent.
     */
    async request(method, path, data = null) {
        const url = `${this.baseUrl}${path}`;
        const config = { method, headers: {} };
        if (data) {
            config.headers['Content-Type'] = 'application/json';
            config.body = JSON.stringify(data);
        }
        const resp = await fetch(url, config);
        if (!resp.ok) {
            let detail = `Agent HTTP ${resp.status}`;
            try {
                const err = await resp.json();
                detail = err.detail || detail;
            } catch { /* not JSON */ }
            throw new ApiError(resp.status, detail);
        }
        return resp.json();
    }

    // Hardware operations
    async scan(dpi = 600)   { return this.request('POST', '/scan', { dpi }); }
    async print(imageUrl, printerName = null) {
        return this.request('POST', '/print', { image_url: imageUrl, printer_name: printerName });
    }
    async programNfc(payload) { return this.request('POST', '/nfc/program', payload); }
    async listScanDevices()   { return this.request('GET', '/scan/devices'); }
    async listPrinters()      { return this.request('GET', '/printers'); }
    async listNfcReaders()    { return this.request('GET', '/nfc/readers'); }
    async detectNfcTag()      { return this.request('GET', '/nfc/detect'); }
}

/**
 * Detect whether we're running in cloud mode (served from a remote host)
 * or desktop mode (localhost). In desktop mode, hardware calls go through
 * the main api client; in cloud mode, they go through the agent client.
 */
const isCloudMode = !['localhost', '127.0.0.1'].includes(window.location.hostname);

// Singleton instances
export const api = new ApiClient();
export const agent = new AgentClient();
export { ApiError, isCloudMode };
