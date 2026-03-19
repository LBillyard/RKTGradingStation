/**
 * RKT Grading Station - Canvas-based Image Viewer
 *
 * Provides pan, zoom, and overlay rendering for card images.
 * Used on the grade-review page to display scanned cards with
 * defect bounding boxes drawn on top.
 */

const MIN_ZOOM = 0.1;
const MAX_ZOOM = 10.0;
const ZOOM_STEP = 0.1;

/**
 * Overlay descriptor.
 * @typedef {Object} Overlay
 * @property {number} x - Image-space X coordinate
 * @property {number} y - Image-space Y coordinate
 * @property {number} w - Image-space width
 * @property {number} h - Image-space height
 * @property {string} className - Severity class for colour coding
 * @property {string} label - Text label to render
 * @property {string} [id] - Optional unique ID for click handling
 */

// Severity colour map
const SEVERITY_COLORS = {
    'defect-minor':    { stroke: '#ffc107', fill: 'rgba(255,193,7,0.12)',   text: '#ffc107' },
    'defect-moderate': { stroke: '#fd7e14', fill: 'rgba(253,126,20,0.12)',  text: '#fd7e14' },
    'defect-major':    { stroke: '#dc3545', fill: 'rgba(220,53,69,0.12)',   text: '#dc3545' },
    'defect-severe':   { stroke: '#8b0000', fill: 'rgba(139,0,0,0.15)',     text: '#8b0000' },
};

export class ImageViewer {
    /**
     * Create an image viewer instance.
     * Does NOT attach to the DOM until init() is called.
     */
    constructor() {
        /** @type {HTMLCanvasElement|null} */
        this.canvas = null;
        /** @type {CanvasRenderingContext2D|null} */
        this.ctx = null;
        /** @type {HTMLImageElement|null} */
        this.image = null;
        /** @type {HTMLElement|null} */
        this.container = null;

        // Transform state
        this.zoom = 1.0;
        this.panX = 0;
        this.panY = 0;

        // Interaction state
        this._dragging = false;
        this._dragStartX = 0;
        this._dragStartY = 0;
        this._dragPanStartX = 0;
        this._dragPanStartY = 0;

        /** @type {Overlay[]} */
        this.overlays = [];
        this._overlaysVisible = true;

        // Bound event handlers (for cleanup)
        this._onMouseDown = this._handleMouseDown.bind(this);
        this._onMouseMove = this._handleMouseMove.bind(this);
        this._onMouseUp = this._handleMouseUp.bind(this);
        this._onWheel = this._handleWheel.bind(this);
        this._onResize = this._handleResize.bind(this);

        /** @type {Function|null} */
        this.onOverlayClick = null;
    }

    /**
     * Initialise the viewer inside a container element.
     *
     * @param {string} containerId - DOM id of the container element.
     * @param {string} [imageUrl] - Optional image URL to load immediately.
     * @returns {Promise<void>}
     */
    async init(containerId, imageUrl) {
        this.container = document.getElementById(containerId);
        if (!this.container) {
            throw new Error(`ImageViewer: container #${containerId} not found`);
        }

        // Create canvas
        this.canvas = document.createElement('canvas');
        this.canvas.style.cssText = 'display:block;width:100%;height:100%;cursor:grab;';
        this.container.innerHTML = '';
        this.container.appendChild(this.canvas);
        this.ctx = this.canvas.getContext('2d');

        // Size canvas to container
        this._resizeCanvas();

        // Attach events
        this.canvas.addEventListener('mousedown', this._onMouseDown);
        this.canvas.addEventListener('mousemove', this._onMouseMove);
        this.canvas.addEventListener('mouseup', this._onMouseUp);
        this.canvas.addEventListener('mouseleave', this._onMouseUp);
        this.canvas.addEventListener('wheel', this._onWheel, { passive: false });
        window.addEventListener('resize', this._onResize);

        if (imageUrl) {
            await this.loadImage(imageUrl);
        }
    }

    /**
     * Load and display an image.
     *
     * @param {string} url - Image URL.
     * @returns {Promise<void>}
     */
    loadImage(url) {
        return new Promise((resolve, reject) => {
            const img = new Image();
            img.crossOrigin = 'anonymous';
            img.onload = () => {
                this.image = img;
                this._fitImage();
                this._render();
                resolve();
            };
            img.onerror = () => reject(new Error(`Failed to load image: ${url}`));
            img.src = url;
        });
    }

