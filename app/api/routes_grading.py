"""Grading API routes."""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload, selectinload

from app.db.database import get_db
from app.utils.validation import VALID_GRADES, validate_grade
from app.services.reports.generator import AuditGenerator, AuditEventTypes, EntityTypes

logger = logging.getLogger(__name__)
router = APIRouter()
_audit = AuditGenerator()


def _safe_int(val):
    """Convert a value to int, handling numpy ints and raw bytes from SQLite."""
    if val is None:
        return None
    if isinstance(val, bytes):
        import struct
        return struct.unpack('<i', val)[0]
    return int(val)


# ----- Request / Response Models -----

class GradeRunRequest(BaseModel):
    """Request body for triggering a grading run."""
    profile: str = Field(default="standard", description="Sensitivity profile name")


class GradeOverrideRequest(BaseModel):
    """Request body for overriding a grade."""
    grade: float = Field(..., description="New grade (1.0-10.0 in 0.5 steps)")
    reason: str = Field(..., min_length=5, description="Mandatory override reason")
    operator: str = Field(default="default", description="Operator identifier")


class GradeApproveRequest(BaseModel):
    """Request body for approving a grade."""
    operator: str = Field(default="default", description="Operator identifier")


# ----- Endpoints -----

# Static routes MUST be defined before parameterised /{card_id} routes
# to prevent "profiles" from being captured as a card_id.

@router.get("/profiles/list")
async def list_profiles():
    """List all available sensitivity profiles."""
    from app.services.grading.profiles import list_profiles as get_profiles
    return {"profiles": get_profiles()}


def _image_url(db, image_id):
    """Convert a CardImage ID to a /data/-relative URL."""
    if not image_id:
        return None
    from app.models.scan import CardImage
    img = db.query(CardImage).filter(CardImage.id == image_id).first()
    if not img:
        return None
    path = (img.processed_path or img.raw_path or "").replace("\\", "/")
    idx = path.find("data/")
    return "/" + path[idx:] if idx >= 0 else None


@router.get("/history/{card_id}")
async def get_grade_history(card_id: str, db: Session = Depends(get_db)):
    """Get grade history for a card."""
    from app.models.grading import GradeHistory
    history = db.query(GradeHistory).filter(
        GradeHistory.card_record_id == card_id
    ).order_by(GradeHistory.graded_at.desc()).all()
    return {
        "card_id": card_id,
        "count": len(history),
        "history": [
            {
                "id": h.id,
                "centering_score": h.centering_score,
                "corners_score": h.corners_score,
                "edges_score": h.edges_score,
                "surface_score": h.surface_score,
                "raw_grade": h.raw_grade,
                "final_grade": h.final_grade,
                "sensitivity_profile": h.sensitivity_profile,
                "defect_count": h.defect_count,
                "grade_caps": h.grade_caps_json,
                "graded_at": h.graded_at.isoformat() if h.graded_at else None,
            }
            for h in history
        ],
    }


@router.get("/population/{pokewallet_card_id}")
async def get_population(pokewallet_card_id: str, db: Session = Depends(get_db)):
    """Get grade distribution for all cards matching a pokewallet_card_id."""
    from app.models.card import CardRecord
    from app.models.grading import GradeDecision
    from sqlalchemy import func

    results = (
        db.query(GradeDecision.final_grade, func.count(GradeDecision.id))
        .join(CardRecord, CardRecord.id == GradeDecision.card_record_id)
        .filter(CardRecord.pokewallet_card_id == pokewallet_card_id)
        .filter(GradeDecision.status.in_(["graded", "approved", "overridden"]))
        .group_by(GradeDecision.final_grade)
        .order_by(GradeDecision.final_grade.desc())
        .all()
    )

    distribution = {str(grade): count for grade, count in results}
    total = sum(count for _, count in results)

    return {
        "pokewallet_card_id": pokewallet_card_id,
        "total_graded": total,
        "distribution": distribution,
    }


