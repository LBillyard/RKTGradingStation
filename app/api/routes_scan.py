"""Scanning API routes."""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db

from app.services.reports.generator import AuditGenerator, AuditEventTypes, EntityTypes

logger = logging.getLogger(__name__)
router = APIRouter()
_audit = AuditGenerator()


async def _cache_pokewallet_reference(pokewallet_card_id: str, card_data: dict, db) -> None:
    """Cache PokeWallet card data + image in the reference library.

    Called after card identification — if the pokewallet_card_id is not already
    in our local reference library, create a ReferenceCard and download the
    image so we never need to fetch it again.
    """
    if not pokewallet_card_id:
        return

    from app.models.reference import ReferenceCard
    existing = db.query(ReferenceCard).filter(
        ReferenceCard.pokewallet_card_id == pokewallet_card_id
    ).first()
    if existing:
        logger.debug("Reference already cached for pokewallet_card_id=%s", pokewallet_card_id)
        return

    try:
        from app.services.reference_library.manager import ReferenceManager
        manager = ReferenceManager()
        ref_card = manager.add_card({
            "pokewallet_card_id": pokewallet_card_id,
            "card_name": card_data.get("card_name", "Unknown"),
            "set_name": card_data.get("set_name", ""),
            "set_code": card_data.get("set_code", ""),
            "collector_number": card_data.get("collector_number", ""),
            "rarity": card_data.get("rarity", ""),
            "language": card_data.get("language", "en"),
            "franchise": "pokemon",
        }, source="pokewallet", db=db)

        # Auto-approve since it comes from the official API
        manager.approve_card(ref_card.id, operator="auto_pokewallet", db=db)
        logger.info("Cached reference card %s for pokewallet_card_id=%s", ref_card.id, pokewallet_card_id)

        # Download image in background (don't block the scan flow)
        async def _download_bg():
            try:
                from app.services.reference_library.sync import PokeWalletSync
                sync = PokeWalletSync()
                downloaded = await sync.sync_card_images(ref_card.id)
                if downloaded:
                    logger.info("Downloaded %d reference image(s) for %s", downloaded, ref_card.id)
                await sync.close()
            except Exception as e:
                logger.warning("Background reference image download failed: %s", e)

        asyncio.create_task(_download_bg())

    except Exception as e:
        logger.warning("Failed to cache reference card: %s", e)


# Module-level scanner instance
_scanner = None


def _get_scanner():
    """Get or create the scanner instance based on settings."""
    global _scanner
    from app.config import settings
    if settings.scanner.mock_mode:
        if _scanner is None or _scanner.__class__.__name__ != "MockScanner":
            from app.services.scanner.mock_scanner import MockScanner
            _scanner = MockScanner(mock_dir=settings.scanner.mock_image_dir)
        return _scanner
    else:
        if _scanner is None or _scanner.__class__.__name__ != "WIAScanner":
            from app.services.scanner.wia_scanner import WIAScanner
            _scanner = WIAScanner()
        return _scanner


@router.post("/start")
async def start_scan_session(preset: str = "detailed", operator: str = "default", db: Session = Depends(get_db)):
    """Start a new scan session."""
    from app.models.scan import ScanSession
    session = ScanSession(scan_preset=preset, operator_name=operator, status="pending")
    db.add(session)
    db.commit()
    db.refresh(session)

    _audit.create_audit_event(
        AuditEventTypes.SCAN_STARTED, EntityTypes.SCAN, session.id,
        operator, {"preset": preset}, None, None, db,
    )

    return {"session_id": session.id, "status": session.status, "preset": session.scan_preset}