    /**
     * Add an overlay rectangle (e.g., a defect bounding box).
     *
     * @param {number} x - Image-space X
     * @param {number} y - Image-space Y
     * @param {number} w - Image-space width
     * @param {number} h - Image-space height
     * @param {string} className - Severity class (defect-minor, defect-moderate, etc.)
     * @param {string} label - Text label
     * @param {string} [id] - Optional ID for click handling
     */
    addOverlay(x, y, w, h, className, label, id) {
        this.overlays.push({ x, y, w, h, className, label, id: id || null });
        this._render();
    }

    /**
     * Remove all overlays.
     */
    clearOverlays() {
        this.overlays = [];
        this._render();
    }

    /**
     * Toggle overlay visibility.
     *
     * @param {boolean} [visible] - Force visible state. Toggles if omitted.
     */
    toggleOverlays(visible) {
        this._overlaysVisible = visible !== undefined ? visible : !this._overlaysVisible;
        this._render();
    }

    /**
     * Animate zoom to a specific image region.
     *
     * @param {number} x - Image-space X
     * @param {number} y - Image-space Y
     * @param {number} w - Image-space width
     * @param {number} h - Image-space height
     */
    zoomToRegion(x, y, w, h) {
        if (!this.canvas) return;

        const cw = this.canvas.width;
        const ch = this.canvas.height;
        const padding = 40;

        // Calculate zoom to fit the region with padding
        const zoomX = (cw - padding * 2) / w;
        const zoomY = (ch - padding * 2) / h;
        this.zoom = Math.min(zoomX, zoomY, MAX_ZOOM);

        // Center the region
        const regionCenterX = x + w / 2;
        const regionCenterY = y + h / 2;
        this.panX = cw / 2 - regionCenterX * this.zoom;
        this.panY = ch / 2 - regionCenterY * this.zoom;

        this._render();
    }

    /**
     * Zoom in toward the center of the canvas.
     */
    zoomIn() {
        if (!this.canvas) return;
        const cw = this.canvas.width;
        const ch = this.canvas.height;
        const oldZoom = this.zoom;
        this.zoom = Math.min(MAX_ZOOM, this.zoom * 1.25);
        const ratio = this.zoom / oldZoom;
        this.panX = cw / 2 - (cw / 2 - this.panX) * ratio;
        this.panY = ch / 2 - (ch / 2 - this.panY) * ratio;
        this._render();
    }

    /**
     * Zoom out from the center of the canvas.
     */
    zoomOut() {
        if (!this.canvas) return;
        const cw = this.canvas.width;
        const ch = this.canvas.height;
        const oldZoom = this.zoom;
        this.zoom = Math.max(MIN_ZOOM, this.zoom * 0.8);
        const ratio = this.zoom / oldZoom;
        this.panX = cw / 2 - (cw / 2 - this.panX) * ratio;
        this.panY = ch / 2 - (ch / 2 - this.panY) * ratio;
        this._render();
    }

    /**
     * Get current zoom level as a percentage.
     * @returns {number}
     */
    getZoomPercent() {
        return Math.round(this.zoom * 100);
    }

    /**
     * Reset zoom/pan to fit the full image.
     */
    resetView() {
        this._fitImage();
        this._render();
    }

    /**
     * Destroy the viewer and clean up event listeners.
     */
    destroy() {
        if (this.canvas) {
            this.canvas.removeEventListener('mousedown', this._onMouseDown);
            this.canvas.removeEventListener('mousemove', this._onMouseMove);
            this.canvas.removeEventListener('mouseup', this._onMouseUp);
            this.canvas.removeEventListener('mouseleave', this._onMouseUp);
            this.canvas.removeEventListener('wheel', this._onWheel);
        }
        window.removeEventListener('resize', this._onResize);
        this.canvas = null;
        this.ctx = null;
        this.image = null;
        this.overlays = [];
    }

    // ---- Private methods ----

    _resizeCanvas() {
        if (!this.canvas || !this.container) return;
        const rect = this.container.getBoundingClientRect();
        this.canvas.width = rect.width;
        this.canvas.height = rect.height;
    }

    _fitImage() {
        if (!this.image || !this.canvas) return;

        const cw = this.canvas.width;
        const ch = this.canvas.height;
        const iw = this.image.width;
        const ih = this.image.height;

        // Fit with some padding
        const padding = 20;
        const scaleX = (cw - padding * 2) / iw;
        const scaleY = (ch - padding * 2) / ih;
        this.zoom = Math.min(scaleX, scaleY);

        // Center
        this.panX = (cw - iw * this.zoom) / 2;
        this.panY = (ch - ih * this.zoom) / 2;
    }

