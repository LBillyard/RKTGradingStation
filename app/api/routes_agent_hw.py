"""Agent hardware routes — served by the local agent on localhost:8742.

These endpoints drive physical hardware (scanner, printer, NFC reader)
and are only registered when RKT_MODE is 'agent' or 'desktop'.
"""

import ipaddress
import logging
import socket
import tempfile
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import settings


# ---- Security helpers ----

_BLOCKED_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
]


def _validate_url_safe(url: str) -> str:
    """Validate a URL is safe to fetch (no SSRF to internal networks).

    Returns the validated URL. Raises HTTPException(400) if blocked.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(400, f"URL scheme '{parsed.scheme}' not allowed; only http/https")

    hostname = parsed.hostname
    if not hostname:
        raise HTTPException(400, "URL has no hostname")

    # Resolve hostname and check all IPs
    try:
        addr_infos = socket.getaddrinfo(hostname, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise HTTPException(400, f"Cannot resolve hostname: {hostname}")

    for family, _, _, _, sockaddr in addr_infos:
        ip = ipaddress.ip_address(sockaddr[0])
        for network in _BLOCKED_NETWORKS:
            if ip in network:
                raise HTTPException(400, "URL resolves to a blocked private/internal IP address")

    return url


def _validate_image_path(image_path: str) -> Path:
    """Validate an image path is within the allowed data directory.

    Returns the resolved Path. Raises HTTPException(400) if invalid.
    """
    if ".." in image_path:
        raise HTTPException(400, "Invalid image path")

    resolved = Path(image_path).resolve()
    allowed_dir = Path("data").resolve()

    if not resolved.is_relative_to(allowed_dir):
        raise HTTPException(400, "Invalid image path")

    return resolved

logger = logging.getLogger(__name__)
router = APIRouter()


def _detect_and_crop_cards(pil_img) -> list[dict]:
    """Detect cards in a full-bed scan and return cropped card images as base64.

    Uses OpenCV contour detection to find card-shaped rectangles, then
    perspective-corrects and crops each one with a small border.
    Returns a list of dicts with 'image_data' (base64 PNG) per card.
    """
    import base64
    import io

    import cv2
    import numpy as np
    from PIL import Image as PILImage

    # Convert PIL to OpenCV
    img_array = np.array(pil_img)
    if len(img_array.shape) == 3 and img_array.shape[2] == 3:
        bgr = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
    else:
        bgr = img_array

    h, w = bgr.shape[:2]
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)

    cards = []

    # Try multiple edge detection methods
    for method in ['canny', 'adaptive', 'otsu']:
        if method == 'canny':
            edges = cv2.Canny(blurred, 30, 150)
            edges = cv2.dilate(edges, None, iterations=2)
        elif method == 'adaptive':
            thresh = cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 11, 2)
            edges = cv2.dilate(thresh, None, iterations=2)
        else:
            _, edges = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
            edges = cv2.dilate(edges, None, iterations=2)

        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        # Sort by area descending
        contours = sorted(contours, key=cv2.contourArea, reverse=True)

        for cnt in contours[:10]:
            area = cv2.contourArea(cnt)
            # Card must be at least 2% of image (very small on scanner bed)
            if area < h * w * 0.02:
                continue

            peri = cv2.arcLength(cnt, True)
            approx = cv2.approxPolyDP(cnt, 0.02 * peri, True)

            if len(approx) == 4:
                # Check aspect ratio (card is ~0.714 = 63/88mm)
                rect = cv2.minAreaRect(cnt)
                rw, rh = rect[1]
                if rw == 0 or rh == 0:
                    continue
                aspect = min(rw, rh) / max(rw, rh)
                if aspect < 0.45 or aspect > 0.95:
                    continue

                # Check not duplicate (IoU with existing)
                is_dup = False
                for existing in cards:
                    iou = _compute_iou(approx.reshape(4, 2), existing['corners'])
                    if iou > 0.5:
                        is_dup = True
                        break
                if is_dup:
                    continue

                corners = approx.reshape(4, 2)
                cards.append({'corners': corners, 'area': area})

        if cards:
            break  # Found cards with this method

    if not cards:
        return []

    # Sort cards by position (top-to-bottom, left-to-right)
    cards.sort(key=lambda c: (c['corners'][:, 1].mean(), c['corners'][:, 0].mean()))

    results = []
    for card_info in cards[:8]:  # Max 8 cards
        corners = card_info['corners'].astype(np.float32)

        # Order corners: TL, TR, BR, BL
        ordered = _order_corners(corners)

        # Expand slightly (5%) to keep card border visible
        center = ordered.mean(axis=0)
        expanded = center + (ordered - center) * 1.05

        # Destination size: standard card at scan DPI
        dst_w, dst_h = 750, 1050
        dst = np.array([[0, 0], [dst_w, 0], [dst_w, dst_h], [0, dst_h]], dtype=np.float32)

        M = cv2.getPerspectiveTransform(expanded.astype(np.float32), dst)
        warped = cv2.warpPerspective(bgr, M, (dst_w, dst_h), flags=cv2.INTER_LANCZOS4)

        # Convert back to PIL and encode
        rgb = cv2.cvtColor(warped, cv2.COLOR_BGR2RGB)
        card_pil = PILImage.fromarray(rgb)

        buf = io.BytesIO()
        card_pil.save(buf, format="PNG", optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode()

        results.append({
            "image_data": b64,
            "width": dst_w,
            "height": dst_h,
        })
        logger.info(f"Cropped card {len(results)}: {len(buf.getvalue())} bytes")

    return results


def _order_corners(pts):
    """Order corners: top-left, top-right, bottom-right, bottom-left."""
    import numpy as np
    rect = np.zeros((4, 2), dtype=np.float32)
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).flatten()
    rect[0] = pts[np.argmin(s)]   # TL: smallest sum
    rect[2] = pts[np.argmax(s)]   # BR: largest sum
    rect[1] = pts[np.argmin(d)]   # TR: smallest diff
    rect[3] = pts[np.argmax(d)]   # BL: largest diff
    return rect


def _compute_iou(corners1, corners2):
    """Compute IoU between two sets of 4 corners using bounding rects."""
    import numpy as np
    r1 = (corners1[:, 0].min(), corners1[:, 1].min(), corners1[:, 0].max(), corners1[:, 1].max())
    r2 = (corners2[:, 0].min(), corners2[:, 1].min(), corners2[:, 0].max(), corners2[:, 1].max())
    x1 = max(r1[0], r2[0])
    y1 = max(r1[1], r2[1])
    x2 = min(r1[2], r2[2])
    y2 = min(r1[3], r2[3])
    if x2 <= x1 or y2 <= y1:
        return 0.0
    inter = (x2 - x1) * (y2 - y1)
    a1 = (r1[2] - r1[0]) * (r1[3] - r1[1])
    a2 = (r2[2] - r2[0]) * (r2[3] - r2[1])
    return inter / (a1 + a2 - inter)


# ---- Request models ----

class PrintRequest(BaseModel):
    image_url: str  # URL to download and print
    printer_name: Optional[str] = None
    width_mm: Optional[float] = None
    height_mm: Optional[float] = None


class NfcProgramRequest(BaseModel):
    tag_type: str = "ntag424_dna"  # "ntag213" or "ntag424_dna"
    serial_number: str
    base_url: str = "https://rktgrading.com/verify"
    # NTag424 DNA keys (hex strings, only needed for ntag424_dna)
    master_key: Optional[str] = None
    sdm_file_read_key: Optional[str] = None
    sdm_meta_read_key: Optional[str] = None


class ScanRequest(BaseModel):
    dpi: int = 600
    device_id: Optional[str] = None


# ---- Helpers ----

def _get_scanner():
    if settings.scanner.mock_mode:
        from app.services.scanner.mock_scanner import MockScanner
        return MockScanner()
    else:
        from app.services.scanner.wia_scanner import WIAScanner
        return WIAScanner()


def _get_printer():
    if settings.printer.mock_mode:
        from app.services.printer.mock_printer import MockPrinter
        return MockPrinter()
    else:
        from app.services.printer.gdi_printer import GdiPrinter
        return GdiPrinter()


def _get_nfc_reader():
    if settings.nfc.mock_mode:
        from app.services.nfc.mock_nfc import MockNfcReader
        return MockNfcReader()
    else:
        from app.services.nfc.reader import NfcReader
        return NfcReader()


# ---- Status ----

@router.get("/status")
def agent_status():
    """Agent health check — returns hardware availability and version.

    Note: hardware enumeration is deferred to dedicated endpoints
    (/scanner/devices, /printer/list, /nfc/readers) to avoid COM
    threading deadlocks with uvicorn on Windows.
    """
    from agent_version import AGENT_VERSION

    scanner = _get_scanner()
    printer = _get_printer()
    nfc = _get_nfc_reader()

    try:
        scanner_devices = scanner.list_devices() if hasattr(scanner, 'list_devices') else []
    except Exception:
        scanner_devices = []
    try:
        printers = printer.list_printers()
    except Exception:
        printers = []
    try:
        nfc_readers = nfc.list_readers()
    except Exception:
        nfc_readers = []

    telemetry = {}

    return {
        "status": "online",
        "version": AGENT_VERSION,
        "station_id": settings.station_id,
        "mode": settings.mode,
        "telemetry": telemetry,
        "hardware": {
            "scanner": {
                "mock_mode": settings.scanner.mock_mode,
                "devices": scanner_devices if isinstance(scanner_devices, list) else [],
            },
            "printer": {
                "mock_mode": settings.printer.mock_mode,
                "printers": printers,
            },
            "nfc": {
                "mock_mode": settings.nfc.mock_mode,
                "readers": nfc_readers,
            },
        },
    }


# ---- Scanner ----

@router.get("/scan/devices")
def list_scan_devices():
    """List available scanner devices."""
    scanner = _get_scanner()
    if hasattr(scanner, 'list_devices'):
        devices = scanner.list_devices()
        return {"devices": devices, "mock_mode": settings.scanner.mock_mode}
    return {"devices": [], "mock_mode": settings.scanner.mock_mode}


@router.post("/scan")
def acquire_scan(req: ScanRequest):
    """Acquire an image from the scanner.

    Returns the scanned image as base64-encoded PNG.
    """
    import base64

    scanner = _get_scanner()
    try:
        # Auto-connect to first available device if not already connected
        if hasattr(scanner, 'is_connected') and not scanner.is_connected():
            if hasattr(scanner, 'list_devices'):
                devices = scanner.list_devices()
                if devices:
                    device_id = devices[0].device_id if hasattr(devices[0], 'device_id') else devices[0].get('device_id', '')
                    if device_id:
                        scanner.connect(device_id)
                        logger.info(f"Auto-connected to scanner: {device_id}")
                    else:
                        raise RuntimeError("Scanner found but no device_id available")
                else:
                    raise RuntimeError("No scanner devices found — is the scanner connected?")

        result = scanner.scan(req.dpi)

        # Get PIL image from result
        pil_img = None
        if hasattr(result, 'image') and result.image is not None:
            pil_img = result.image
        elif hasattr(result, 'image_path') and result.image_path:
            from PIL import Image as PILImage
            pil_img = PILImage.open(result.image_path)
        elif isinstance(result, str):
            from PIL import Image as PILImage
            pil_img = PILImage.open(result)
        elif isinstance(result, dict) and 'image_path' in result:
            from PIL import Image as PILImage
            pil_img = PILImage.open(result['image_path'])
        else:
            raise RuntimeError(f"Unexpected scan result type: {type(result)}")

        # Detect and crop cards from the full-bed scan
        cards_data = _detect_and_crop_cards(pil_img)

        if cards_data:
            # Return cropped card images (much smaller than full bed)
            logger.info(f"Detected {len(cards_data)} card(s), uploading cropped images")
            return {
                "status": "success",
                "cards": cards_data,
                "card_count": len(cards_data),
                "format": "png",
            }
        else:
            # Fallback: no cards detected, send full image
            import io
            buf = io.BytesIO()
            pil_img.save(buf, format="PNG")
            image_data = base64.b64encode(buf.getvalue()).decode()
            logger.warning("No cards detected in scan, sending full bed image")
            return {
                "status": "success",
                "image_data": image_data,
                "image_path": "memory",
            "format": "png",
        }
    except Exception as e:
        logger.error(f"Scan failed: {e}")
        raise HTTPException(500, f"Scan failed: {e}")


# ---- Printer ----

@router.get("/printers")
def list_printers():
    """List available printers."""
    printer = _get_printer()
    printers = printer.list_printers()
    return {"printers": printers, "mock_mode": settings.printer.mock_mode}


@router.post("/print")
def print_image(req: PrintRequest):
    """Download an image from a URL and print it."""
    printer = _get_printer()
    width = req.width_mm or settings.printer.label_width_mm
    height = req.height_mm or settings.printer.label_height_mm
    printer_name = req.printer_name or settings.printer.printer_name

    try:
        # Validate URL before fetching (SSRF protection)
        _validate_url_safe(req.image_url)

        # Download the image to a temp file
        import httpx

        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.get(req.image_url, timeout=30.0)
            resp.raise_for_status()

        # Validate final URL after redirects (SSRF protection)
        _validate_url_safe(str(resp.url))

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp.write(resp.content)
            tmp_path = tmp.name

        # Print it
        try:
            result = printer.print_image(
                image_path=tmp_path,
                printer_name=printer_name or "default",
                width_mm=width,
                height_mm=height,
                dpi=settings.printer.dpi,
            )
        finally:
            # Clean up temp file even if print_image throws
            Path(tmp_path).unlink(missing_ok=True)

        return {
            "status": result.status,
            "printer_name": result.printer_name,
            "error": result.error,
        }
    except Exception as e:
        logger.error(f"Print failed: {e}")
        raise HTTPException(500, f"Print failed: {e}")


# ---- NFC ----

@router.get("/nfc/readers")
def list_nfc_readers():
    """List available NFC readers."""
    nfc = _get_nfc_reader()
    readers = nfc.list_readers()
    return {"readers": readers, "mock_mode": settings.nfc.mock_mode}


@router.get("/nfc/detect")
def detect_nfc_tag():
    """Detect what tag is on the NFC reader."""
    nfc = _get_nfc_reader()
    if settings.nfc.mock_mode:
        tag_info = nfc.detect_tag()
    else:
        info = nfc.connect(settings.nfc.reader_name)
        if not info.is_connected:
            return {"detected": False, "error": "No NFC reader connected"}
        try:
            tag_info = nfc.detect_tag()
        finally:
            nfc.disconnect()

    if tag_info:
        return {"detected": True, "uid": tag_info.uid, "tag_type": tag_info.tag_type}
    return {"detected": False}


@router.post("/nfc/program")
def program_nfc_tag(req: NfcProgramRequest):
    """Program an NFC tag with the given payload."""
    nfc = _get_nfc_reader()

    try:
        if settings.nfc.mock_mode:
            if req.tag_type == "ntag424_dna":
                result = nfc.program_ntag424(req.serial_number, req.base_url)
            else:
                result = nfc.program_ntag213(req.serial_number, req.base_url)
        else:
            info = nfc.connect(settings.nfc.reader_name)
            if not info.is_connected:
                raise RuntimeError("No NFC reader connected")

            try:
                if req.tag_type == "ntag424_dna":
                    from app.services.nfc.ntag424 import program_sdm
                    master_key = bytes.fromhex(req.master_key or settings.nfc_master_key)
                    sdm_file_key = bytes.fromhex(req.sdm_file_read_key or settings.nfc_sdm_file_read_key)
                    sdm_meta_key = bytes.fromhex(req.sdm_meta_read_key or settings.nfc_sdm_meta_read_key)
                    result = program_sdm(nfc, req.serial_number, req.base_url,
                        master_key, sdm_file_key, sdm_meta_key)
                else:
                    from app.services.nfc.ntag213 import program_url
                    result = program_url(nfc, req.serial_number, req.base_url)
            finally:
                nfc.disconnect()

        return {
            "status": result.status,
            "tag_uid": result.tag_uid,
            "tag_type": result.tag_type,
            "ndef_url": result.ndef_url,
            "sdm_configured": result.sdm_configured,
            "error": result.error,
        }
    except Exception as e:
        logger.error(f"NFC programming failed: {e}")
        raise HTTPException(500, f"NFC programming failed: {e}")


# ---- Telemetry & Monitoring ----

@router.get("/telemetry/productivity")
async def get_productivity():
    """Get operator productivity stats (cards/hour, timing breakdowns)."""
    from app.services.agent.telemetry import get_productivity_stats
    return get_productivity_stats()


@router.get("/telemetry/metrics")
async def get_telemetry_metrics(metric_type: Optional[str] = None, limit: int = 100):
    """Get recent telemetry metrics."""
    from app.services.agent.telemetry import get_metrics
    return {"metrics": get_metrics(metric_type, limit)}


@router.post("/telemetry/session/start")
async def start_grading_session(operator_name: str = "", station_id: str = ""):
    """Start timing a new grading session."""
    from app.services.agent.telemetry import start_session
    session = start_session(operator_name, station_id or settings.station_id)
    return {"session_id": session.id, "started_at": session.started_at}


@router.post("/telemetry/session/{session_id}/update")
async def update_grading_session(session_id: str, phase: str):
    """Update session timing (phase: scan_started, scan_completed, grade_started, etc)."""
    from app.services.agent.telemetry import update_session
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    valid_phases = [
        "scan_started_at", "scan_completed_at", "grade_started_at",
        "grade_completed_at", "print_started_at", "print_completed_at",
        "nfc_started_at", "nfc_completed_at",
    ]
    field = f"{phase}_at" if not phase.endswith("_at") else phase
    if field not in valid_phases:
        raise HTTPException(400, f"Invalid phase. Use: {valid_phases}")
    session = update_session(session_id, **{field: now})
    if not session:
        raise HTTPException(404, "Session not found")
    return {"session_id": session_id, field: now}


@router.post("/telemetry/session/{session_id}/complete")
async def complete_grading_session(session_id: str):
    """Complete a grading session and calculate total time."""
    from app.services.agent.telemetry import complete_session
    session = complete_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    return {
        "session_id": session.id,
        "total_seconds": session.total_seconds,
        "status": session.status,
    }


# ---- Scanner Quality ----

@router.get("/scanner/quality")
async def get_scanner_quality():
    """Get scanner quality trend data."""
    from app.services.agent.telemetry import get_scanner_quality_trend
    return {"readings": get_scanner_quality_trend()}


@router.post("/scanner/quality/check")
async def check_scan_quality(image_path: str = ""):
    """Analyze a scanned image for quality metrics."""
    from app.services.agent.image_security import analyze_scan_quality
    from app.services.agent.telemetry import record_scan_quality

    if not image_path:
        # Use the most recent scan if no path provided
        return {"error": "Provide image_path parameter"}

    validated_path = _validate_image_path(image_path)
    quality = analyze_scan_quality(str(validated_path))
    record_scan_quality(
        brightness=quality["brightness"],
        contrast=quality["contrast"],
        sharpness=quality["sharpness"],
        noise_level=quality["noise_level"],
        station_id=settings.station_id,
    )
    return quality


@router.post("/scanner/calibrate")
async def calibration_check(image_path: str):
    """Run a calibration check against a reference card scan."""
    from app.services.agent.image_security import analyze_scan_quality
    from app.services.agent.telemetry import record_scan_quality

    validated_path = _validate_image_path(image_path)
    quality = analyze_scan_quality(str(validated_path))
    record_scan_quality(
        brightness=quality["brightness"],
        contrast=quality["contrast"],
        sharpness=quality["sharpness"],
        noise_level=quality["noise_level"],
        station_id=settings.station_id,
        is_calibration=True,
    )
    return {**quality, "type": "calibration_baseline"}


# ---- Image Security ----

@router.post("/security/hash")
async def hash_scanned_image(image_path: str, operator_name: str = ""):
    """Hash and sign a scanned image for tamper detection."""
    from app.services.agent.image_security import hash_image, sign_image
    from app.services.agent.telemetry import log_custody_event

    validated_path = _validate_image_path(image_path)
    img_hash = hash_image(str(validated_path))
    signed = sign_image(img_hash, settings.station_id, operator_name)

    # Log custody event
    log_custody_event(
        event_type="image_captured",
        operator_name=operator_name,
        station_id=settings.station_id,
        image_hash=img_hash,
        details=f"Signed at {signed['timestamp']}",
    )

    return signed


@router.post("/security/verify")
async def verify_image(image_path: str, original_hash: str, signature: str,
                       station_id: str = "", operator: str = "", timestamp: str = ""):
    """Verify image integrity against a signed record."""
    from app.services.agent.image_security import verify_image_integrity

    validated_path = _validate_image_path(image_path)
    signed_record = {
        "image_hash": original_hash,
        "station_id": station_id,
        "operator": operator,
        "timestamp": timestamp,
        "signature": signature,
    }
    result = verify_image_integrity(str(validated_path), signed_record)
    return result


# ---- Chain of Custody ----

@router.get("/custody/{card_serial}")
async def get_card_custody(card_serial: str):
    """Get the full chain of custody for a card."""
    from app.services.agent.telemetry import get_custody_chain
    return {"card_serial": card_serial, "events": get_custody_chain(card_serial)}


@router.post("/custody/log")
async def log_custody(event_type: str, card_serial: str = "", operator_name: str = "", details: str = ""):
    """Log a custody event manually."""
    from app.services.agent.telemetry import log_custody_event
    log_custody_event(
        event_type=event_type,
        card_serial=card_serial,
        operator_name=operator_name,
        station_id=settings.station_id,
        details=details,
    )
    return {"status": "logged"}


# ---- Offline Cache ----

@router.get("/cache/pending")
async def get_pending_cache():
    """Get items waiting to sync to the cloud."""
    from app.services.agent.telemetry import get_pending_sync
    pending = get_pending_sync()
    return {"pending_count": len(pending), "items": pending[:20]}


@router.post("/cache/sync")
async def sync_to_cloud():
    """Manually trigger sync of cached items to the cloud."""
    from app.services.agent.telemetry import sync_cached_items
    result = sync_cached_items(settings.nfc.verify_base_url.rsplit("/", 1)[0])
    return result


# ---- Print Tracking ----

@router.get("/print/stats")
async def get_print_stats():
    """Get print job statistics and ink usage estimates."""
    from app.services.agent.telemetry import get_metrics
    print_metrics = get_metrics("print")
    total_prints = len(print_metrics)

    # Rough ink estimate: ~0.5ml per label, C6000 has ~50ml per cartridge
    estimated_ink_used_ml = total_prints * 0.5
    estimated_remaining_pct = max(0, 100 - (estimated_ink_used_ml / 50 * 100))

    return {
        "total_prints": total_prints,
        "estimated_ink_used_ml": round(estimated_ink_used_ml, 1),
        "estimated_remaining_pct": round(estimated_remaining_pct, 1),
        "labels_until_empty": max(0, int((50 - estimated_ink_used_ml) / 0.5)),
    }
