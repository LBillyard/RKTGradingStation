"""Authenticity review API routes.

Provides endpoints for running authenticity checks, querying results,
overriding decisions, and listing configured rules.
"""

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.services.reports.generator import AuditGenerator, AuditEventTypes, EntityTypes

logger = logging.getLogger(__name__)
router = APIRouter()
_audit = AuditGenerator()


# ============================================================================
# Request / Response Models
# ============================================================================

class AuthOverrideRequest(BaseModel):
    """Request body for overriding an authenticity decision."""
    status: str = Field(..., description="New status: authentic, suspect, or reject")
    reason: str = Field(..., min_length=1, description="Mandatory reason for override")
    operator: str = Field(..., min_length=1, description="Name of the operator performing override")


class AuthRunRequest(BaseModel):
    """Optional request body for triggering an authenticity check."""
    reference_image_path: Optional[str] = None
    card_type: Optional[str] = None


# ============================================================================
# Endpoints
# ============================================================================

# NOTE: Static routes MUST come before /{card_id} to avoid FastAPI matching
# "rules" as a card_id parameter.

@router.get("/rules/list")
async def list_rules(card_type: Optional[str] = None):
    """List configured authenticity rules, optionally adjusted for a card type."""
    from app.services.authenticity.rules import get_rules

    rules = get_rules(card_type)
    return {
        "card_type": card_type,
        "rules": [r.to_dict() for r in rules],
        "total": len(rules),
    }


@router.get("/{card_id}")
async def get_authenticity_decision(card_id: str, db: Session = Depends(get_db)):
    """Get the authenticity decision and all check results for a card."""
    from app.models.authenticity import AuthenticityDecision, AuthenticityCheck

    decision = (
        db.query(AuthenticityDecision)
        .filter(AuthenticityDecision.card_record_id == card_id)
        .first()
    )
    if not decision:
        raise HTTPException(status_code=404, detail="Authenticity decision not found")

    checks = (
        db.query(AuthenticityCheck)
        .filter(AuthenticityCheck.card_record_id == card_id)
        .order_by(AuthenticityCheck.created_at)
        .all()
    )

    return {
        "id": decision.id,
        "card_id": card_id,
        "overall_status": decision.operator_override_status or decision.overall_status,
        "original_status": decision.overall_status,
        "confidence": decision.confidence,
        "checks_passed": decision.checks_passed,
        "checks_failed": decision.checks_failed,
        "checks_total": decision.checks_total,
        "flags": decision.flags_json.get("flags", []) if decision.flags_json else [],
        "operator_override": decision.operator_override_status,
        "override_reason": decision.override_reason,
        "reviewed_by": decision.reviewed_by,
        "reviewed_at": decision.reviewed_at.isoformat() if decision.reviewed_at else None,
        "created_at": decision.created_at.isoformat() if decision.created_at else None,
        "checks": [
            {
                "id": c.id,
                "check_type": c.check_type,
                "passed": c.passed,
                "confidence": c.confidence,
                "details": c.details,
                "error_message": c.error_message,
                "processing_time_ms": c.processing_time_ms,
            }
            for c in checks
        ],
    }


