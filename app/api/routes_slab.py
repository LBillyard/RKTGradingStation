"""Slab assembly API routes — print labels, program NFC tags, track workflow."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.core.events import Events, event_bus
from app.db.database import get_db
from app.models.card import CardRecord
from app.models.grading import GradeDecision
from app.models.slab import PrintJob, NfcTag, SlabAssembly

logger = logging.getLogger(__name__)
router = APIRouter()


# ---- Request / Response models ----

class StartAssemblyRequest(BaseModel):
    card_record_id: str


class PrintRequest(BaseModel):
    template_name: Optional[str] = None
    printer_name: Optional[str] = None


class NfcProgramRequest(BaseModel):
    reader_name: Optional[str] = None


# ---- Helpers ----

def _get_assembly_or_404(assembly_id: str, db: Session) -> SlabAssembly:
    assembly = db.query(SlabAssembly).filter(SlabAssembly.id == assembly_id).first()
    if not assembly:
        raise HTTPException(404, "Slab assembly not found")
    return assembly


def _get_printer():
    """Get the appropriate printer implementation based on mock mode."""
    if settings.printer.mock_mode:
        from app.services.printer.mock_printer import MockPrinter
        return MockPrinter()
    else:
        from app.services.printer.gdi_printer import GdiPrinter
        return GdiPrinter()


def _get_nfc_reader():
    """Get the appropriate NFC reader based on mock mode."""
    if settings.nfc.mock_mode:
        from app.services.nfc.mock_nfc import MockNfcReader
        return MockNfcReader()
    else:
        from app.services.nfc.reader import NfcReader
        return NfcReader()


def _assembly_to_dict(assembly: SlabAssembly, db: Session) -> dict:
    """Convert a SlabAssembly to a response dict with related records."""
    result = {
        "id": assembly.id,
        "card_record_id": assembly.card_record_id,
        "serial_number": assembly.serial_number,
        "grade": assembly.grade,
        "workflow_status": assembly.workflow_status,
        "completed_at": assembly.completed_at.isoformat() if assembly.completed_at else None,
        "created_at": assembly.created_at.isoformat() if assembly.created_at else None,
        "print_job": None,
        "nfc_tag": None,
    }

    if assembly.print_job_id:
        pj = db.query(PrintJob).filter(PrintJob.id == assembly.print_job_id).first()
        if pj:
            result["print_job"] = {
                "id": pj.id, "status": pj.status,
                "image_path": pj.image_path, "printer_name": pj.printer_name,
                "printed_at": pj.printed_at.isoformat() if pj.printed_at else None,
            }

    # Use whichever NFC tag is linked (424 preferred, fallback to 213)
    nfc_tag_id = assembly.nfc_424_tag_id or assembly.nfc_213_tag_id
    if nfc_tag_id:
        tag = db.query(NfcTag).filter(NfcTag.id == nfc_tag_id).first()
        if tag:
            result["nfc_tag"] = {
                "id": tag.id, "tag_uid": tag.tag_uid, "tag_type": tag.tag_type,
                "ndef_url": tag.ndef_url, "status": tag.status,
                "sdm_configured": tag.sdm_configured,
                "error_message": tag.error_message,
                "programmed_at": tag.programmed_at.isoformat() if tag.programmed_at else None,
            }

    # Include card info
    card = db.query(CardRecord).filter(CardRecord.id == assembly.card_record_id).first()
    if card:
        result["card"] = {
            "card_name": card.card_name,
            "set_name": card.set_name,
            "rarity": card.rarity,
        }

    return result


# ---- Endpoints ----

@router.post("/start")
async def start_assembly(req: StartAssemblyRequest, db: Session = Depends(get_db)):
    """Start slab assembly for a graded card."""
    # Verify card exists and has a serial number
    card = db.query(CardRecord).filter(CardRecord.id == req.card_record_id).first()
    if not card:
        raise HTTPException(404, "Card record not found")
    if not card.serial_number:
        raise HTTPException(400, "Card has no serial number")

    # Check for approved grade
    grade_decision = (
        db.query(GradeDecision)
        .filter(GradeDecision.card_record_id == req.card_record_id)
        .filter(GradeDecision.status.in_(["approved", "overridden"]))
        .first()
    )
    if not grade_decision:
        raise HTTPException(400, "Card has no approved grade — approve grade first")

    # Check if assembly already exists
    existing = db.query(SlabAssembly).filter(
        SlabAssembly.card_record_id == req.card_record_id
    ).first()
    if existing:
        return _assembly_to_dict(existing, db)

    assembly = SlabAssembly(
        card_record_id=req.card_record_id,
        serial_number=card.serial_number,
        grade=grade_decision.final_grade,
        workflow_status="graded",
    )
    db.add(assembly)
    db.commit()
    db.refresh(assembly)

    event_bus.publish(Events.SLAB_ASSEMBLY_STARTED, {
        "assembly_id": assembly.id,
        "serial_number": card.serial_number,
    })

    return _assembly_to_dict(assembly, db)


@router.get("/queue")
async def list_assemblies(
    status: Optional[str] = None, db: Session = Depends(get_db)
):
    """List slab assemblies, optionally filtered by workflow status."""
    query = db.query(SlabAssembly).order_by(SlabAssembly.created_at.desc())
    if status:
        query = query.filter(SlabAssembly.workflow_status == status)
    assemblies = query.limit(100).all()
    return [_assembly_to_dict(a, db) for a in assemblies]


@router.get("/{assembly_id}")
async def get_assembly(assembly_id: str, db: Session = Depends(get_db)):
    """Get slab assembly status."""
    assembly = _get_assembly_or_404(assembly_id, db)
    return _assembly_to_dict(assembly, db)


@router.get("/printers/list")
async def list_printers():
    """List available printers."""
    printer = _get_printer()
    printers = await asyncio.to_thread(printer.list_printers)
    return {"printers": printers, "mock_mode": settings.printer.mock_mode}


@router.post("/{assembly_id}/print")
async def print_label(
    assembly_id: str, req: PrintRequest, db: Session = Depends(get_db)
):
    """Render and print the slab insert label."""
    assembly = _get_assembly_or_404(assembly_id, db)

    card = db.query(CardRecord).filter(CardRecord.id == assembly.card_record_id).first()
    if not card:
        raise HTTPException(404, "Card record not found")

    # Create print job record
    printer_name = req.printer_name or settings.printer.printer_name
    print_job = PrintJob(
        card_record_id=assembly.card_record_id,
        serial_number=assembly.serial_number,
        template_name=req.template_name,
        label_width_mm=settings.printer.label_width_mm,
        label_height_mm=settings.printer.label_height_mm,
        dpi=settings.printer.dpi,
        printer_name=printer_name,
        status="rendering",
    )
    db.add(print_job)
    db.commit()
    db.refresh(print_job)

    event_bus.publish(Events.PRINT_STARTED, {"job_id": print_job.id})

    try:
        # Render the label image
        from app.services.printer.renderer import render_label

        image_path = await asyncio.to_thread(
            render_label,
            serial_number=assembly.serial_number,
            grade=assembly.grade or 0.0,
            card_name=card.card_name or "Unknown Card",
            set_name=card.set_name or "",
            template_name=req.template_name,
            width_mm=settings.printer.label_width_mm,
            height_mm=settings.printer.label_height_mm,
            dpi=settings.printer.dpi,
        )

        # Print the image
        printer = _get_printer()
        result = await asyncio.to_thread(
            printer.print_image,
            image_path=image_path,
            printer_name=printer_name or "default",
            width_mm=settings.printer.label_width_mm,
            height_mm=settings.printer.label_height_mm,
            dpi=settings.printer.dpi,
        )

        # Update records
        print_job.image_path = image_path
        print_job.status = result.status
        print_job.error_message = result.error
        if result.status == "printed":
            print_job.printed_at = datetime.now(timezone.utc)
            assembly.print_job_id = print_job.id
            assembly.workflow_status = "insert_printed"
            event_bus.publish(Events.PRINT_COMPLETED, {"job_id": print_job.id})
        else:
            event_bus.publish(Events.PRINT_FAILED, {
                "job_id": print_job.id, "error": result.error,
            })

        db.commit()
        return _assembly_to_dict(assembly, db)

    except Exception as e:
        print_job.status = "failed"
        print_job.error_message = str(e)
        db.commit()
        event_bus.publish(Events.PRINT_FAILED, {"job_id": print_job.id, "error": str(e)})
        raise HTTPException(500, f"Print failed: {e}")


@router.get("/nfc/readers")
async def list_nfc_readers():
    """List available NFC readers."""
    nfc = _get_nfc_reader()
    readers = await asyncio.to_thread(nfc.list_readers)
    return {"readers": readers, "mock_mode": settings.nfc.mock_mode}


@router.get("/nfc/detect")
async def detect_nfc_tag():
    """Detect a tag on the NFC reader."""
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
        return {
            "detected": True,
            "uid": tag_info.uid,
            "tag_type": tag_info.tag_type,
            "atr": tag_info.atr,
        }
    return {"detected": False}


@router.post("/{assembly_id}/nfc/ntag213")
async def program_ntag213(
    assembly_id: str, req: NfcProgramRequest, db: Session = Depends(get_db)
):
    """Program an NTag213 with a verification URL."""
    assembly = _get_assembly_or_404(assembly_id, db)

    nfc_tag = NfcTag(
        card_record_id=assembly.card_record_id,
        serial_number=assembly.serial_number,
        tag_type="ntag213",
        status="programming",
    )
    db.add(nfc_tag)
    db.commit()
    db.refresh(nfc_tag)

    try:
        nfc = _get_nfc_reader()
        base_url = settings.nfc.verify_base_url

        if settings.nfc.mock_mode:
            result = nfc.program_ntag213(assembly.serial_number, base_url)
        else:
            from app.services.nfc.ntag213 import program_url

            info = await asyncio.to_thread(nfc.connect, req.reader_name or settings.nfc.reader_name)
            if not info.is_connected:
                raise RuntimeError("No NFC reader connected — place tag on reader and try again")
            result = await asyncio.to_thread(program_url, nfc, assembly.serial_number, base_url)
            nfc.disconnect()

        nfc_tag.tag_uid = result.tag_uid
        nfc_tag.ndef_url = result.ndef_url
        nfc_tag.status = result.status
        nfc_tag.error_message = result.error

        if result.status == "programmed":
            nfc_tag.programmed_at = datetime.now(timezone.utc)
            assembly.nfc_213_tag_id = nfc_tag.id
            # Advance workflow
            assembly.workflow_status = "nfc_programmed"
            event_bus.publish(Events.NFC_PROGRAMMED, {
                "tag_id": nfc_tag.id, "tag_type": "ntag213",
            })
        else:
            event_bus.publish(Events.NFC_FAILED, {
                "tag_id": nfc_tag.id, "error": result.error,
            })

        db.commit()
        return _assembly_to_dict(assembly, db)

    except Exception as e:
        nfc_tag.status = "failed"
        nfc_tag.error_message = str(e)
        db.commit()
        raise HTTPException(500, f"NTag213 programming failed: {e}")


@router.post("/{assembly_id}/nfc/ntag424")
async def program_ntag424(
    assembly_id: str, req: NfcProgramRequest, db: Session = Depends(get_db)
):
    """Program an NTag424 DNA with SUN/SDM secure URL."""
    assembly = _get_assembly_or_404(assembly_id, db)

    # Validate AES keys are configured
    if not settings.nfc.mock_mode:
        if not settings.nfc_master_key or not settings.nfc_sdm_file_read_key or not settings.nfc_sdm_meta_read_key:
            raise HTTPException(400, "NFC AES keys not configured — set RKT_NFC_MASTER_KEY, RKT_NFC_SDM_FILE_READ_KEY, RKT_NFC_SDM_META_READ_KEY in .env")

    nfc_tag = NfcTag(
        card_record_id=assembly.card_record_id,
        serial_number=assembly.serial_number,
        tag_type="ntag424_dna",
        status="programming",
    )
    db.add(nfc_tag)
    db.commit()
    db.refresh(nfc_tag)

    try:
        nfc = _get_nfc_reader()
        base_url = settings.nfc.verify_base_url

        if settings.nfc.mock_mode:
            result = nfc.program_ntag424(assembly.serial_number, base_url)
        else:
            from app.services.nfc.ntag424 import program_sdm

            master_key = bytes.fromhex(settings.nfc_master_key)
            sdm_file_read_key = bytes.fromhex(settings.nfc_sdm_file_read_key)
            sdm_meta_read_key = bytes.fromhex(settings.nfc_sdm_meta_read_key)

            info = await asyncio.to_thread(nfc.connect, req.reader_name or settings.nfc.reader_name)
            if not info.is_connected:
                raise RuntimeError("No NFC reader connected — place tag on reader and try again")
            result = await asyncio.to_thread(
                program_sdm, nfc, assembly.serial_number, base_url,
                master_key, sdm_file_read_key, sdm_meta_read_key,
            )
            nfc.disconnect()

        nfc_tag.tag_uid = result.tag_uid
        nfc_tag.ndef_url = result.ndef_url
        nfc_tag.sdm_configured = result.sdm_configured
        nfc_tag.status = result.status
        nfc_tag.error_message = result.error

        if result.status == "programmed":
            nfc_tag.programmed_at = datetime.now(timezone.utc)
            assembly.nfc_424_tag_id = nfc_tag.id
            # Advance workflow
            assembly.workflow_status = "nfc_programmed"
            event_bus.publish(Events.NFC_PROGRAMMED, {
                "tag_id": nfc_tag.id, "tag_type": "ntag424_dna",
            })
        else:
            event_bus.publish(Events.NFC_FAILED, {
                "tag_id": nfc_tag.id, "error": result.error,
            })

        db.commit()
        return _assembly_to_dict(assembly, db)

    except Exception as e:
        nfc_tag.status = "failed"
        nfc_tag.error_message = str(e)
        db.commit()
        raise HTTPException(500, f"NTag424 DNA programming failed: {e}")


@router.post("/{assembly_id}/complete")
async def complete_assembly(assembly_id: str, db: Session = Depends(get_db)):
    """Mark slab assembly as complete."""
    assembly = _get_assembly_or_404(assembly_id, db)

    if not assembly.nfc_213_tag_id and not assembly.nfc_424_tag_id:
        raise HTTPException(400, "NFC tag must be programmed before completing")

    assembly.workflow_status = "complete"
    assembly.completed_at = datetime.now(timezone.utc)
    db.commit()

    event_bus.publish(Events.SLAB_ASSEMBLY_COMPLETED, {
        "assembly_id": assembly.id,
        "serial_number": assembly.serial_number,
    })

    return _assembly_to_dict(assembly, db)


@router.post("/verify")
async def verify_nfc_tap(picc_data: str, cmac: str, db: Session = Depends(get_db)):
    """Verify an NTag424 DNA SUN tap (for future rktgrading.com backend)."""
    if not settings.nfc_sdm_file_read_key or not settings.nfc_sdm_meta_read_key:
        raise HTTPException(500, "SDM keys not configured")

    from app.services.nfc.crypto_nfc import verify_sdm_tag

    result = verify_sdm_tag(
        picc_data_hex=picc_data,
        cmac_hex=cmac,
        sdm_file_read_key=bytes.fromhex(settings.nfc_sdm_file_read_key),
        sdm_meta_read_key=bytes.fromhex(settings.nfc_sdm_meta_read_key),
    )

    if result["valid"] and result["uid"]:
        # Look up the card by NFC tag UID
        tag = db.query(NfcTag).filter(
            NfcTag.tag_uid == result["uid"],
            NfcTag.tag_type == "ntag424_dna",
        ).first()
        if tag:
            card = db.query(CardRecord).filter(CardRecord.id == tag.card_record_id).first()
            grade = db.query(GradeDecision).filter(
                GradeDecision.card_record_id == tag.card_record_id,
            ).first()
            result["card"] = {
                "serial_number": tag.serial_number,
                "card_name": card.card_name if card else None,
                "set_name": card.set_name if card else None,
                "grade": grade.final_grade if grade else None,
            }

    return result