    _render() {
        if (!this.ctx || !this.canvas) return;
        const ctx = this.ctx;
        const cw = this.canvas.width;
        const ch = this.canvas.height;

        // Clear
        ctx.clearRect(0, 0, cw, ch);

        // Background
        ctx.fillStyle = '#1a1a2e';
        ctx.fillRect(0, 0, cw, ch);

        // Draw image
        if (this.image) {
            ctx.save();
            ctx.translate(this.panX, this.panY);
            ctx.scale(this.zoom, this.zoom);
            ctx.drawImage(this.image, 0, 0);

            // Draw overlays on top of image in image space
            if (this._overlaysVisible) {
                this._renderOverlays(ctx);
            }
            // Draw centering guide lines
            if (this._centeringLines) {
                this._renderCenteringOverlay(ctx);
            }

            ctx.restore();
        }
    }

    _renderOverlays(ctx) {
        for (const overlay of this.overlays) {
            const colors = SEVERITY_COLORS[overlay.className] || SEVERITY_COLORS['defect-minor'];

            // Fill
            ctx.fillStyle = colors.fill;
            ctx.fillRect(overlay.x, overlay.y, overlay.w, overlay.h);

            // Stroke
            ctx.strokeStyle = colors.stroke;
            ctx.lineWidth = 2 / this.zoom; // keep apparent width constant
            ctx.strokeRect(overlay.x, overlay.y, overlay.w, overlay.h);

            // Label background
            if (overlay.label) {
                const fontSize = Math.max(10, 14 / this.zoom);
                ctx.font = `bold ${fontSize}px sans-serif`;
                const textWidth = ctx.measureText(overlay.label).width;
                const labelH = fontSize + 6 / this.zoom;
                const labelY = overlay.y - labelH;

                ctx.fillStyle = colors.stroke;
                ctx.fillRect(overlay.x, labelY, textWidth + 8 / this.zoom, labelH);

                ctx.fillStyle = '#ffffff';
                ctx.fillText(overlay.label, overlay.x + 4 / this.zoom, overlay.y - 4 / this.zoom);
            }
        }
    }

    _handleMouseDown(e) {
        this._dragging = true;
        this._dragStartX = e.clientX;
        this._dragStartY = e.clientY;
        this._dragPanStartX = this.panX;
        this._dragPanStartY = this.panY;
        if (this.canvas) this.canvas.style.cursor = 'grabbing';
    }

    _handleMouseMove(e) {
        if (!this._dragging) {
            // Check for overlay hover
            this._updateCursorForOverlays(e);
            return;
        }

        const dx = e.clientX - this._dragStartX;
        const dy = e.clientY - this._dragStartY;
        this.panX = this._dragPanStartX + dx;
        this.panY = this._dragPanStartY + dy;
        this._render();
    }

    _handleMouseUp(e) {
        if (this._dragging) {
            const dx = Math.abs(e.clientX - this._dragStartX);
            const dy = Math.abs(e.clientY - this._dragStartY);

            // If it was a click (not a drag), check for overlay click
            if (dx < 3 && dy < 3) {
                this._handleOverlayClick(e);
            }
        }

        this._dragging = false;
        if (this.canvas) this.canvas.style.cursor = 'grab';
    }