@router.get("/{card_id}")
async def get_grade_decision(card_id: str, db: Session = Depends(get_db)):
    """Get grade decision for a card, including all defect findings."""
    from app.models.grading import GradeDecision, DefectFinding
    from app.models.card import CardRecord

    # Single joined query for decision + card (avoids N+1)
    row = (
        db.query(GradeDecision, CardRecord)
        .outerjoin(CardRecord, CardRecord.id == GradeDecision.card_record_id)
        .filter(GradeDecision.card_record_id == card_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Grade decision not found")
    decision, card = row

    defects = db.query(DefectFinding).filter(
        DefectFinding.card_record_id == card_id
    ).all()

    return {
        "id": decision.id,
        "card_record_id": decision.card_record_id,
        "card_name": card.card_name if card else None,
        "language": card.language if card else None,
        "set_name": card.set_name if card else None,
        "set_code": card.set_code if card else None,
        "collector_number": card.collector_number if card else None,
        "rarity": card.rarity if card else None,
        "card_type": card.card_type if card else None,
        "serial_number": card.serial_number if card else None,
        "franchise": card.franchise if card else None,
        "hp": card.hp if card else None,
        "pokewallet_card_id": card.pokewallet_card_id if card else None,
        "front_image_url": _image_url(db, card.front_image_id) if card else None,
        "back_image_url": _image_url(db, card.back_image_id) if card else None,
        "centering_score": decision.centering_score,
        "corners_score": decision.corners_score,
        "edges_score": decision.edges_score,
        "surface_score": decision.surface_score,
        "raw_grade": decision.raw_grade,
        "final_grade": decision.final_grade,
        "auto_grade": decision.auto_grade,
        "centering_ratio_lr": decision.centering_ratio_lr,
        "centering_ratio_tb": decision.centering_ratio_tb,
        "grade_caps": decision.grade_caps_json,
        "sensitivity_profile": decision.sensitivity_profile,
        "status": decision.status,
        "override_grade": decision.operator_override_grade,
        "override_reason": decision.override_reason,
        "graded_by": decision.graded_by,
        "approved_at": decision.approved_at.isoformat() if decision.approved_at else None,
        "defect_count": decision.defect_count,
        "grading_confidence": decision.grading_confidence,
        "ai_review": decision.ai_review_json,
        "grading_method": (decision.ai_review_json or {}).get("grading_method", "opencv"),
        "grade_explanation": (decision.ai_review_json or {}).get("grade_explanation", ""),
        "ai_model": (decision.ai_review_json or {}).get("ai_model"),
        "centering_details": (decision.ai_review_json or {}).get("centering_details", {}),
        "created_at": decision.created_at.isoformat() if decision.created_at else None,
        "updated_at": decision.updated_at.isoformat() if decision.updated_at else None,
        "defects": [
            {
                "id": d.id,
                "category": d.category,
                "defect_type": d.defect_type,
                "severity": d.severity,
                "location": d.location_description,
                "side": d.side,
                "bbox": {
                    "x": _safe_int(d.bbox_x),
                    "y": _safe_int(d.bbox_y),
                    "w": _safe_int(d.bbox_w),
                    "h": _safe_int(d.bbox_h),
                } if d.bbox_x is not None else None,
                "confidence": d.confidence,
                "score_impact": d.score_impact,
                "is_noise": d.is_noise,
                "details": d.details_json,
            }
            for d in defects
        ],
    }


@router.post("/{card_id}/run")
async def run_grading(card_id: str, req: GradeRunRequest = None, db: Session = Depends(get_db)):
    """Trigger grading analysis for a card.

    Loads the card's front image, runs the full grading pipeline,
    and stores the results.
    """
    from app.models.card import CardRecord
    from app.models.scan import CardImage
    from app.services.grading.engine import GradingEngine

    if req is None:
        req = GradeRunRequest()

    # Look up the card record
    card = db.query(CardRecord).filter(CardRecord.id == card_id).first()
    if not card:
        raise HTTPException(status_code=404, detail="Card record not found")

    # Get the front image path
    image_path = None
    if card.front_image_id:
        image = db.query(CardImage).filter(CardImage.id == card.front_image_id).first()
        if image:
            image_path = image.processed_path or image.raw_path

    if not image_path:
        raise HTTPException(
            status_code=400,
            detail="Card has no front image. Scan the card first.",
        )

    # Look up reference image for artwork comparison
    reference_path = None
    if card.pokewallet_card_id:
        from app.models.reference import ReferenceCard, ReferenceImage
        ref_card = db.query(ReferenceCard).filter(
            ReferenceCard.pokewallet_card_id == card.pokewallet_card_id
        ).first()
        if ref_card:
            ref_img = db.query(ReferenceImage).filter(
                ReferenceImage.reference_card_id == ref_card.id,
                ReferenceImage.side == "front",
            ).first()
            if ref_img and ref_img.image_path:
                from pathlib import Path as _P
                if _P(ref_img.image_path).exists():
                    reference_path = ref_img.image_path
                    logger.info("Using reference image for grading: %s", reference_path)

    # If no reference image yet, try to fetch it synchronously (5s timeout)
    if reference_path is None and card.pokewallet_card_id:
        try:
            import asyncio
            from app.models.reference import ReferenceCard, ReferenceImage
            from app.services.reference_library.sync import PokeWalletSync

            ref_card = db.query(ReferenceCard).filter(
                ReferenceCard.pokewallet_card_id == card.pokewallet_card_id
            ).first()
            if ref_card:
                sync = PokeWalletSync()
                try:
                    downloaded = await asyncio.wait_for(
                        sync.sync_card_images(ref_card.id), timeout=5.0
                    )
                    if downloaded:
                        ref_img = db.query(ReferenceImage).filter(
                            ReferenceImage.reference_card_id == ref_card.id,
                            ReferenceImage.side == "front",
                        ).first()
                        if ref_img and ref_img.image_path:
                            from pathlib import Path as _P
                            if _P(ref_img.image_path).exists():
                                reference_path = ref_img.image_path
                                logger.info("Pre-fetched reference image: %s", reference_path)
                finally:
                    await sync.close()
        except asyncio.TimeoutError:
            logger.warning("Reference image pre-fetch timed out for %s", card.pokewallet_card_id)
        except Exception as e:
            logger.warning("Reference image pre-fetch failed: %s", e)

    # Run the grading engine
    try:
        engine = GradingEngine(profile_name=req.profile)
        result = await engine.grade_card_for_record(
            card_id, image_path, profile=req.profile,
            reference_image_path=reference_path,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Grading failed for card %s", card_id)
        raise HTTPException(status_code=500, detail=f"Grading failed: {str(e)}")

    # Auto-trigger authenticity check after successful grading
    auth_status = None
    auth_confidence = None
    try:
        from app.services.authenticity.engine import AuthenticityEngine
        auth_engine = AuthenticityEngine()
        auth_result = await auth_engine.check_authenticity(card_id, image_path)

        if hasattr(auth_result, "overall_status"):
            auth_status = auth_result.overall_status
            auth_confidence = auth_result.confidence
        elif isinstance(auth_result, dict):
            auth_status = auth_result.get("overall_status") or auth_result.get("status")
            auth_confidence = auth_result.get("confidence")
    except Exception as e:
        logger.warning("Authenticity check failed after grading for card %s: %s", card_id, e)
        # auth_status and auth_confidence remain None — grading response is not broken

    return {
        "status": "graded",
        "card_id": card_id,
        "final_grade": result["final_grade"],
        "raw_score": result["raw_score"],
        "sub_scores": result["sub_scores"],
        "defect_count": result["defect_count"],
        "profile": result["sensitivity_profile"],
        "grading_confidence": result.get("grading_confidence"),
        "auth_status": auth_status,
        "auth_confidence": auth_confidence,
    }


@router.post("/{card_id}/approve")
async def approve_grade(card_id: str, req: GradeApproveRequest = None, db: Session = Depends(get_db)):
    """Approve the auto-grade for a card.

    Sets the grade decision status to 'approved' and records the operator.
    """
    from app.models.grading import GradeDecision
    from app.core.events import Events, event_bus

    if req is None:
        req = GradeApproveRequest()

    decision = db.query(GradeDecision).filter(
        GradeDecision.card_record_id == card_id
    ).first()
    if not decision:
        raise HTTPException(status_code=404, detail="Grade decision not found")

    if decision.status == "approved":
        raise HTTPException(status_code=400, detail="Grade is already approved")

    decision.status = "approved"
    decision.graded_by = req.operator
    decision.approved_at = datetime.now(timezone.utc)
    db.commit()

    _audit.create_audit_event(
        AuditEventTypes.GRADE_APPROVED, EntityTypes.GRADE, card_id,
        req.operator, {"final_grade": decision.final_grade},
        None, {"status": "approved"}, db,
    )

    event_bus.publish(Events.GRADE_APPROVED, {
        "card_id": card_id,
        "final_grade": decision.final_grade,
        "operator": req.operator,
    })

    return {
        "status": "approved",
        "card_id": card_id,
        "final_grade": decision.final_grade,
        "approved_at": decision.approved_at.isoformat(),
    }


@router.post("/{card_id}/override")
async def override_grade(card_id: str, req: GradeOverrideRequest, db: Session = Depends(get_db)):
    """Override the auto-grade with a manual grade and reason.

    The new grade must be a valid 0.5-increment value between 1.0 and 10.0.
    A reason of at least 5 characters is required.
    """
    from app.models.grading import GradeDecision
    from app.core.events import Events, event_bus

    # Validate grade
    if not validate_grade(req.grade):
        raise HTTPException(
            status_code=400,
            detail=f"Grade must be one of: {VALID_GRADES}",
        )

    if not req.reason or len(req.reason.strip()) < 5:
        raise HTTPException(
            status_code=400,
            detail="Override reason is required (minimum 5 characters)",
        )

    decision = db.query(GradeDecision).filter(
        GradeDecision.card_record_id == card_id
    ).first()
    if not decision:
        raise HTTPException(status_code=404, detail="Grade decision not found")

    before_grade = decision.final_grade
    decision.operator_override_grade = req.grade
    decision.override_reason = req.reason.strip()
    decision.status = "overridden"
    decision.graded_by = req.operator
    decision.approved_at = datetime.now(timezone.utc)
    db.commit()

    _audit.create_audit_event(
        AuditEventTypes.GRADE_OVERRIDDEN, EntityTypes.GRADE, card_id,
        req.operator, {"reason": req.reason.strip()},
        {"grade": before_grade}, {"grade": req.grade}, db,
    )

    event_bus.publish(Events.GRADE_OVERRIDDEN, {
        "card_id": card_id,
        "original_grade": decision.auto_grade,
        "override_grade": req.grade,
        "reason": req.reason.strip(),
        "operator": req.operator,
    })

    return {
        "status": "overridden",
        "card_id": card_id,
        "original_grade": decision.auto_grade,
        "final_grade": req.grade,
        "reason": req.reason.strip(),
    }


@router.get("/{card_id}/defects")
async def get_defects(card_id: str, include_noise: bool = False, db: Session = Depends(get_db)):
    """Get defect findings for a card.

    Args:
        card_id: Card record ID.
        include_noise: If True, include defects marked as noise.
    """
    from app.models.grading import DefectFinding

    query = db.query(DefectFinding).filter(DefectFinding.card_record_id == card_id)

    if not include_noise:
        query = query.filter(DefectFinding.is_noise == False)  # noqa: E712

    defects = query.all()

    return {
        "card_id": card_id,
        "count": len(defects),
        "defects": [
            {
                "id": d.id,
                "category": d.category,
                "defect_type": d.defect_type,
                "severity": d.severity,
                "location": d.location_description,
                "side": d.side,
                "bbox": {
                    "x": _safe_int(d.bbox_x),
                    "y": _safe_int(d.bbox_y),
                    "w": _safe_int(d.bbox_w),
                    "h": _safe_int(d.bbox_h),
                } if d.bbox_x is not None else None,
                "confidence": d.confidence,
                "score_impact": d.score_impact,
                "is_noise": d.is_noise,
                "details": d.details_json,
            }
            for d in defects
        ],
    }
