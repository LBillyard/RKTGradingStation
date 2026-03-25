"""Queue / Graded Cards API routes."""

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.config import settings
from app.db.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter()


def _escape_like(s: str) -> str:
    """Escape LIKE wildcards to prevent injection of % and _ characters."""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _to_data_url(abs_path: Optional[str]) -> Optional[str]:
    """Convert an absolute filesystem path to a /data/ relative URL."""
    if not abs_path:
        return None
    try:
        rel = Path(abs_path).relative_to(Path(settings.data_dir).resolve())
        return f"/data/{rel.as_posix()}"
    except (ValueError, TypeError):
        # Try relative to unresolved data_dir
        try:
            rel = Path(abs_path).relative_to(settings.data_dir)
            return f"/data/{rel.as_posix()}"
        except (ValueError, TypeError):
            return None


@router.get("/list")
async def list_queue(
    status: Optional[str] = Query(None, description="Filter by status"),
    search: Optional[str] = Query(None, description="Search card name"),
    grade_min: Optional[float] = Query(None, description="Minimum grade"),
    grade_max: Optional[float] = Query(None, description="Maximum grade"),
    sort_by: str = Query("created_at", description="Sort field"),
    sort_dir: str = Query("desc", description="Sort direction (asc/desc)"),
    limit: int = 25,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """List cards with grade data, images, search, and sorting."""
    from app.models.card import CardRecord
    from app.models.grading import GradeDecision
    from app.models.scan import CardImage

    query = (
        db.query(CardRecord, GradeDecision, CardImage)
        .outerjoin(GradeDecision, GradeDecision.card_record_id == CardRecord.id)
        .outerjoin(CardImage, CardImage.id == CardRecord.front_image_id)
    )

    # Filters
    if status and status != "all":
        query = query.filter(CardRecord.status == status)
    if search:
        query = query.filter(CardRecord.card_name.ilike(f"%{_escape_like(search)}%", escape="\\"))
    if grade_min is not None:
        query = query.filter(GradeDecision.final_grade >= grade_min)
    if grade_max is not None:
        query = query.filter(GradeDecision.final_grade <= grade_max)

    total = query.count()

    # Sorting
    sort_map = {
        "created_at": CardRecord.created_at,
        "card_name": CardRecord.card_name,
        "grade": GradeDecision.final_grade,
        "status": CardRecord.status,
    }
    sort_col = sort_map.get(sort_by, CardRecord.created_at)
    if sort_dir == "asc":
        query = query.order_by(sort_col.asc())
    else:
        query = query.order_by(sort_col.desc())

    rows = query.offset(offset).limit(limit).all()

    cards = []
    for card, grade, image in rows:
        cards.append({
            "id": card.id,
            "card_name": card.card_name,
            "set_name": card.set_name,
            "collector_number": card.collector_number,
            "rarity": card.rarity,
            "status": card.status,
            "language": card.language,
            "serial_number": card.serial_number,
            "identification_confidence": card.identification_confidence,
            "created_at": card.created_at.isoformat() if card.created_at else None,
            # Grade data
            "final_grade": grade.final_grade if grade else None,
            "grade_status": grade.status if grade else None,
            "defect_count": grade.defect_count if grade else 0,
            # Image data
            "front_image_path": _to_data_url(image.processed_path or image.raw_path) if image else None,
            "thumbnail_path": _to_data_url(image.thumbnail_path) or _to_data_url(image.processed_path or image.raw_path) if image else None,
        })

    return {"total": total, "limit": limit, "offset": offset, "cards": cards}


@router.get("/export")
async def export_graded_cards(
    format: str = "csv",
    db: Session = Depends(get_db),
):
    """Export all graded cards as CSV."""
    from app.models.card import CardRecord
    from app.models.grading import GradeDecision
    from fastapi.responses import StreamingResponse
    import csv
    import io

    cards = db.query(CardRecord, GradeDecision).outerjoin(
        GradeDecision, GradeDecision.card_record_id == CardRecord.id
    ).order_by(CardRecord.created_at.desc()).limit(10000).all()  # Cap at 10k to prevent OOM

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Card Name", "Set", "Collector #", "Language", "Serial",
        "Final Grade", "Raw Grade", "Centering", "Corners", "Edges", "Surface",
        "Defect Count", "Profile", "Status", "Graded At",
    ])

    def _safe_csv(val):
        """Escape CSV formula injection."""
        s = str(val) if val else ""
        if s and s[0] in ("=", "+", "-", "@"):
            return "'" + s
        return s

    for card, grade in cards:
        writer.writerow([
            _safe_csv(card.card_name),
            _safe_csv(card.set_name),
            _safe_csv(card.collector_number),
            card.language or "",
            card.serial_number or "",
            grade.final_grade if grade else "",
            grade.raw_grade if grade else "",
            grade.centering_score if grade else "",
            grade.corners_score if grade else "",
            grade.edges_score if grade else "",
            grade.surface_score if grade else "",
            grade.defect_count if grade else "",
            grade.sensitivity_profile if grade else "",
            grade.status if grade else card.status,
            grade.created_at.isoformat() if grade and grade.created_at else "",
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=rkt_graded_cards.csv"},
    )
