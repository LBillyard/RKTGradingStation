"""Enhancement API routes — grade curve, queue priority, daily targets,
auto-slab routing, bulk import, and grading configuration."""

import csv
import io
import logging
from datetime import datetime, timezone, date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter()


# ---- Grade Curve ----

class GradeCurveUpdate(BaseModel):
    enabled: Optional[bool] = None
    curve_offset: Optional[float] = None
    min_raw_score: Optional[float] = None


@router.get("/grade-curve")
async def get_grade_curve():
    from app.services.grading.enhancements import get_curve_config
    return get_curve_config()


@router.put("/grade-curve")
async def update_grade_curve(req: GradeCurveUpdate):
    from app.services.grading.enhancements import set_curve_config
    set_curve_config(
        enabled=req.enabled,
        curve_offset=req.curve_offset,
        min_raw_score=req.min_raw_score,
    )
    from app.services.grading.enhancements import get_curve_config
    return {"status": "ok", "grade_curve": get_curve_config()}


# ---- Smart Queue ----

@router.get("/queue/prioritised")
async def prioritised_queue(limit: int = 50, db: Session = Depends(get_db)):
    """Get cards sorted by grading priority (high-value first)."""
    from app.models.card import CardRecord
    from app.models.grading import GradeDecision
    from app.services.grading.enhancements import prioritise_queue

    rows = (
        db.query(CardRecord)
        .outerjoin(GradeDecision, GradeDecision.card_record_id == CardRecord.id)
        .filter(CardRecord.status.in_(["pending", "graded"]))
        .limit(limit * 2)
        .all()
    )

    cards = [
        {
            "id": c.id, "card_name": c.card_name, "set_name": c.set_name,
            "rarity": c.rarity, "serial_number": c.serial_number,
            "franchise": c.franchise,
        }
        for c in rows
    ]

    prioritised = prioritise_queue(cards)
    return {"cards": prioritised[:limit]}


# ---- Daily Targets ----

@router.get("/daily-targets")
async def daily_targets(operator: Optional[str] = None, db: Session = Depends(get_db)):
    """Get daily grading progress for the current day."""
    from app.models.grading import GradeDecision

    today = date.today()
    today_start = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)

    query = db.query(func.count(GradeDecision.id)).filter(
        GradeDecision.created_at >= today_start
    )
    if operator:
        query = query.filter(GradeDecision.graded_by == operator)

    graded_today = query.scalar() or 0
    target = 50

    # Calculate pace (cards per hour based on first and last grade today)
    pace = 0
    if graded_today > 1:
        first = db.query(func.min(GradeDecision.created_at)).filter(
            GradeDecision.created_at >= today_start
        ).scalar()
        last = db.query(func.max(GradeDecision.created_at)).filter(
            GradeDecision.created_at >= today_start
        ).scalar()
        if first and last:
            hours = max((last - first).total_seconds() / 3600, 0.1)
            pace = round(graded_today / hours, 1)

    return {
        "target": target,
        "graded_today": graded_today,
        "remaining": max(0, target - graded_today),
        "pace_cards_per_hour": pace,
        "progress_pct": round(min(100, (graded_today / target) * 100), 1),
        "operator": operator,
    }


# ---- Grade Explanation ----

@router.get("/explain/{card_id}")
async def explain_grade(card_id: str, db: Session = Depends(get_db)):
    """Generate a human-readable grade explanation for a card."""
    from app.models.grading import GradeDecision, DefectFinding
    from app.models.card import CardRecord
    from app.services.grading.enhancements import generate_explanation

    grade = db.query(GradeDecision).filter(GradeDecision.card_record_id == card_id).first()
    if not grade:
        raise HTTPException(404, "No grade found for this card")

    card = db.query(CardRecord).filter(CardRecord.id == card_id).first()
    defects = db.query(DefectFinding).filter(
        DefectFinding.card_record_id == card_id,
        DefectFinding.is_noise == False,
    ).all()

    defect_list = [
        {"category": d.category, "defect_type": d.defect_type,
         "severity": d.severity, "score_impact": d.score_impact}
        for d in defects
    ]

    sub_scores = {
        "centering": grade.centering_score or 0,
        "corners": grade.corners_score or 0,
        "edges": grade.edges_score or 0,
        "surface": grade.surface_score or 0,
    }

    import json
    caps = json.loads(grade.grade_caps_json) if isinstance(grade.grade_caps_json, str) else (grade.grade_caps_json or [])

    explanation = generate_explanation(
        final_grade=grade.final_grade,
        sub_scores=sub_scores,
        defects=defect_list,
        caps_applied=caps,
        card_name=card.card_name if card else "",
    )

    return {
        "card_id": card_id,
        "final_grade": grade.final_grade,
        "explanation": explanation,
        "sub_scores": sub_scores,
        "defect_count": len(defect_list),
    }