    _handleWheel(e) {
        e.preventDefault();
        if (!this.canvas) return;

        const rect = this.canvas.getBoundingClientRect();
        const mouseX = e.clientX - rect.left;
        const mouseY = e.clientY - rect.top;

        // Zoom toward/away from mouse position
        const oldZoom = this.zoom;
        const delta = e.deltaY > 0 ? -ZOOM_STEP : ZOOM_STEP;
        this.zoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, this.zoom + delta * this.zoom));

        // Adjust pan so the point under the mouse stays fixed
        const zoomRatio = this.zoom / oldZoom;
        this.panX = mouseX - (mouseX - this.panX) * zoomRatio;
        this.panY = mouseY - (mouseY - this.panY) * zoomRatio;

        this._render();
    }

    _handleResize() {
        this._resizeCanvas();
        this._render();
    }

    _screenToImage(screenX, screenY) {
        return {
            x: (screenX - this.panX) / this.zoom,
            y: (screenY - this.panY) / this.zoom,
        };
    }

    _updateCursorForOverlays(e) {
        if (!this.canvas || !this._overlaysVisible) return;

        const rect = this.canvas.getBoundingClientRect();
        const pt = this._screenToImage(e.clientX - rect.left, e.clientY - rect.top);

        const hit = this.overlays.some(o =>
            pt.x >= o.x && pt.x <= o.x + o.w &&
            pt.y >= o.y && pt.y <= o.y + o.h
        );

        this.canvas.style.cursor = hit ? 'pointer' : 'grab';
    }

    _handleOverlayClick(e) {
        if (!this.canvas || !this._overlaysVisible || !this.onOverlayClick) return;

        const rect = this.canvas.getBoundingClientRect();
        const pt = this._screenToImage(e.clientX - rect.left, e.clientY - rect.top);

        for (const overlay of this.overlays) {
            if (pt.x >= overlay.x && pt.x <= overlay.x + overlay.w &&
                pt.y >= overlay.y && pt.y <= overlay.y + overlay.h) {
                this.onOverlayClick(overlay);
                return;
            }
        }
    }

    // ── Centering Overlay ────────────────────────────────────────────

    addCenteringOverlay(bLeft, bRight, bTop, bBottom) {
        this._centeringLines = { bLeft, bRight, bTop, bBottom };
        this._render();
    }

    removeCenteringOverlay() {
        this._centeringLines = null;
        this._render();
    }

    _renderCenteringOverlay(ctx) {
        if (!this._centeringLines || !this.image) return;

        const { bLeft, bRight, bTop, bBottom } = this._centeringLines;
        const imgW = this.image.width;
        const imgH = this.image.height;

        ctx.save();

        // Border lines (green dashed)
        ctx.strokeStyle = '#22c55e';
        ctx.lineWidth = 2 / this.zoom;
        ctx.setLineDash([8 / this.zoom, 4 / this.zoom]);

        // Left border
        ctx.beginPath();
        ctx.moveTo(bLeft, 0);
        ctx.lineTo(bLeft, imgH);
        ctx.stroke();

        // Right border
        ctx.beginPath();
        ctx.moveTo(imgW - bRight, 0);
        ctx.lineTo(imgW - bRight, imgH);
        ctx.stroke();

        // Top border
        ctx.beginPath();
        ctx.moveTo(0, bTop);
        ctx.lineTo(imgW, bTop);
        ctx.stroke();

        // Bottom border
        ctx.beginPath();
        ctx.moveTo(0, imgH - bBottom);
        ctx.lineTo(imgW, imgH - bBottom);
        ctx.stroke();

        // Center crosshair (white dashed)
        ctx.strokeStyle = 'rgba(255,255,255,0.6)';
        ctx.lineWidth = 1 / this.zoom;
        ctx.setLineDash([4 / this.zoom, 6 / this.zoom]);

        const cx = imgW / 2;
        const cy = imgH / 2;

        ctx.beginPath();
        ctx.moveTo(cx, 0);
        ctx.lineTo(cx, imgH);
        ctx.stroke();

        ctx.beginPath();
        ctx.moveTo(0, cy);
        ctx.lineTo(imgW, cy);
        ctx.stroke();

        // Border width labels
        ctx.setLineDash([]);
        const fontSize = Math.max(12, 16 / this.zoom);
        ctx.font = `bold ${fontSize}px sans-serif`;
        ctx.textAlign = 'center';

        // Left label
        ctx.fillStyle = 'rgba(0,0,0,0.7)';
        ctx.fillRect(bLeft / 2 - 20 / this.zoom, cy - fontSize, 40 / this.zoom, fontSize + 4 / this.zoom);
        ctx.fillStyle = '#22c55e';
        ctx.fillText(`${bLeft}`, bLeft / 2, cy - 2 / this.zoom);

        // Right label
        ctx.fillStyle = 'rgba(0,0,0,0.7)';
        ctx.fillRect(imgW - bRight / 2 - 20 / this.zoom, cy - fontSize, 40 / this.zoom, fontSize + 4 / this.zoom);
        ctx.fillStyle = '#22c55e';
        ctx.fillText(`${bRight}`, imgW - bRight / 2, cy - 2 / this.zoom);

        // Top label
        ctx.fillStyle = 'rgba(0,0,0,0.7)';
        ctx.fillRect(cx - 20 / this.zoom, bTop / 2 - fontSize / 2, 40 / this.zoom, fontSize + 4 / this.zoom);
        ctx.fillStyle = '#22c55e';
        ctx.fillText(`${bTop}`, cx, bTop / 2 + fontSize / 2 - 2 / this.zoom);

        // Bottom label
        ctx.fillStyle = 'rgba(0,0,0,0.7)';
        ctx.fillRect(cx - 20 / this.zoom, imgH - bBottom / 2 - fontSize / 2, 40 / this.zoom, fontSize + 4 / this.zoom);
        ctx.fillStyle = '#22c55e';
        ctx.fillText(`${bBottom}`, cx, imgH - bBottom / 2 + fontSize / 2 - 2 / this.zoom);

        ctx.restore();
    }
}
