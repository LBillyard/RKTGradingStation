"""Agent hardware routes — served by the local agent on localhost:8742.

These endpoints drive physical hardware (scanner, printer, NFC reader)
and are only registered when RKT_MODE is 'agent' or 'desktop'.
"""

import asyncio
import logging
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


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
async def agent_status():
    """Agent health check — returns hardware availability and version."""
    from agent_version import AGENT_VERSION

    scanner = _get_scanner()
    printer = _get_printer()
    nfc = _get_nfc_reader()

    scanner_devices = await asyncio.to_thread(scanner.list_devices) if hasattr(scanner, 'list_devices') else []
    printers = await asyncio.to_thread(printer.list_printers)
    nfc_readers = await asyncio.to_thread(nfc.list_readers)

    # Get telemetry summary
    telemetry = {}
    try:
        from app.services.agent.telemetry import get_productivity_stats, get_pending_sync
        telemetry = {
            "productivity": get_productivity_stats(),
            "pending_sync": len(get_pending_sync()),
        }
    except Exception:
        pass

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
async def list_scan_devices():
    """List available scanner devices."""
    scanner = _get_scanner()
    if hasattr(scanner, 'list_devices'):
        devices = await asyncio.to_thread(scanner.list_devices)
        return {"devices": devices, "mock_mode": settings.scanner.mock_mode}
    return {"devices": [], "mock_mode": settings.scanner.mock_mode}


@router.post("/scan")
async def acquire_scan(req: ScanRequest):
    """Acquire an image from the scanner.

    Returns the scanned image as base64-encoded PNG.
    """
    import base64

    scanner = _get_scanner()
    try:
        # Auto-connect to first available device if not already connected
        if hasattr(scanner, 'is_connected') and not scanner.is_connected():
            if hasattr(scanner, 'list_devices'):
                devices = await asyncio.to_thread(scanner.list_devices)
                if devices:
                    device_id = devices[0].device_id if hasattr(devices[0], 'device_id') else devices[0].get('device_id', '')
                    if device_id:
                        await asyncio.to_thread(scanner.connect, device_id)
                        logger.info(f"Auto-connected to scanner: {device_id}")
                    else:
                        raise RuntimeError("Scanner found but no device_id available")
                else:
                    raise RuntimeError("No scanner devices found — is the scanner connected?")

        result = await asyncio.to_thread(scanner.scan, req.dpi)

        if hasattr(result, 'image_path') and result.image_path:
            image_path = result.image_path
        elif isinstance(result, str):
            image_path = result
        elif isinstance(result, dict) and 'image_path' in result:
            image_path = result['image_path']
        else:
            raise RuntimeError(f"Unexpected scan result type: {type(result)}")

        # Read and encode the image
        with open(image_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode()

        return {
            "status": "success",
            "image_data": image_data,
            "image_path": image_path,
            "format": "png",
        }
    except Exception as e:
        logger.error(f"Scan failed: {e}")
        raise HTTPException(500, f"Scan failed: {e}")


# ---- Printer ----

@router.get("/printers")
async def list_printers():
    """List available printers."""
    printer = _get_printer()
    printers = await asyncio.to_thread(printer.list_printers)
    return {"printers": printers, "mock_mode": settings.printer.mock_mode}


@router.post("/print")
async def print_image(req: PrintRequest):
    """Download an image from a URL and print it."""
    printer = _get_printer()
    width = req.width_mm or settings.printer.label_width_mm
    height = req.height_mm or settings.printer.label_height_mm
    printer_name = req.printer_name or settings.printer.printer_name

    try:
        # Download the image to a temp file
        import httpx

        async with httpx.AsyncClient() as client:
            resp = await client.get(req.image_url, timeout=30.0)
            resp.raise_for_status()

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp.write(resp.content)
            tmp_path = tmp.name

        # Print it
        result = await asyncio.to_thread(
            printer.print_image,
            image_path=tmp_path,
            printer_name=printer_name or "default",
            width_mm=width,
            height_mm=height,
            dpi=settings.printer.dpi,
        )

        # Clean up temp file
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
async def list_nfc_readers():
    """List available NFC readers."""
    nfc = _get_nfc_reader()
    readers = await asyncio.to_thread(nfc.list_readers)
    return {"readers": readers, "mock_mode": settings.nfc.mock_mode}


@router.get("/nfc/detect")
async def detect_nfc_tag():
    """Detect what tag is on the NFC reader."""
    nfc = _get_nfc_reader()
    if settings.nfc.mock_mode:
        tag_info = nfc.detect_tag()
    else:
        info = await asyncio.to_thread(nfc.connect, settings.nfc.reader_name)
        if not info.is_connected:
            return {"detected": False, "error": "No NFC reader connected"}
        tag_info = await asyncio.to_thread(nfc.detect_tag)
        nfc.disconnect()

    if tag_info:
        return {"detected": True, "uid": tag_info.uid, "tag_type": tag_info.tag_type}
    return {"detected": False}


@router.post("/nfc/program")
async def program_nfc_tag(req: NfcProgramRequest):
    """Program an NFC tag with the given payload."""
    nfc = _get_nfc_reader()

    try:
        if settings.nfc.mock_mode:
            if req.tag_type == "ntag424_dna":
                result = nfc.program_ntag424(req.serial_number, req.base_url)
            else:
                result = nfc.program_ntag213(req.serial_number, req.base_url)
        else:
            info = await asyncio.to_thread(nfc.connect, settings.nfc.reader_name)
            if not info.is_connected:
                raise RuntimeError("No NFC reader connected")

            if req.tag_type == "ntag424_dna":
                from app.services.nfc.ntag424 import program_sdm
                master_key = bytes.fromhex(req.master_key or settings.nfc_master_key)
                sdm_file_key = bytes.fromhex(req.sdm_file_read_key or settings.nfc_sdm_file_read_key)
                sdm_meta_key = bytes.fromhex(req.sdm_meta_read_key or settings.nfc_sdm_meta_read_key)
                result = await asyncio.to_thread(
                    program_sdm, nfc, req.serial_number, req.base_url,
                    master_key, sdm_file_key, sdm_meta_key,
                )
            else:
                from app.services.nfc.ntag213 import program_url
                result = await asyncio.to_thread(
                    program_url, nfc, req.serial_number, req.base_url,
                )
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

    quality = await asyncio.to_thread(analyze_scan_quality, image_path)
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

    quality = await asyncio.to_thread(analyze_scan_quality, image_path)
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

    img_hash = await asyncio.to_thread(hash_image, image_path)
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

    signed_record = {
        "image_hash": original_hash,
        "station_id": station_id,
        "operator": operator,
        "timestamp": timestamp,
        "signature": signature,
    }
    result = await asyncio.to_thread(verify_image_integrity, image_path, signed_record)
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