# ---- Cross-Validation ----

@router.get("/cross-validate/{card_id}")
async def cross_validate(card_id: str, db: Session = Depends(get_db)):
    """Check if the current grade is consistent with previous grades."""
    from app.models.grading import GradeDecision, GradeHistory
    from app.services.grading.enhancements import cross_validate_grade

    current = db.query(GradeDecision).filter(GradeDecision.card_record_id == card_id).first()
    if not current:
        raise HTTPException(404, "No grade found")

    previous = db.query(GradeHistory).filter(
        GradeHistory.card_record_id == card_id
    ).order_by(GradeHistory.created_at.desc()).first()

    if not previous:
        return {"consistent": True, "message": "No previous grade to compare against"}

    return cross_validate_grade(current.final_grade, previous.final_grade)


# ---- Auto-Slab Routing ----

@router.get("/auto-slab-candidates")
async def auto_slab_candidates(min_grade: float = 9.0, db: Session = Depends(get_db)):
    """Get cards that qualify for auto-slab routing (high grade + high confidence)."""
    from app.models.grading import GradeDecision
    from app.models.card import CardRecord
    from app.services.grading.enhancements import should_auto_slab

    rows = (
        db.query(GradeDecision, CardRecord)
        .join(CardRecord, CardRecord.id == GradeDecision.card_record_id)
        .filter(
            GradeDecision.final_grade >= min_grade,
            GradeDecision.status.in_(["graded", "approved"]),
        )
        .order_by(GradeDecision.final_grade.desc())
        .limit(50)
        .all()
    )

    candidates = []
    for grade, card in rows:
        confidence = grade.grading_confidence or 0
        if should_auto_slab(grade.final_grade, confidence, min_grade):
            candidates.append({
                "card_id": card.id,
                "card_name": card.card_name,
                "serial_number": card.serial_number,
                "final_grade": grade.final_grade,
                "confidence": confidence,
                "auto_slab": True,
            })

    return {"candidates": candidates, "count": len(candidates)}


# ---- Bulk CSV Import ----

@router.post("/bulk-import")
async def bulk_import_cards(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Import cards from a CSV file to pre-populate the grading queue.

    CSV format: card_name, set_name, rarity, expected_grade (optional)
    """
    from app.models.card import CardRecord
    from app.utils.crypto import generate_serial_number

    content = await file.read()
    text = content.decode("utf-8")
    reader = csv.DictReader(io.StringIO(text))

    imported = 0
    errors = []

    for i, row in enumerate(reader, start=2):
        try:
            card_name = row.get("card_name", "").strip()
            set_name = row.get("set_name", "").strip()
            rarity = row.get("rarity", "").strip()

            if not card_name:
                errors.append(f"Row {i}: missing card_name")
                continue

            card = CardRecord(
                card_name=card_name,
                set_name=set_name,
                rarity=rarity,
                serial_number=generate_serial_number(),
                status="pending",
                session_id="bulk-import",
            )
            db.add(card)
            imported += 1
        except Exception as e:
            errors.append(f"Row {i}: {str(e)}")

    db.commit()

    return {
        "imported": imported,
        "errors": errors[:10],
        "total_errors": len(errors),
    }


# ---- Known Issues ----

@router.get("/known-issues")
async def get_known_issues(set_name: str = "", card_name: str = ""):
    """Get known manufacturing defects for a card/set."""
    from app.services.grading.enhancements import get_known_issues
    issues = get_known_issues(set_name, card_name)
    return {"issues": issues, "count": len(issues)}


# ---- Confidence Routing ----

@router.get("/routing/{card_id}")
async def get_grade_routing(card_id: str, db: Session = Depends(get_db)):
    """Get the review routing recommendation for a graded card."""
    from app.models.grading import GradeDecision
    from app.services.grading.enhancements import route_grade

    grade = db.query(GradeDecision).filter(GradeDecision.card_record_id == card_id).first()
    if not grade:
        raise HTTPException(404, "No grade found")

    routing = route_grade(grade.grading_confidence or 50.0, grade.final_grade)
    return {
        "card_id": card_id,
        "route": routing.route,
        "reason": routing.reason,
        "confidence": routing.confidence,
        "final_grade": grade.final_grade,
    }
