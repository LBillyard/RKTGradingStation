"""Analytics API routes — population data, grade distribution, defect heatmaps.

Cloud-side endpoints that aggregate grading data for insights.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.db.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/population")
async def population_report(
    card_name: Optional[str] = None,
    set_name: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """Card population data — how many of each card graded and grade distribution."""
    from app.models.card import CardRecord
    from app.models.grading import GradeDecision

    query = (
        db.query(
            CardRecord.card_name,
            CardRecord.set_name,
            func.count(CardRecord.id).label("total_graded"),
            func.avg(GradeDecision.final_grade).label("avg_grade"),
            func.min(GradeDecision.final_grade).label("min_grade"),
            func.max(GradeDecision.final_grade).label("max_grade"),
        )
        .outerjoin(GradeDecision, GradeDecision.card_record_id == CardRecord.id)
        .filter(GradeDecision.final_grade.isnot(None))
        .group_by(CardRecord.card_name, CardRecord.set_name)
        .order_by(func.count(CardRecord.id).desc())
    )

    if card_name:
        query = query.filter(CardRecord.card_name.ilike(f"%{card_name}%"))
    if set_name:
        query = query.filter(CardRecord.set_name.ilike(f"%{set_name}%"))

    rows = query.limit(limit).all()

    return {
        "population": [
            {
                "card_name": r.card_name,
                "set_name": r.set_name,
                "total_graded": r.total_graded,
                "avg_grade": round(r.avg_grade, 2) if r.avg_grade else None,
                "min_grade": r.min_grade,
                "max_grade": r.max_grade,
            }
            for r in rows
        ],
    }


@router.get("/grade-distribution")
async def grade_distribution(db: Session = Depends(get_db)):
    """Distribution of grades across all cards."""
    from app.models.grading import GradeDecision

    rows = (
        db.query(
            GradeDecision.final_grade,
            func.count(GradeDecision.id).label("count"),
        )
        .filter(GradeDecision.final_grade.isnot(None))
        .group_by(GradeDecision.final_grade)
        .order_by(GradeDecision.final_grade)
        .all()
    )

    total = sum(r.count for r in rows)

    return {
        "distribution": [
            {
                "grade": r.final_grade,
                "count": r.count,
                "percentage": round((r.count / total) * 100, 1) if total > 0 else 0,
            }
            for r in rows
        ],
        "total": total,
    }


@router.get("/defect-heatmap")
async def defect_heatmap(
    category: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Defect frequency by category and location."""
    from app.models.grading import DefectFinding

    query = db.query(
        DefectFinding.category,
        DefectFinding.defect_type,
        DefectFinding.severity,
        DefectFinding.location,
        func.count(DefectFinding.id).label("count"),
        func.avg(DefectFinding.score_impact).label("avg_impact"),
    ).group_by(
        DefectFinding.category, DefectFinding.defect_type,
        DefectFinding.severity, DefectFinding.location,
    ).order_by(func.count(DefectFinding.id).desc())

    if category:
        query = query.filter(DefectFinding.category == category)

    rows = query.limit(100).all()

    return {
        "defects": [
            {
                "category": r.category,
                "defect_type": r.defect_type,
                "severity": r.severity,
                "location": r.location,
                "count": r.count,
                "avg_impact": round(r.avg_impact, 3) if r.avg_impact else 0,
            }
            for r in rows
        ],
    }


@router.get("/operator-stats")
async def operator_stats(db: Session = Depends(get_db)):
    """Per-operator grading statistics and bias detection."""
    from app.models.grading import GradeDecision

    rows = (
        db.query(
            GradeDecision.graded_by,
            func.count(GradeDecision.id).label("total_graded"),
            func.avg(GradeDecision.final_grade).label("avg_grade"),
            func.count(GradeDecision.operator_override_grade).label("overrides"),
        )
        .filter(GradeDecision.graded_by.isnot(None))
        .group_by(GradeDecision.graded_by)
        .order_by(func.count(GradeDecision.id).desc())
        .all()
    )

    # Calculate overall average for bias detection
    overall_avg = db.query(func.avg(GradeDecision.final_grade)).filter(
        GradeDecision.final_grade.isnot(None)
    ).scalar() or 0

    return {
        "operators": [
            {
                "name": r.graded_by,
                "total_graded": r.total_graded,
                "avg_grade": round(r.avg_grade, 2) if r.avg_grade else None,
                "overrides": r.overrides,
                "bias": round((r.avg_grade or 0) - overall_avg, 2),
            }
            for r in rows
        ],
        "overall_avg_grade": round(overall_avg, 2),
    }


@router.get("/stations")
async def station_overview(db: Session = Depends(get_db)):
    """Overview of all registered stations."""
    from app.models.station import Station

    stations = db.query(Station).order_by(Station.last_seen_at.desc()).all()
    return {
        "stations": [
            {
                "id": s.id,
                "station_name": s.station_name,
                "station_id": s.station_id,
                "agent_version": s.agent_version,
                "is_online": s.is_online,
                "last_seen_at": s.last_seen_at.isoformat() if s.last_seen_at else None,
                "hardware_info": s.hardware_info,
            }
            for s in stations
        ],
    }
