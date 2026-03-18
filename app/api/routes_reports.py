"""Reports API routes — operational analytics endpoints."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.services.reports.queries import ReportQueries

logger = logging.getLogger(__name__)
router = APIRouter()

_queries = ReportQueries()


# ------------------------------------------------------------------
# GET /api/reports/summary
# ------------------------------------------------------------------

@router.get("/summary")
async def get_report_summary(
    date_start: Optional[str] = Query(None, description="ISO date start"),
    date_end: Optional[str] = Query(None, description="ISO date end"),
    db: Session = Depends(get_db),
):
    """Overall summary stats: total cards, avg grade, pass rate, etc."""
    return _queries.summary(db, date_start=date_start, date_end=date_end)


# ------------------------------------------------------------------
# GET /api/reports/grade-distribution
# ------------------------------------------------------------------

@router.get("/grade-distribution")
async def get_grade_distribution(
    date_start: Optional[str] = Query(None),
    date_end: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Grade histogram data (1.0 through 10.0)."""
    return _queries.grade_distribution(db, date_start=date_start, date_end=date_end)


# ------------------------------------------------------------------
# GET /api/reports/throughput
# ------------------------------------------------------------------

@router.get("/throughput")
async def get_throughput(
    date_start: Optional[str] = Query(None),
    date_end: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Daily / weekly / monthly throughput data."""
    return _queries.throughput(db, date_start=date_start, date_end=date_end)


# ------------------------------------------------------------------
# GET /api/reports/override-rate
# ------------------------------------------------------------------

@router.get("/override-rate")
async def get_override_rate(
    date_start: Optional[str] = Query(None),
    date_end: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Override vs auto-approve percentages."""
    return _queries.override_rate(db, date_start=date_start, date_end=date_end)


# ------------------------------------------------------------------
# GET /api/reports/authenticity-rate
# ------------------------------------------------------------------

@router.get("/authenticity-rate")
async def get_authenticity_rate(
    date_start: Optional[str] = Query(None),
    date_end: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Authenticity outcome percentages."""
    return _queries.authenticity_rate(db, date_start=date_start, date_end=date_end)


# ------------------------------------------------------------------
# GET /api/reports/processing-time
# ------------------------------------------------------------------

@router.get("/processing-time")
async def get_processing_time(
    date_start: Optional[str] = Query(None),
    date_end: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Average processing times (scan to grade approval)."""
    return _queries.processing_time(db, date_start=date_start, date_end=date_end)


# ------------------------------------------------------------------
# GET /api/reports/defect-frequency
# ------------------------------------------------------------------

@router.get("/defect-frequency")
async def get_defect_frequency(
    date_start: Optional[str] = Query(None),
    date_end: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Defect type frequency data."""
    return _queries.defect_frequency(db, date_start=date_start, date_end=date_end)


# ------------------------------------------------------------------
# GET /api/reports/daily-volume
# ------------------------------------------------------------------

@router.get("/daily-volume")
async def get_daily_volume(
    date_start: Optional[str] = Query(None),
    date_end: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Last 30 days daily volume."""
    return _queries.daily_volume(db, date_start=date_start, date_end=date_end)


# ------------------------------------------------------------------
# GET /api/reports/operator-stats
# ------------------------------------------------------------------

@router.get("/operator-stats")
async def get_operator_stats(
    date_start: Optional[str] = Query(None),
    date_end: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Per-operator action counts."""
    return _queries.operator_stats(db, date_start=date_start, date_end=date_end)