@router.post("/pipeline")
async def scan_to_slab_pipeline(
    preset: str = "detailed",
    operator: str = "default",
    profile: str = "standard",
    dpi: int = 600,
    db: Session = Depends(get_db),
):
    """One-click scan-to-slab pipeline.

    Chains the full workflow in a single call:
      1. Create scan session
      2. Acquire scan from hardware
      3. Vision pipeline (detect + correct card)
      4. OCR text extraction
      5. Card identification via PokeWallet
      6. Grading engine
      7. Authenticity check

    Each step is fault-tolerant — if a later step fails, earlier results
    are still returned.  Parameters mirror the individual endpoints:
      - preset: scan preset name (default "detailed")
      - operator: operator name (default "default")
      - profile: grading sensitivity profile (default "standard")
      - dpi: scanner DPI (default 600)
    """
    import cv2
    from app.models.scan import ScanSession, CardImage
    from app.models.card import CardRecord
    from app.config import settings

    results: dict = {"steps": [], "overall_status": "in_progress"}

    # ── Step 0: Create scan session ──────────────────────────────────────
    session = ScanSession(scan_preset=preset, operator_name=operator, status="scanning")
    db.add(session)
    db.commit()
    db.refresh(session)
    results["session_id"] = session.id

    _audit.create_audit_event(
        AuditEventTypes.SCAN_STARTED, EntityTypes.SCAN, session.id,
        operator, {"preset": preset, "pipeline": True}, None, None, db,
    )

    # ── Step 1: Acquire scan ─────────────────────────────────────────────
    front_image = None
    try:
        scanner = _get_scanner()
        if not scanner.is_connected():
            devices = scanner.list_devices()
            if not devices:
                raise RuntimeError("No scanner devices found")
            if not scanner.connect(devices[0].device_id):
                raise RuntimeError(f"Failed to connect to {devices[0].name}")

        scan_result = await asyncio.to_thread(scanner.scan, dpi=dpi)

        scan_dir = Path(settings.data_dir) / "scans" / session.id
        scan_dir.mkdir(parents=True, exist_ok=True)
        filename = f"front_{uuid.uuid4().hex[:8]}.png"
        file_path = scan_dir / filename
        scan_result.image.save(str(file_path), "PNG")
        file_size = file_path.stat().st_size

        front_image = CardImage(
            session_id=session.id,
            side="front",
            raw_path=str(file_path),
            dpi=dpi,
            width_px=scan_result.image.size[0],
            height_px=scan_result.image.size[1],
            file_size_bytes=file_size,
        )
        db.add(front_image)
        db.commit()
        db.refresh(front_image)

        results["steps"].append({
            "step": "acquire",
            "status": "ok",
            "image_id": front_image.id,
            "width": front_image.width_px,
            "height": front_image.height_px,
            "scan_time_ms": scan_result.scan_time_ms,
        })
    except Exception as e:
        logger.error("Pipeline acquire failed: %s", e)
        results["steps"].append({"step": "acquire", "status": "error", "error": str(e)})
        results["overall_status"] = "failed"
        session.status = "failed"
        db.commit()
        return results

    # ── Step 2: Vision pipeline ──────────────────────────────────────────
    processed = None
    try:
        from app.services.vision.pipeline import VisionPipeline
        pipeline = VisionPipeline(debug_dir=Path(settings.data_dir) / "debug")
        raw_img = cv2.imread(front_image.raw_path)
        if raw_img is None:
            raise ValueError(f"Failed to load image from {front_image.raw_path}")
        processed = await asyncio.to_thread(pipeline.process, raw_img, session.id, "front")

        if processed.corrected_image is not None:
            proc_dir = Path(settings.data_dir) / "scans" / session.id
            proc_dir.mkdir(parents=True, exist_ok=True)
            proc_filename = f"front_processed_{uuid.uuid4().hex[:8]}.png"
            proc_path = proc_dir / proc_filename
            cv2.imwrite(str(proc_path), processed.corrected_image)
            front_image.processed_path = str(proc_path)
            front_image.processing_status = "processed"
            db.commit()

        results["steps"].append({
            "step": "vision_pipeline",
            "status": "ok",
            "contour_found": processed.contour_found,
            "perspective_corrected": processed.perspective_corrected,
            "orientation_rotated": processed.orientation_rotated,
            "processing_time_ms": processed.processing_time_ms,
            "errors": processed.errors,
        })
    except Exception as e:
        logger.error("Pipeline vision failed: %s", e)
        results["steps"].append({"step": "vision_pipeline", "status": "error", "error": str(e)})

    # ── Step 3: OCR ──────────────────────────────────────────────────────
    ocr_engine = None
    parsed_fields = None
    try:
        from app.services.ocr.engine import OCREngine
        ocr_engine = OCREngine()
        if processed is not None and processed.corrected_image is not None:
            ocr_img = processed.corrected_image
        else:
            ocr_img = cv2.imread(front_image.raw_path)
            if ocr_img is None:
                raise ValueError("Failed to load image for OCR")
        ocr_result = await ocr_engine.recognize(ocr_img)

        ai_enhanced = False
        try:
            parsed_fields = await ocr_engine.parse_fields_with_ai(ocr_result, ocr_img)
            ai_enhanced = True
        except Exception:
            parsed_fields = ocr_engine.parse_fields(ocr_result)

        results["steps"].append({
            "step": "ocr",
            "status": "ok",
            "confidence": ocr_result.confidence if ocr_result else 0.0,
            "card_name": parsed_fields.card_name if parsed_fields else None,
            "collector_number": parsed_fields.collector_number if parsed_fields else None,
            "ai_enhanced": ai_enhanced,
        })
    except Exception as e:
        logger.error("Pipeline OCR failed: %s", e)
        results["steps"].append({"step": "ocr", "status": "error", "error": str(e)})

    # ── Step 4: Card identification ──────────────────────────────────────
    card_record = None
    try:
        from app.services.card_id.identifier import CardIdentifier
        from app.services.card_id.pokewallet import PokeWalletClient
        from app.services.ocr.engine import OCREngine as _OCREngine

        id_ocr_engine = ocr_engine if ocr_engine is not None else _OCREngine()
        pokewallet = PokeWalletClient(api_key=settings.pokewallet.api_key, base_url=settings.pokewallet.base_url)
        identifier = CardIdentifier(ocr_engine=id_ocr_engine, pokewallet=pokewallet)

        if processed is not None and processed.corrected_image is not None:
            front_img_for_id = processed.corrected_image
        else:
            front_img_for_id = cv2.imread(front_image.raw_path)

        id_result = await identifier.identify(front_image=front_img_for_id)

        best = id_result.best_match
        id_parsed = id_result.parsed_fields
        from app.utils.crypto import generate_serial_number

        card_record = CardRecord(
            session_id=session.id,
            front_image_id=front_image.id,
            pokewallet_card_id=best.card.id if best else None,
            card_name=(best.card.name if best else None) or (id_parsed.card_name if id_parsed else None) or "Unknown",
            set_name=(best.card.set_name if best else None) or "",
            set_code=best.card.set_code if best else "",
            collector_number=(best.card.card_number if best else None) or (id_parsed.collector_number if id_parsed else ""),
            rarity=(best.card.rarity if best else None) or (id_parsed.rarity if id_parsed else ""),
            card_type="Pokemon",
            hp=(best.card.hp if best else None) or (id_parsed.hp if id_parsed else ""),
            language=(id_parsed.language if id_parsed and id_parsed.language else None)
                     or (id_result.ocr_output.language if id_result.ocr_output else "en"),
            franchise="pokemon",
            identification_confidence=best.confidence if best else 0.0,
            identification_method="ocr_api" if id_result.status == "identified" else "ocr",
            serial_number=generate_serial_number(),
            status="identified" if id_result.status == "identified" else "pending_review",
        )
        db.add(card_record)
        db.commit()
        db.refresh(card_record)

        if best and best.card.id:
            await _cache_pokewallet_reference(best.card.id, {
                "card_name": card_record.card_name,
                "set_name": card_record.set_name,
                "set_code": card_record.set_code,
                "collector_number": card_record.collector_number,
                "rarity": card_record.rarity,
                "language": card_record.language,
            }, db)

        _audit.create_audit_event(
            AuditEventTypes.CARD_CREATED, EntityTypes.CARD, card_record.id,
            operator, {"card_name": card_record.card_name, "serial": card_record.serial_number, "pipeline": True},
            None, None, db,
        )

        results["steps"].append({
            "step": "card_identification",
            "status": "ok",
            "card_id": card_record.id,
            "card_name": card_record.card_name,
            "set_name": card_record.set_name,
            "confidence": card_record.identification_confidence,
            "serial": card_record.serial_number,
        })
    except Exception as e:
        logger.error("Pipeline card identification failed: %s", e)
        from app.utils.crypto import generate_serial_number
        card_record = CardRecord(
            session_id=session.id,
            front_image_id=front_image.id,
            card_name=parsed_fields.card_name if parsed_fields else "Unknown Card",
            collector_number=parsed_fields.collector_number if parsed_fields else "",
            hp=parsed_fields.hp if parsed_fields else "",
            language="en",
            franchise="pokemon",
            serial_number=generate_serial_number(),
            status="pending_review",
        )
        db.add(card_record)
        db.commit()
        db.refresh(card_record)

        _audit.create_audit_event(
            AuditEventTypes.CARD_CREATED, EntityTypes.CARD, card_record.id,
            operator, {"card_name": card_record.card_name, "serial": card_record.serial_number, "pipeline": True, "partial": True},
            None, None, db,
        )

        results["steps"].append({"step": "card_identification", "status": "partial", "error": str(e), "card_id": card_record.id})

    # ── Step 5: Grading ──────────────────────────────────────────────────
    grade_data = None
    try:
        # Note: grading proceeds even for unidentified cards — the vision-based
        # grading engine analyses centering, corners, edges, surface independently
        if card_record.card_name in ("Unknown", "Unknown Card", ""):
            logger.info("Card not identified — grading will proceed without card identity")

        from app.services.grading.engine import GradingEngine
        engine = GradingEngine(profile_name=profile)
        img_path = front_image.processed_path or front_image.raw_path
        grade_result = await engine.grade_card_for_record(card_record.id, img_path, profile=profile)

        final_grade = grade_result.get("final_grade") if isinstance(grade_result, dict) else getattr(grade_result, "final_grade", None)
        _audit.create_audit_event(
            AuditEventTypes.GRADE_APPROVED, EntityTypes.GRADE, card_record.id,
            operator, {"final_grade": final_grade, "auto": True, "pipeline": True},
            None, None, db,
        )

        grade_data = {
            "final_grade": final_grade,
            "sub_scores": grade_result.get("sub_scores") if isinstance(grade_result, dict) else None,
            "raw_score": grade_result.get("raw_score") if isinstance(grade_result, dict) else None,
            "defect_count": grade_result.get("defect_count", 0) if isinstance(grade_result, dict) else 0,
            "grading_confidence": grade_result.get("grading_confidence") if isinstance(grade_result, dict) else None,
        }
        results["steps"].append({"step": "grading", "status": "ok", **grade_data})
    except Exception as e:
        logger.error("Pipeline grading failed: %s", e)
        results["steps"].append({"step": "grading", "status": "error", "error": str(e)})

    # ── Step 6: Authenticity check ───────────────────────────────────────
    auth_data = None
    try:
        from app.services.authenticity.engine import AuthenticityEngine
        auth_engine = AuthenticityEngine()
        img_path = front_image.processed_path or front_image.raw_path
        auth_result = await auth_engine.check_authenticity(card_record.id, img_path)

        auth_status = auth_result.overall_status if hasattr(auth_result, "overall_status") else "unknown"
        auth_conf = auth_result.confidence if hasattr(auth_result, "confidence") else 0.0

        _audit.create_audit_event(
            AuditEventTypes.AUTH_DECIDED, EntityTypes.AUTHENTICITY, card_record.id,
            operator, {"status": auth_status, "confidence": auth_conf, "pipeline": True},
            None, None, db,
        )

        auth_data = {
            "decision": auth_status,
            "confidence": auth_conf,
            "checks_passed": auth_result.checks_passed if hasattr(auth_result, "checks_passed") else 0,
            "checks_failed": auth_result.checks_failed if hasattr(auth_result, "checks_failed") else 0,
            "recommendation": auth_result.recommendation if hasattr(auth_result, "recommendation") else "",
        }
        results["steps"].append({"step": "authenticity", "status": "ok", **auth_data})
    except Exception as e:
        logger.error("Pipeline authenticity failed: %s", e)
        results["steps"].append({"step": "authenticity", "status": "error", "error": str(e)})

    # ── Finalize ─────────────────────────────────────────────────────────
    session.status = "completed"
    session.completed_at = datetime.now(timezone.utc)
    card_record.status = "graded"
    db.commit()

    _audit.create_audit_event(
        AuditEventTypes.SCAN_COMPLETED, EntityTypes.SCAN, session.id,
        operator, {"card_id": card_record.id, "pipeline": True},
        None, None, db,
    )

    # Build summary response
    results["overall_status"] = "completed"
    results["card_id"] = card_record.id
    results["serial"] = card_record.serial_number
    results["card_name"] = card_record.card_name

    results["summary"] = {
        "card_name": card_record.card_name,
        "set_name": card_record.set_name or "",
        "serial": card_record.serial_number,
        "grade": grade_data.get("final_grade") if grade_data else None,
        "grading_confidence": grade_data.get("grading_confidence") if grade_data else None,
        "authenticity": auth_data.get("decision") if auth_data else None,
        "auth_confidence": auth_data.get("confidence") if auth_data else None,
    }

    return results


