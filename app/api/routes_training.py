"""Training Mode API routes — expert grade submission, comparison, and calibration."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.core.events import Events, event_bus

logger = logging.getLogger(__name__)
router = APIRouter()


# ---- Request models ----

class ExpertGradeRequest(BaseModel):
    card_record_id: str
    centering: float = Field(..., ge=1.0, le=10.0)
    corners: float = Field(..., ge=1.0, le=10.0)
    edges: float = Field(..., ge=1.0, le=10.0)
    surface: float = Field(..., ge=1.0, le=10.0)
    final_grade: float = Field(..., ge=1.0, le=10.0)
    defect_notes: str = ""
    operator: str = "default"
    expertise_level: str = "standard"


class ApplyCalibrationRequest(BaseModel):
    report_id: str
    operator: str


# ---- Endpoints ----

@router.post("/submit")
async def submit_expert_grade(req: ExpertGradeRequest, db: Session = Depends(get_db)):
    """Submit expert manual grade for a card."""
    from app.services.training.service import submit_expert_grade

    try:
        result = submit_expert_grade(
            card_record_id=req.card_record_id,
            centering=req.centering,
            corners=req.corners,
            edges=req.edges,
            surface=req.surface,
            final_grade=req.final_grade,
            defect_notes=req.defect_notes,
            operator_name=req.operator,
            expertise_level=req.expertise_level,
            db=db,
        )
        event_bus.publish(Events.TRAINING_GRADE_SUBMITTED, {
            "card_record_id": req.card_record_id,
            "operator": req.operator,
        })
        return result
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/compare/{card_id}")
async def compare_grades(card_id: str, db: Session = Depends(get_db)):
    """Get side-by-side expert vs AI comparison."""
    from app.services.training.service import get_comparison

    result = get_comparison(card_id, db)
    if not result:
        raise HTTPException(404, "No training grade found for this card")
    return result


@router.get("/stats")
async def training_stats(
    profile: Optional[str] = None,
    franchise: Optional[str] = None,
    min_date: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Get aggregate training statistics."""
    from app.services.training.service import get_aggregate_stats
    return get_aggregate_stats(db, profile=profile, franchise=franchise, min_date=min_date)


@router.get("/calibration")
async def calibration_report(
    profile: Optional[str] = None,
    franchise: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Generate calibration report with threshold recommendations."""
    from app.services.training.service import generate_calibration_report
    return generate_calibration_report(db, profile=profile, franchise=franchise)


@router.get("/calibration/history")
async def calibration_history(db: Session = Depends(get_db)):
    """List past calibration reports."""
    from app.models.training import CalibrationReport

    reports = db.query(CalibrationReport).order_by(CalibrationReport.created_at.desc()).limit(20).all()
    return {
        "reports": [
            {
                "id": r.id,
                "sample_count": r.sample_count,
                "match_rate": r.match_rate,
                "avg_delta_final": r.avg_delta_final,
                "recommendations_count": len(r.recommendations_json or []),
                "applied": r.applied,
                "applied_by": r.applied_by,
                "applied_at": r.applied_at.isoformat() if r.applied_at else None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in reports
        ],
    }


@router.post("/calibrate/apply")
async def apply_calibration(req: ApplyCalibrationRequest, db: Session = Depends(get_db)):
    """Apply calibration report recommendations (admin only)."""
    from app.services.training.service import apply_calibration

    try:
        result = apply_calibration(req.report_id, req.operator, db)
        event_bus.publish(Events.CALIBRATION_APPLIED, {
            "report_id": req.report_id,
            "operator": req.operator,
            "changes": len(result.get("changes", [])),
        })
        return result
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/trend")
async def training_trend(window_days: int = 90, db: Session = Depends(get_db)):
    """Get trend data for training accuracy over time."""
    from app.services.training.service import get_trend_data
    return {"trend": get_trend_data(db, window_days)}


@router.get("/list")
async def list_training_grades(
    page: int = 1,
    per_page: int = 25,
    db: Session = Depends(get_db),
):
    """Paginated list of all training grades."""
    from app.models.training import TrainingGrade
    from app.models.card import CardRecord

    offset = (page - 1) * per_page
    total = db.query(TrainingGrade).count()
    rows = (
        db.query(TrainingGrade, CardRecord)
        .outerjoin(CardRecord, CardRecord.id == TrainingGrade.card_record_id)
        .order_by(TrainingGrade.created_at.desc())
        .offset(offset)
        .limit(per_page)
        .all()
    )

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "items": [
            {
                "id": tg.id,
                "card_name": card.card_name if card else None,
                "set_name": card.set_name if card else None,
                "expert_final": tg.expert_final,
                "ai_final": tg.ai_final,
                "delta_final": tg.delta_final,
                "operator_name": tg.operator_name,
                "created_at": tg.created_at.isoformat() if tg.created_at else None,
            }
            for tg, card in rows
        ],
    }
