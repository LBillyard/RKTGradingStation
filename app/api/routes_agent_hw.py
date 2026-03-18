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

    return {
        "status": "online",
        "version": AGENT_VERSION,
        "station_id": settings.station_id,
        "mode": settings.mode,
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