@router.post("/{session_id}/batch")
async def batch_scan(session_id: str, dpi: int = 600, db: Session = Depends(get_db)):
    """Batch scan mode: acquire one full-bed image, detect all cards, process each.

    Acquires a single scan from the scanner hardware, runs multi-card
    detection via the vision pipeline, and for each detected card creates
    a separate CardImage, CardRecord, and auto-queues identification +
    grading.

    Returns a list of all detected card records with their IDs, grades,
    and identification results.
    """
    import cv2
    from app.models.scan import ScanSession, CardImage
    from app.models.card import CardRecord
    from app.config import settings

    session = db.query(ScanSession).filter(ScanSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Scan session not found")

    # ── Step 1: Acquire full-bed scan ────────────────────────────────────
    scanner = _get_scanner()
    if not scanner.is_connected():
        devices = scanner.list_devices()
        if not devices:
            raise HTTPException(status_code=503, detail="No scanner devices found")
        if not scanner.connect(devices[0].device_id):
            raise HTTPException(status_code=503, detail=f"Failed to connect to {devices[0].name}")

    try:
        scan_result = await asyncio.to_thread(scanner.scan, dpi=dpi)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Batch scan failed: {str(e)}")

    # Save the full-bed image
    scan_dir = Path(settings.data_dir) / "scans" / session_id
    scan_dir.mkdir(parents=True, exist_ok=True)
    bed_filename = f"fullbed_{uuid.uuid4().hex[:8]}.png"
    bed_path = scan_dir / bed_filename
    scan_result.image.save(str(bed_path), "PNG")

    bed_image = CardImage(
        session_id=session_id,
        side="front",
        raw_path=str(bed_path),
        dpi=dpi,
        width_px=scan_result.image.size[0],
        height_px=scan_result.image.size[1],
        file_size_bytes=bed_path.stat().st_size,
    )
    db.add(bed_image)
    db.commit()
    db.refresh(bed_image)

    # ── Step 2: Multi-card detection + vision processing ─────────────────
    raw_img = cv2.imread(str(bed_path))
    if raw_img is None:
        raise HTTPException(status_code=500, detail="Failed to load scanned image")

    from app.services.vision.pipeline import VisionPipeline
    pipeline = VisionPipeline(debug_dir=Path(settings.data_dir) / "debug")
    processed_cards = await asyncio.to_thread(pipeline.process_multi, raw_img, session_id, "front")

    card_count = len(processed_cards)
    response_cards = []

    # ── Step 3: Process each detected card ───────────────────────────────
    for i, processed in enumerate(processed_cards):
        card_result = {"card_index": i, "steps": []}

        # Save individual card image and create CardImage record
        proc_dir = Path(settings.data_dir) / "scans" / session_id
        proc_filename = f"front_card{i}_{uuid.uuid4().hex[:8]}.png"
        proc_path = proc_dir / proc_filename
        card_image_id = bed_image.id

        if processed.corrected_image is not None:
            cv2.imwrite(str(proc_path), processed.corrected_image)
            h, w = processed.corrected_image.shape[:2]
            card_img_record = CardImage(
                session_id=session_id,
                side="front",
                raw_path=str(proc_path),
                processed_path=str(proc_path),
                processing_status="processed",
                width_px=w,
                height_px=h,
                file_size_bytes=proc_path.stat().st_size,
            )
            db.add(card_img_record)
            db.commit()
            db.refresh(card_img_record)
            card_image_id = card_img_record.id

        card_result["steps"].append({
            "step": "vision_pipeline",
            "status": "ok" if processed.contour_found else "partial",
            "contour_found": processed.contour_found,
            "perspective_corrected": processed.perspective_corrected,
            "orientation_rotated": processed.orientation_rotated,
            "errors": processed.errors,
        })

        # OCR
        ocr_img = processed.corrected_image if processed.corrected_image is not None else raw_img
        parsed_fields = None
        ocr_engine = None
        try:
            from app.services.ocr.engine import OCREngine
            ocr_engine = OCREngine()
            ocr_result = await ocr_engine.recognize(ocr_img)
            try:
                parsed_fields = await ocr_engine.parse_fields_with_ai(ocr_result, ocr_img)
            except Exception:
                parsed_fields = ocr_engine.parse_fields(ocr_result)

            card_result["steps"].append({
                "step": "ocr", "status": "ok",
                "card_name": parsed_fields.card_name if parsed_fields else None,
                "confidence": ocr_result.confidence if ocr_result else 0.0,
            })
        except Exception as e:
            card_result["steps"].append({"step": "ocr", "status": "error", "error": str(e)})

        # Card identification
        card_record = None
        try:
            from app.services.card_id.identifier import CardIdentifier
            from app.services.card_id.pokewallet import PokeWalletClient

            id_ocr = ocr_engine if ocr_engine is not None else OCREngine()
            pokewallet = PokeWalletClient(api_key=settings.pokewallet.api_key, base_url=settings.pokewallet.base_url)
            identifier = CardIdentifier(ocr_engine=id_ocr, pokewallet=pokewallet)
            id_result = await identifier.identify(front_image=ocr_img)

            best = id_result.best_match
            id_parsed = id_result.parsed_fields
            from app.utils.crypto import generate_serial_number

            card_record = CardRecord(
                session_id=session_id,
                front_image_id=card_image_id,
                pokewallet_card_id=best.card.id if best else None,
                card_name=(best.card.name if best else None) or (id_parsed.card_name if id_parsed else None) or "Unknown",
                set_name=(best.card.set_name if best else None) or "",
                set_code=best.card.set_code if best else "",
                collector_number=(best.card.card_number if best else None) or (id_parsed.collector_number if id_parsed else ""),
                rarity=(best.card.rarity if best else None) or (id_parsed.rarity if id_parsed else ""),
                card_type="Pokemon",
                hp=(best.card.hp if best else None) or (id_parsed.hp if id_parsed else ""),
                language=(id_parsed.language if id_parsed and id_parsed.language else None)
                         or (id_result.ocr_output.language if id_result.ocr_output else "en"),
                franchise="pokemon",
                identification_confidence=best.confidence if best else 0.0,
                identification_method="ocr_api" if id_result.status == "identified" else "ocr",
                serial_number=generate_serial_number(),
                status="identified" if id_result.status == "identified" else "pending_review",
            )
            db.add(card_record)
            db.commit()
            db.refresh(card_record)

            if best and best.card.id:
                await _cache_pokewallet_reference(best.card.id, {
                    "card_name": card_record.card_name,
                    "set_name": card_record.set_name,
                    "set_code": card_record.set_code,
                    "collector_number": card_record.collector_number,
                    "rarity": card_record.rarity,
                    "language": card_record.language,
                }, db)

            _audit.create_audit_event(
                AuditEventTypes.CARD_CREATED, EntityTypes.CARD, card_record.id,
                session.operator_name,
                {"card_name": card_record.card_name, "serial": card_record.serial_number, "card_index": i, "batch": True},
                None, None, db,
            )

            card_result["steps"].append({
                "step": "card_identification", "status": "ok",
                "card_id": card_record.id,
                "card_name": card_record.card_name,
                "confidence": card_record.identification_confidence,
                "serial": card_record.serial_number,
            })
        except Exception as e:
            from app.utils.crypto import generate_serial_number
            card_record = CardRecord(
                session_id=session_id,
                front_image_id=card_image_id,
                card_name=parsed_fields.card_name if parsed_fields else "Unknown Card",
                serial_number=generate_serial_number(),
                status="pending_review",
            )
            db.add(card_record)
            db.commit()
            db.refresh(card_record)

            _audit.create_audit_event(
                AuditEventTypes.CARD_CREATED, EntityTypes.CARD, card_record.id,
                session.operator_name,
                {"card_name": card_record.card_name, "card_index": i, "batch": True, "partial": True},
                None, None, db,
            )

            card_result["steps"].append({"step": "card_identification", "status": "partial", "error": str(e), "card_id": card_record.id})

        # Grading
        try:
            # Gate: skip grading if card identification failed
            if card_record.card_name in ("Unknown", "Unknown Card", ""):
                card_record.status = "identification_failed"
                db.commit()
                raise RuntimeError("Card identification failed — manual review required")

            from app.services.grading.engine import GradingEngine
            engine = GradingEngine()
            grade_result = await engine.grade_card_for_record(card_record.id, str(proc_path))
            batch_final_grade = grade_result.get("final_grade") if isinstance(grade_result, dict) else None
            _audit.create_audit_event(
                AuditEventTypes.GRADE_APPROVED, EntityTypes.GRADE, card_record.id,
                session.operator_name,
                {"final_grade": batch_final_grade, "auto": True, "card_index": i, "batch": True},
                None, None, db,
            )

            card_result["steps"].append({
                "step": "grading", "status": "ok",
                "final_grade": batch_final_grade,
                "defect_count": grade_result.get("defect_count", 0) if isinstance(grade_result, dict) else 0,
            })
        except Exception as e:
            card_result["steps"].append({"step": "grading", "status": "error", "error": str(e)})

        card_record.status = card_record.status if card_record.status == "identification_failed" else "graded"
        db.commit()

        card_result["card_id"] = card_record.id
        card_result["card_name"] = card_record.card_name
        card_result["serial"] = card_record.serial_number
        response_cards.append(card_result)

    # ── Finalize session ─────────────────────────────────────────────────
    session.status = "completed"
    session.completed_at = datetime.now(timezone.utc)
    db.commit()

    _audit.create_audit_event(
        AuditEventTypes.SCAN_COMPLETED, EntityTypes.SCAN, session_id,
        session.operator_name, {"card_count": card_count, "batch": True},
        None, None, db,
    )

    return {
        "session_id": session_id,
        "card_count": card_count,
        "scan_time_ms": scan_result.scan_time_ms,
        "bed_image_id": bed_image.id,
        "cards": response_cards,
        "overall_status": "completed",
    }


@router.post("/{session_id}/acquire")
async def acquire_scan(session_id: str, side: str = "front", dpi: int = 600, db: Session = Depends(get_db)):
    """Acquire an image from the scanner hardware."""
    if side not in ALLOWED_SIDES:
        raise HTTPException(status_code=400, detail=f"Invalid side '{side}'. Must be one of: {', '.join(sorted(ALLOWED_SIDES))}")

    from app.models.scan import ScanSession, CardImage
    from app.config import settings

    session = db.query(ScanSession).filter(ScanSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Scan session not found")

    scanner = _get_scanner()

    # Connect to first available device if not connected
    if not scanner.is_connected():
        devices = scanner.list_devices()
        if not devices:
            raise HTTPException(status_code=503, detail="No scanner devices found")
        connected = scanner.connect(devices[0].device_id)
        if not connected:
            raise HTTPException(status_code=503, detail=f"Failed to connect to {devices[0].name}")

    # Run scan in thread to avoid blocking
    try:
        scan_result = await asyncio.to_thread(scanner.scan, dpi=dpi)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Scan failed: {str(e)}")

    # Save scanned image
    scan_dir = Path(settings.data_dir) / "scans" / session_id
    scan_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{side}_{uuid.uuid4().hex[:8]}.png"
    file_path = scan_dir / filename
    scan_result.image.save(str(file_path), "PNG")
    file_size = file_path.stat().st_size

    image = CardImage(
        session_id=session_id,
        side=side,
        raw_path=str(file_path),
        dpi=dpi,
        width_px=scan_result.image.size[0],
        height_px=scan_result.image.size[1],
        file_size_bytes=file_size,
    )
    db.add(image)
    db.commit()
    db.refresh(image)

    logger.info(f"Scan acquired: {image.width_px}x{image.height_px} @ {dpi}dpi, saved to {file_path}")

    return {
        "image_id": image.id,
        "side": side,
        "path": str(file_path),
        "width": image.width_px,
        "height": image.height_px,
        "dpi": dpi,
        "size_bytes": file_size,
        "scan_time_ms": scan_result.scan_time_ms,
    }


ALLOWED_SIDES = {"front", "back"}
ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp"}
MAX_UPLOAD_SIZE_BYTES = 100 * 1024 * 1024  # 100 MB


@router.post("/{session_id}/upload")
async def upload_scan_image(session_id: str, side: str = "front", file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Upload a card image for a scan session."""
    if side not in ALLOWED_SIDES:
        raise HTTPException(status_code=400, detail=f"Invalid side '{side}'. Must be one of: {', '.join(sorted(ALLOWED_SIDES))}")

    from app.models.scan import ScanSession, CardImage
    from app.config import settings

    session = db.query(ScanSession).filter(ScanSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Scan session not found")

    # Validate file extension
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"File type '{ext}' not allowed. Accepted types: {', '.join(sorted(ALLOWED_IMAGE_EXTENSIONS))}"
        )

    # Validate MIME type
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid MIME type '{file.content_type}'. Only image files are accepted."
        )

    content = await file.read()

    # Validate file size
    if len(content) > MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({len(content)} bytes). Maximum allowed size is {MAX_UPLOAD_SIZE_BYTES} bytes (100 MB)."
        )

    scan_dir = Path(settings.data_dir) / "scans" / session_id
    scan_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{side}_{uuid.uuid4().hex[:8]}{ext}"
    file_path = scan_dir / filename

    with open(file_path, "wb") as f:
        f.write(content)

    image = CardImage(
        session_id=session_id,
        side=side,
        raw_path=str(file_path),
        file_size_bytes=len(content),
    )
    db.add(image)
    db.commit()
    db.refresh(image)

    return {"image_id": image.id, "side": side, "path": str(file_path), "size_bytes": len(content)}


@router.post("/{session_id}/process")
async def process_scan_session(session_id: str, force_multi: bool = False, db: Session = Depends(get_db)):
    """Run the full pipeline: vision → OCR → card ID → grading → authenticity.

    Automatically detects multiple cards on the scanner bed and delegates
    to the multi-card pipeline when 2+ cards are found.
    """
    from app.models.scan import ScanSession, CardImage
    from app.models.card import CardRecord
    from app.config import settings

    session = db.query(ScanSession).filter(ScanSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Scan session not found")

    front_image = db.query(CardImage).filter(
        CardImage.session_id == session_id, CardImage.side == "front"
    ).first()
    if not front_image:
        raise HTTPException(status_code=400, detail="No front image found. Scan or upload a front image first.")

    import cv2

    # ── Auto-detect multiple cards on scanner bed ──
    raw_img = cv2.imread(front_image.raw_path)
    if raw_img is None:
        raise HTTPException(status_code=500, detail=f"Failed to load image from {front_image.raw_path}")

    if force_multi:
        logger.info("Force multi-card mode requested for session %s", session_id)
        multi_result = await process_multi_scan(session_id, db)
        multi_result["auto_multi"] = True
        multi_result["force_multi"] = True
        return multi_result

    try:
        from app.services.vision.contour import ContourDetector
        detector = ContourDetector()
        detected_cards = await asyncio.to_thread(detector.detect_all, raw_img)
        detected_count = len(detected_cards)
        logger.info("Auto-detection found %d card(s) in session %s", detected_count, session_id)
    except Exception as e:
        logger.warning("Auto-detection failed, proceeding as single card: %s", e)
        detected_count = 1

    if detected_count >= 2:
        logger.info("Multiple cards detected (%d), auto-switching to multi-card pipeline", detected_count)
        multi_result = await process_multi_scan(session_id, db)
        multi_result["auto_multi"] = True
        return multi_result

    # ── Single card processing ──
    results = {"session_id": session_id, "steps": [], "detected_card_count": detected_count}
    processed = None  # Will hold VisionPipeline result if Step 1 succeeds
    ocr_engine = None  # Will hold OCREngine instance if Step 2 succeeds

    # Step 1: Vision pipeline
    try:
        from app.services.vision.pipeline import VisionPipeline
        pipeline = VisionPipeline(debug_dir=Path(settings.data_dir) / "debug")
        processed = await asyncio.to_thread(pipeline.process, raw_img, session_id, "front")

        # Save the corrected image as the processed file
        if processed.corrected_image is not None:
            proc_dir = Path(settings.data_dir) / "scans" / session_id
            proc_dir.mkdir(parents=True, exist_ok=True)
            proc_filename = f"front_processed_{uuid.uuid4().hex[:8]}.png"
            proc_path = proc_dir / proc_filename
            cv2.imwrite(str(proc_path), processed.corrected_image)
            front_image.processed_path = str(proc_path)
            front_image.processing_status = "processed"
            db.commit()

        results["steps"].append({
            "step": "vision_pipeline",
            "status": "ok",
            "debug_dir": processed.debug_dir,
            "contour_found": processed.contour_found,
            "perspective_corrected": processed.perspective_corrected,
            "orientation_rotated": processed.orientation_rotated,
            "has_borders": processed.borders is not None,
            "regions_extracted": sum(1 for attr in ['corner_tl', 'corner_tr', 'corner_br', 'corner_bl',
                'edge_top', 'edge_bottom', 'edge_left', 'edge_right', 'surface']
                if processed.regions and getattr(processed.regions, attr, None) is not None),
            "errors": processed.errors,
            "processing_time_ms": processed.processing_time_ms,
        })
    except Exception as e:
        logger.error(f"Vision pipeline failed: {e}")
        results["steps"].append({"step": "vision_pipeline", "status": "error", "error": str(e)})

    # Step 2: OCR
    ocr_text = ""
    ocr_result = None
    parsed_fields = None
    try:
        from app.services.ocr.engine import OCREngine
        ocr_engine = OCREngine()
        # Prefer the corrected image from the vision pipeline; fall back to raw file
        if processed is not None and processed.corrected_image is not None:
            ocr_img = processed.corrected_image
        else:
            ocr_img = cv2.imread(front_image.raw_path)
            if ocr_img is None:
                raise ValueError(f"Failed to load image for OCR from {front_image.raw_path}")
        ocr_result = await ocr_engine.recognize(ocr_img)

        ocr_text = ocr_result.raw_text if ocr_result else ""

        # Use AI-enhanced parsing if enabled, else regex
        ai_enhanced = False
        try:
            parsed_fields = await ocr_engine.parse_fields_with_ai(ocr_result, ocr_img)
            ai_enhanced = True
        except Exception:
            parsed_fields = ocr_engine.parse_fields(ocr_result)

        results["steps"].append({
            "step": "ocr",
            "status": "ok",
            "engine": ocr_result.engine if ocr_result else "none",
            "confidence": ocr_result.confidence if ocr_result else 0.0,
            "text_length": len(ocr_text),
            "card_name": parsed_fields.card_name if parsed_fields else None,
            "collector_number": parsed_fields.collector_number if parsed_fields else None,
            "ai_enhanced": ai_enhanced,
        })
    except Exception as e:
        logger.error(f"OCR failed: {e}")
        results["steps"].append({"step": "ocr", "status": "error", "error": str(e)})

    # Step 3: Card identification
    card_record = None
    try:
        from app.services.card_id.identifier import CardIdentifier
        from app.services.card_id.pokewallet import PokeWalletClient
        from app.services.ocr.engine import OCREngine as _OCREngine

        id_ocr_engine = ocr_engine if ocr_engine is not None else _OCREngine()
        pokewallet = PokeWalletClient(api_key=settings.pokewallet.api_key, base_url=settings.pokewallet.base_url)
        identifier = CardIdentifier(ocr_engine=id_ocr_engine, pokewallet=pokewallet)

        # CardIdentifier.identify() expects numpy image arrays; prefer corrected image
        if processed is not None and processed.corrected_image is not None:
            front_img_for_id = processed.corrected_image
        else:
            front_img_for_id = cv2.imread(front_image.raw_path)

        back_image_record = db.query(CardImage).filter(
            CardImage.session_id == session_id, CardImage.side == "back"
        ).first()
        back_img_for_id = None
        if back_image_record:
            back_img_for_id = cv2.imread(back_image_record.raw_path)

        id_result = await identifier.identify(
            front_image=front_img_for_id,
            back_image=back_img_for_id,
        )

        # Extract fields from the IdentificationResult dataclass
        best = id_result.best_match
        id_parsed = id_result.parsed_fields
        id_confidence = best.confidence if best else 0.0

        from app.utils.crypto import generate_serial_number
        card_record = CardRecord(
            session_id=session_id,
            front_image_id=front_image.id,
            pokewallet_card_id=best.card.id if best else None,
            card_name=(best.card.name if best else None) or (id_parsed.card_name if id_parsed else None) or "Unknown",
            set_name=(best.card.set_name if best else None) or "",
            set_code=best.card.set_code if best else "",
            collector_number=(best.card.card_number if best else None) or (id_parsed.collector_number if id_parsed else ""),
            rarity=(best.card.rarity if best else None) or (id_parsed.rarity if id_parsed else ""),
            card_type="Pokemon",
            hp=(best.card.hp if best else None) or (id_parsed.hp if id_parsed else ""),
            language=(id_parsed.language if id_parsed and id_parsed.language else None)
                     or (id_result.ocr_output.language if id_result.ocr_output else "en"),
            franchise="pokemon",
            identification_confidence=id_confidence,
            identification_method="ocr_api" if id_result.status == "identified" else "ocr",
            serial_number=generate_serial_number(),
            status="identified" if id_result.status == "identified" else "pending_review",
        )
        db.add(card_record)
        db.commit()
        db.refresh(card_record)

        # Cache PokeWallet card data + image in reference library
        if best and best.card.id:
            await _cache_pokewallet_reference(best.card.id, {
                "card_name": card_record.card_name,
                "set_name": card_record.set_name,
                "set_code": card_record.set_code,
                "collector_number": card_record.collector_number,
                "rarity": card_record.rarity,
                "language": card_record.language,
            }, db)

        _audit.create_audit_event(
            AuditEventTypes.CARD_CREATED, EntityTypes.CARD, card_record.id,
            session.operator_name, {"card_name": card_record.card_name, "serial": card_record.serial_number},
            None, None, db,
        )

        results["steps"].append({
            "step": "card_identification",
            "status": "ok",
            "identification_status": id_result.status,
            "card_id": card_record.id,
            "card_name": card_record.card_name,
            "set_name": card_record.set_name,
            "confidence": card_record.identification_confidence,
            "serial": card_record.serial_number,
            "requires_manual_review": id_result.requires_manual_review,
            "alternatives_count": len(id_result.alternatives),
        })
    except Exception as e:
        logger.error(f"Card identification failed: {e}")
        # Create card record with just OCR data
        from app.utils.crypto import generate_serial_number
        card_record = CardRecord(
            session_id=session_id,
            front_image_id=front_image.id,
            card_name=parsed_fields.card_name if parsed_fields else "Unknown Card",
            collector_number=parsed_fields.collector_number if parsed_fields else "",
            hp=parsed_fields.hp if parsed_fields else "",
            language="en",
            franchise="pokemon",
            serial_number=generate_serial_number(),
            status="pending_review",
        )
        db.add(card_record)
        db.commit()
        db.refresh(card_record)

        _audit.create_audit_event(
            AuditEventTypes.CARD_CREATED, EntityTypes.CARD, card_record.id,
            session.operator_name, {"card_name": card_record.card_name, "serial": card_record.serial_number, "partial": True},
            None, None, db,
        )

        results["steps"].append({"step": "card_identification", "status": "partial", "error": str(e), "card_id": card_record.id})

    # Step 4: Grading
    try:
        # Gate: skip grading only if card name is truly unknown
        if card_record.card_name in ("Unknown", "Unknown Card", ""):
            card_record.status = "identification_failed"
            db.commit()
            raise RuntimeError("Card identification failed — manual review required")

        from app.services.grading.engine import GradingEngine
        engine = GradingEngine()
        img_path = front_image.processed_path or front_image.raw_path
        grade_result = await engine.grade_card_for_record(card_record.id, img_path)

        final_grade = grade_result.get("final_grade") if isinstance(grade_result, dict) else getattr(grade_result, "final_grade", None)
        _audit.create_audit_event(
            AuditEventTypes.GRADE_APPROVED, EntityTypes.GRADE, card_record.id,
            session.operator_name, {"final_grade": final_grade, "auto": True},
            None, None, db,
        )

        results["steps"].append({
            "step": "grading",
            "status": "ok",
            "final_grade": final_grade,
            "sub_scores": grade_result.get("sub_scores") if isinstance(grade_result, dict) else None,
            "defect_count": grade_result.get("defect_count", 0) if isinstance(grade_result, dict) else 0,
        })
    except Exception as e:
        logger.error(f"Grading failed: {e}")
        results["steps"].append({"step": "grading", "status": "error", "error": str(e)})

    # Step 4b: AI grade review
    ai_review = None
    try:
        from app.services.ai.grade_advisor import get_grade_review
        from app.models.grading import GradeDecision as GradeDecisionModel

        grade_step = next((s for s in results["steps"] if s["step"] == "grading" and s["status"] == "ok"), None)
        if grade_step and card_record:
            grade_decision = db.query(GradeDecisionModel).filter(
                GradeDecisionModel.card_record_id == card_record.id
            ).first()

            if grade_decision:
                # Load image for AI review
                review_img = cv2.imread(front_image.processed_path or front_image.raw_path)
                if review_img is not None:
                    grade_data_for_ai = {
                        "final_grade": grade_decision.final_grade,
                        "centering_score": grade_decision.centering_score,
                        "corners_score": grade_decision.corners_score,
                        "edges_score": grade_decision.edges_score,
                        "surface_score": grade_decision.surface_score,
                        "centering_ratio_lr": grade_decision.centering_ratio_lr,
                        "centering_ratio_tb": grade_decision.centering_ratio_tb,
                        "defect_count": grade_decision.defect_count,
                        "defects": [],
                    }
                    review = await get_grade_review(review_img, grade_data_for_ai)
                    if review:
                        ai_review = review.to_dict()
                        grade_decision.ai_review_json = ai_review
                        db.commit()
                        results["steps"].append({
                            "step": "ai_review",
                            "status": "ok",
                            "agrees_with_grade": review.agrees_with_grade,
                            "suggested_grade": review.suggested_grade,
                            "confidence": review.confidence,
                            "assessment": review.overall_assessment,
                        })
    except Exception as e:
        logger.warning("AI grade review failed: %s", e)
        results["steps"].append({"step": "ai_review", "status": "skipped", "reason": str(e)})

    # Step 5: Authenticity check
    try:
        from app.services.authenticity.engine import AuthenticityEngine
        auth_engine = AuthenticityEngine()
        img_path = front_image.processed_path or front_image.raw_path
        auth_result = await auth_engine.check_authenticity(card_record.id, img_path)

        auth_status = auth_result.status if hasattr(auth_result, "status") else auth_result.get("status", "unknown") if isinstance(auth_result, dict) else "unknown"
        auth_conf = auth_result.confidence if hasattr(auth_result, "confidence") else auth_result.get("confidence", 0) if isinstance(auth_result, dict) else 0

        _audit.create_audit_event(
            AuditEventTypes.AUTH_DECIDED, EntityTypes.AUTHENTICITY, card_record.id,
            session.operator_name, {"status": auth_status, "confidence": auth_conf},
            None, None, db,
        )

        results["steps"].append({
            "step": "authenticity",
            "status": "ok",
            "decision": auth_status,
            "confidence": auth_conf,
        })
    except Exception as e:
        logger.error(f"Authenticity check failed: {e}")
        results["steps"].append({"step": "authenticity", "status": "error", "error": str(e)})

    # Update session status
    session.status = "completed"
    session.completed_at = datetime.now(timezone.utc)
    db.commit()

    card_record.status = "graded"
    db.commit()

    _audit.create_audit_event(
        AuditEventTypes.SCAN_COMPLETED, EntityTypes.SCAN, session_id,
        session.operator_name, {"card_id": card_record.id if card_record else None},
        None, None, db,
    )

    results["card_id"] = card_record.id if card_record else None
    results["overall_status"] = "completed"
    if ai_review:
        results["ai_review"] = ai_review

    return results


@router.post("/{session_id}/process-multi")
async def process_multi_scan(session_id: str, db: Session = Depends(get_db)):
    """Detect multiple cards from a single scan and process each individually."""
    from app.models.scan import ScanSession, CardImage
    from app.models.card import CardRecord
    from app.config import settings

    session = db.query(ScanSession).filter(ScanSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Scan session not found")

    front_image = db.query(CardImage).filter(
        CardImage.session_id == session_id, CardImage.side == "front"
    ).first()
    if not front_image:
        raise HTTPException(status_code=400, detail="No front image found.")

    import cv2

    raw_img = cv2.imread(front_image.raw_path)
    if raw_img is None:
        raise HTTPException(status_code=500, detail="Failed to load image")

    # Step 1: Detect and process all cards
    from app.services.vision.pipeline import VisionPipeline
    pipeline = VisionPipeline(debug_dir=Path(settings.data_dir) / "debug")
    processed_cards = await asyncio.to_thread(pipeline.process_multi, raw_img, session_id, "front")

    card_count = len(processed_cards)
    response_cards = []

    for i, processed in enumerate(processed_cards):
        card_result = {"card_index": i, "steps": []}

        # Save processed image and create individual CardImage record
        proc_dir = Path(settings.data_dir) / "scans" / session_id
        proc_dir.mkdir(parents=True, exist_ok=True)
        proc_filename = f"front_card{i}_{uuid.uuid4().hex[:8]}.png"
        proc_path = proc_dir / proc_filename
        card_image_id = front_image.id  # default to full-bed
        if processed.corrected_image is not None:
            cv2.imwrite(str(proc_path), processed.corrected_image)
            h, w = processed.corrected_image.shape[:2]
            card_img_record = CardImage(
                session_id=session_id,
                side="front",
                raw_path=str(proc_path),
                processed_path=str(proc_path),
                processing_status="processed",
                width_px=w,
                height_px=h,
                file_size_bytes=proc_path.stat().st_size,
            )
            db.add(card_img_record)
            db.commit()
            db.refresh(card_img_record)
            card_image_id = card_img_record.id

        card_result["steps"].append({
            "step": "vision_pipeline",
            "status": "ok" if processed.contour_found else "partial",
            "contour_found": processed.contour_found,
            "perspective_corrected": processed.perspective_corrected,
            "orientation_rotated": processed.orientation_rotated,
            "errors": processed.errors,
        })

        # OCR
        ocr_img = processed.corrected_image if processed.corrected_image is not None else raw_img
        parsed_fields = None
        try:
            from app.services.ocr.engine import OCREngine
            ocr_engine = OCREngine()
            ocr_result = await ocr_engine.recognize(ocr_img)
            try:
                parsed_fields = await ocr_engine.parse_fields_with_ai(ocr_result, ocr_img)
            except Exception:
                parsed_fields = ocr_engine.parse_fields(ocr_result)

            card_result["steps"].append({
                "step": "ocr", "status": "ok",
                "card_name": parsed_fields.card_name if parsed_fields else None,
                "confidence": ocr_result.confidence if ocr_result else 0.0,
            })
        except Exception as e:
            card_result["steps"].append({"step": "ocr", "status": "error", "error": str(e)})

        # Card identification
        card_record = None
        try:
            from app.services.card_id.identifier import CardIdentifier
            from app.services.card_id.pokewallet import PokeWalletClient

            pokewallet = PokeWalletClient(api_key=settings.pokewallet.api_key, base_url=settings.pokewallet.base_url)
            identifier = CardIdentifier(ocr_engine=ocr_engine, pokewallet=pokewallet)
            id_result = await identifier.identify(front_image=ocr_img)

            best = id_result.best_match
            id_parsed = id_result.parsed_fields
            from app.utils.crypto import generate_serial_number

            card_record = CardRecord(
                session_id=session_id,
                front_image_id=card_image_id,
                pokewallet_card_id=best.card.id if best else None,
                card_name=(best.card.name if best else None) or (id_parsed.card_name if id_parsed else None) or "Unknown",
                set_name=(best.card.set_name if best else None) or "",
                set_code=best.card.set_code if best else "",
                collector_number=(best.card.card_number if best else None) or (id_parsed.collector_number if id_parsed else ""),
                rarity=(best.card.rarity if best else None) or (id_parsed.rarity if id_parsed else ""),
                card_type="Pokemon",
                hp=(best.card.hp if best else None) or (id_parsed.hp if id_parsed else ""),
                language=(id_parsed.language if id_parsed and id_parsed.language else None)
                         or (id_result.ocr_output.language if id_result.ocr_output else "en"),
                franchise="pokemon",
                identification_confidence=best.confidence if best else 0.0,
                identification_method="ocr_api" if id_result.status == "identified" else "ocr",
                serial_number=generate_serial_number(),
                status="identified" if id_result.status == "identified" else "pending_review",
            )
            db.add(card_record)
            db.commit()
            db.refresh(card_record)

            # Cache PokeWallet card data + image in reference library
            if best and best.card.id:
                await _cache_pokewallet_reference(best.card.id, {
                    "card_name": card_record.card_name,
                    "set_name": card_record.set_name,
                    "set_code": card_record.set_code,
                    "collector_number": card_record.collector_number,
                    "rarity": card_record.rarity,
                    "language": card_record.language,
                }, db)

            _audit.create_audit_event(
                AuditEventTypes.CARD_CREATED, EntityTypes.CARD, card_record.id,
                session.operator_name, {"card_name": card_record.card_name, "serial": card_record.serial_number, "card_index": i},
                None, None, db,
            )

            card_result["steps"].append({
                "step": "card_identification", "status": "ok",
                "card_id": card_record.id,
                "card_name": card_record.card_name,
                "confidence": card_record.identification_confidence,
                "serial": card_record.serial_number,
            })
        except Exception as e:
            from app.utils.crypto import generate_serial_number
            card_record = CardRecord(
                session_id=session_id,
                front_image_id=card_image_id,
                card_name=parsed_fields.card_name if parsed_fields else "Unknown Card",
                serial_number=generate_serial_number(),
                status="pending_review",
            )
            db.add(card_record)
            db.commit()
            db.refresh(card_record)

            _audit.create_audit_event(
                AuditEventTypes.CARD_CREATED, EntityTypes.CARD, card_record.id,
                session.operator_name, {"card_name": card_record.card_name, "card_index": i, "partial": True},
                None, None, db,
            )

            card_result["steps"].append({"step": "card_identification", "status": "partial", "error": str(e), "card_id": card_record.id})

        # Grading
        try:
            # Gate: skip grading if card identification failed
            if card_record.card_name in ("Unknown", "Unknown Card", ""):
                card_record.status = "identification_failed"
                db.commit()
                raise RuntimeError("Card identification failed — manual review required")

            from app.services.grading.engine import GradingEngine
            engine = GradingEngine()
            grade_result = await engine.grade_card_for_record(card_record.id, str(proc_path))
            multi_final_grade = grade_result.get("final_grade") if isinstance(grade_result, dict) else None
            _audit.create_audit_event(
                AuditEventTypes.GRADE_APPROVED, EntityTypes.GRADE, card_record.id,
                session.operator_name, {"final_grade": multi_final_grade, "auto": True, "card_index": i},
                None, None, db,
            )

            card_result["steps"].append({
                "step": "grading", "status": "ok",
                "final_grade": multi_final_grade,
                "defect_count": grade_result.get("defect_count", 0) if isinstance(grade_result, dict) else 0,
            })
        except Exception as e:
            card_result["steps"].append({"step": "grading", "status": "error", "error": str(e)})

        card_record.status = card_record.status if card_record.status == "identification_failed" else "graded"
        db.commit()

        card_result["card_id"] = card_record.id
        card_result["card_name"] = card_record.card_name
        card_result["serial"] = card_record.serial_number
        response_cards.append(card_result)

    session.status = "completed"
    session.completed_at = datetime.now(timezone.utc)
    db.commit()

    _audit.create_audit_event(
        AuditEventTypes.SCAN_COMPLETED, EntityTypes.SCAN, session_id,
        session.operator_name, {"card_count": card_count},
        None, None, db,
    )

    return {
        "session_id": session_id,
        "card_count": card_count,
        "cards": response_cards,
        "overall_status": "completed",
    }


@router.get("/devices/list")
async def list_scanner_devices():
    """List available scanner devices.

    When mock mode is enabled, still probes for real hardware scanners
    so the UI can show whether the physical scanner is available.
    """
    from app.config import settings

    real_devices = []
    # Always try to detect real WIA scanners
    try:
        from app.services.scanner.wia_scanner import WIAScanner
        real_scanner = WIAScanner()
        real_devices = [
            {"device_id": d.device_id, "name": d.name, "manufacturer": d.manufacturer, "connected": d.is_connected}
            for d in real_scanner.list_devices()
        ]
    except Exception as e:
        logger.debug(f"Real scanner probe failed: {e}")

    if settings.scanner.mock_mode:
        return {
            "mock_mode": True,
            "devices": [{"device_id": "mock_scanner", "name": "Mock Scanner (Development)", "connected": True}],
            "real_devices": real_devices,
        }

    if real_devices:
        return {"mock_mode": False, "devices": real_devices, "real_devices": real_devices}

    # No real devices found and not in mock mode
    return {"mock_mode": False, "devices": [], "real_devices": []}


@router.get("/presets/list")
async def list_scan_presets():
    """List available scan presets."""
    return {
        "presets": [
            {"id": "fast_production", "name": "Fast Production", "dpi": 300, "description": "Quick scan for high-volume grading"},
            {"id": "detailed", "name": "Detailed", "dpi": 600, "description": "Standard grading quality"},
            {"id": "authenticity", "name": "Authenticity Rescan", "dpi": 1200, "description": "High-res for authenticity analysis"},
            {"id": "back_quick", "name": "Back Quick", "dpi": 300, "description": "Quick back-side scan"},
        ]
    }


@router.post("/{card_id}/rescan")
async def rescan_card(card_id: str, dpi: int = 600, db: Session = Depends(get_db)):
    """Re-scan an existing card: re-acquire image, re-run vision + grading pipeline.

    Looks up the existing CardRecord, re-acquires a scan from the scanner
    hardware, replaces the front image, re-runs the vision pipeline and
    grading engine, and returns the new grade result.
    """
    from app.models.scan import ScanSession, CardImage
    from app.models.card import CardRecord
    from app.config import settings

    import cv2

    # 1. Look up the card record
    card = db.query(CardRecord).filter(CardRecord.id == card_id).first()
    if not card:
        raise HTTPException(status_code=404, detail="Card record not found")

    # 2. Get the scan session
    session = db.query(ScanSession).filter(ScanSession.id == card.session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Scan session not found for this card")

    # 3. Re-acquire the scan from the scanner hardware
    scanner = _get_scanner()

    if not scanner.is_connected():
        devices = scanner.list_devices()
        if not devices:
            raise HTTPException(status_code=503, detail="No scanner devices found")
        connected = scanner.connect(devices[0].device_id)
        if not connected:
            raise HTTPException(status_code=503, detail=f"Failed to connect to {devices[0].name}")

    try:
        scan_result = await asyncio.to_thread(scanner.scan, dpi=dpi)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Rescan failed: {str(e)}")

    # Save the new scanned image
    scan_dir = Path(settings.data_dir) / "scans" / card.session_id
    scan_dir.mkdir(parents=True, exist_ok=True)
    filename = f"front_rescan_{uuid.uuid4().hex[:8]}.png"
    file_path = scan_dir / filename
    scan_result.image.save(str(file_path), "PNG")
    file_size = file_path.stat().st_size

    # 4. Update or create the front CardImage record
    front_image = None
    if card.front_image_id:
        front_image = db.query(CardImage).filter(CardImage.id == card.front_image_id).first()

    if front_image:
        # Update existing image record with new scan
        front_image.raw_path = str(file_path)
        front_image.processed_path = None
        front_image.processing_status = "raw"
        front_image.dpi = dpi
        front_image.width_px = scan_result.image.size[0]
        front_image.height_px = scan_result.image.size[1]
        front_image.file_size_bytes = file_size
    else:
        # Create new image record
        front_image = CardImage(
            session_id=card.session_id,
            side="front",
            raw_path=str(file_path),
            dpi=dpi,
            width_px=scan_result.image.size[0],
            height_px=scan_result.image.size[1],
            file_size_bytes=file_size,
        )
        db.add(front_image)
        db.commit()
        db.refresh(front_image)
        card.front_image_id = front_image.id

    db.commit()

    logger.info(f"Rescan acquired for card {card_id}: {file_path}")

    results = {"card_id": card_id, "steps": []}

    # 5. Re-run the vision pipeline
    processed = None
    try:
        from app.services.vision.pipeline import VisionPipeline
        pipeline = VisionPipeline(debug_dir=Path(settings.data_dir) / "debug")
        raw_img = cv2.imread(front_image.raw_path)
        if raw_img is None:
            raise ValueError(f"Failed to load image from {front_image.raw_path}")
        processed = await asyncio.to_thread(pipeline.process, raw_img, card.session_id, "front")

        if processed.corrected_image is not None:
            proc_dir = Path(settings.data_dir) / "scans" / card.session_id
            proc_dir.mkdir(parents=True, exist_ok=True)
            proc_filename = f"front_rescan_processed_{uuid.uuid4().hex[:8]}.png"
            proc_path = proc_dir / proc_filename
            cv2.imwrite(str(proc_path), processed.corrected_image)
            front_image.processed_path = str(proc_path)
            front_image.processing_status = "processed"
            db.commit()

        results["steps"].append({
            "step": "vision_pipeline",
            "status": "ok",
            "contour_found": processed.contour_found,
            "perspective_corrected": processed.perspective_corrected,
            "orientation_rotated": processed.orientation_rotated,
            "processing_time_ms": processed.processing_time_ms,
        })
    except Exception as e:
        logger.error(f"Vision pipeline failed during rescan: {e}")
        results["steps"].append({"step": "vision_pipeline", "status": "error", "error": str(e)})

    # 6. Re-trigger grading via the GradingEngine
    try:
        from app.services.grading.engine import GradingEngine
        engine = GradingEngine()
        img_path = front_image.processed_path or front_image.raw_path
        grade_result = await engine.grade_card_for_record(card_id, img_path)

        final_grade = grade_result.get("final_grade") if isinstance(grade_result, dict) else getattr(grade_result, "final_grade", None)

        _audit.create_audit_event(
            AuditEventTypes.GRADE_APPROVED, EntityTypes.GRADE, card_id,
            session.operator_name, {"final_grade": final_grade, "auto": True, "rescan": True},
            None, None, db,
        )

        results["steps"].append({
            "step": "grading",
            "status": "ok",
            "final_grade": final_grade,
            "raw_score": grade_result.get("raw_score") if isinstance(grade_result, dict) else None,
            "sub_scores": grade_result.get("sub_scores") if isinstance(grade_result, dict) else None,
            "defect_count": grade_result.get("defect_count", 0) if isinstance(grade_result, dict) else 0,
        })
    except Exception as e:
        logger.error(f"Grading failed during rescan: {e}")
        results["steps"].append({"step": "grading", "status": "error", "error": str(e)})

    # Update card status
    card.status = "graded"
    db.commit()

    _audit.create_audit_event(
        AuditEventTypes.SCAN_COMPLETED, EntityTypes.SCAN, card.session_id,
        session.operator_name, {"card_id": card_id, "rescan": True},
        None, None, db,
    )

    results["overall_status"] = "completed"
    results["scan_path"] = str(file_path)
    results["scan_time_ms"] = scan_result.scan_time_ms

    return results


@router.get("/{session_id}")
async def get_scan_session(session_id: str, db: Session = Depends(get_db)):
    """Get scan session details."""
    from app.models.scan import ScanSession
    session = db.query(ScanSession).filter(ScanSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Scan session not found")
    return {
        "id": session.id,
        "status": session.status,
        "preset": session.scan_preset,
        "operator": session.operator_name,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "completed_at": session.completed_at.isoformat() if session.completed_at else None,
        "images": [
            {"id": img.id, "side": img.side, "raw_path": img.raw_path, "processed_path": img.processed_path,
             "width": img.width_px, "height": img.height_px, "dpi": img.dpi}
            for img in session.images
        ],
    }


@router.get("/recent/list")
async def list_recent_scans(limit: int = 20, db: Session = Depends(get_db)):
    """List recent scan sessions."""
    from app.models.scan import ScanSession
    sessions = db.query(ScanSession).order_by(ScanSession.created_at.desc()).limit(limit).all()
    return [
        {
            "id": s.id,
            "status": s.status,
            "preset": s.scan_preset,
            "operator": s.operator_name,
            "image_count": len(s.images),
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in sessions
    ]