@router.post("/{card_id}/run")
async def run_authenticity_check(card_id: str, body: AuthRunRequest = None,
                                 db: Session = Depends(get_db)):
    """Trigger an authenticity check for a card.

    Loads the card record, finds its scanned image, gathers any available
    reference data, and runs the full authenticity engine pipeline.
    """
    from app.models.card import CardRecord
    from app.models.scan import CardImage

    card = db.query(CardRecord).filter(CardRecord.id == card_id).first()
    if not card:
        raise HTTPException(status_code=404, detail="Card record not found")

    # Find the card's front image path
    image_path = None
    if card.front_image_id:
        card_image = db.query(CardImage).filter(CardImage.id == card.front_image_id).first()
        if card_image:
            # Prefer processed path, fall back to raw scan path
            image_path = card_image.processed_path or card_image.raw_path

    if not image_path or not Path(image_path).exists():
        raise HTTPException(
            status_code=400,
            detail="Card does not have a valid front image for authenticity analysis",
        )

    # Gather reference data from the card record
    reference_data = {
        "card_name": card.card_name,
        "hp": card.hp,
        "collector_number": card.collector_number,
        "card_type": card.card_type,
    }

    # Include body overrides if provided
    if body:
        if body.reference_image_path:
            reference_data["reference_image_path"] = body.reference_image_path
        if body.card_type:
            reference_data["card_type"] = body.card_type

    # Try to find OCR results for text checks
    try:
        from app.models.ocr import OCRResult
        ocr_record = (
            db.query(OCRResult)
            .filter(OCRResult.card_record_id == card_id)
            .order_by(OCRResult.created_at.desc())
            .first()
        )
        if ocr_record:
            reference_data["ocr_results"] = {
                "raw_text": ocr_record.raw_text or "",
                "confidence": ocr_record.confidence_score or 0.0,
                "card_name": card.card_name,
                "hp": card.hp,
                "collector_number": card.collector_number,
            }
    except Exception as e:
        logger.warning(f"Could not load OCR results for card {card_id}: {e}")

    # Try to find reference image from reference library
    if "reference_image_path" not in reference_data and card.pokewallet_card_id:
        try:
            from app.models.reference import ReferenceCard, ReferenceImage
            ref_card = (
                db.query(ReferenceCard)
                .filter(ReferenceCard.pokewallet_card_id == card.pokewallet_card_id)
                .first()
            )
            if ref_card:
                ref_img = (
                    db.query(ReferenceImage)
                    .filter(
                        ReferenceImage.reference_card_id == ref_card.id,
                        ReferenceImage.side == "front",
                    )
                    .first()
                )
                if ref_img and ref_img.image_path and Path(ref_img.image_path).exists():
                    reference_data["reference_image_path"] = ref_img.image_path
        except Exception as e:
            logger.debug(f"Reference library lookup skipped: {e}")

    # Run the engine
    from app.services.authenticity.engine import AuthenticityEngine
    engine = AuthenticityEngine()

    try:
        result = await engine.check_authenticity(
            card_id=card_id,
            card_image_path=image_path,
            reference_data=reference_data,
        )
    except Exception as e:
        logger.error(f"Authenticity engine error for card {card_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Authenticity check failed: {e}")

    return result.to_dict()


@router.post("/{card_id}/override")
async def override_authenticity(card_id: str, req: AuthOverrideRequest,
                                db: Session = Depends(get_db)):
    """Override an authenticity decision with operator judgment."""
    from app.models.authenticity import AuthenticityDecision

    decision = (
        db.query(AuthenticityDecision)
        .filter(AuthenticityDecision.card_record_id == card_id)
        .first()
    )
    if not decision:
        raise HTTPException(status_code=404, detail="Authenticity decision not found")

    valid_statuses = ("authentic", "suspect", "reject")
    if req.status not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Status must be one of: {', '.join(valid_statuses)}",
        )

    original_status = decision.overall_status
    decision.operator_override_status = req.status
    decision.override_reason = req.reason
    decision.reviewed_by = req.operator
    decision.reviewed_at = datetime.now(timezone.utc)
    db.commit()

    _audit.create_audit_event(
        AuditEventTypes.AUTH_OVERRIDDEN, EntityTypes.AUTHENTICITY, card_id,
        req.operator, {"reason": req.reason},
        {"status": original_status}, {"status": req.status}, db,
    )

    logger.info(
        f"[{card_id}] Authenticity overridden to '{req.status}' by {req.operator}: {req.reason}"
    )

    return {
        "card_id": card_id,
        "status": req.status,
        "reason": req.reason,
        "reviewed_by": req.operator,
        "reviewed_at": decision.reviewed_at.isoformat(),
    }


@router.get("/{card_id}/checks")
async def get_authenticity_checks(card_id: str, db: Session = Depends(get_db)):
    """Get individual check results for a card."""
    from app.models.authenticity import AuthenticityCheck

    checks = (
        db.query(AuthenticityCheck)
        .filter(AuthenticityCheck.card_record_id == card_id)
        .order_by(AuthenticityCheck.created_at)
        .all()
    )

    if not checks:
        raise HTTPException(status_code=404, detail="No authenticity checks found for this card")

    return {
        "card_id": card_id,
        "checks": [
            {
                "id": c.id,
                "check_type": c.check_type,
                "passed": c.passed,
                "confidence": c.confidence,
                "details": c.details,
                "error_message": c.error_message,
                "processing_time_ms": c.processing_time_ms,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in checks
        ],
    }
