"""Pre-built report queries returning Chart.js-compatible data structures."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import func, select, case, distinct
from sqlalchemy.orm import Session

from app.models.admin import AuditEvent, OperatorAction
from app.models.authenticity import AuthenticityDecision
from app.models.card import CardRecord
from app.models.grading import DefectFinding, GradeDecision
from app.models.scan import ScanSession

logger = logging.getLogger(__name__)


def _parse_dates(
    date_start: Optional[str],
    date_end: Optional[str],
) -> tuple[datetime, datetime]:
    """Parse ISO date strings; default to last 30 days."""
    now = datetime.now(timezone.utc)
    if date_end:
        end = datetime.fromisoformat(date_end)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
    else:
        end = now

    if date_start:
        start = datetime.fromisoformat(date_start)
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
    else:
        start = end - timedelta(days=30)

    return start, end


class ReportQueries:
    """Collection of analytics queries returning Chart.js-ready dicts."""

    # ------------------------------------------------------------------
    # throughput: cards graded per day / week / month
    # ------------------------------------------------------------------
    def throughput(
        self,
        db: Session,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
    ) -> dict:
        start, end = _parse_dates(date_start, date_end)
        stmt = (
            select(
                func.date(GradeDecision.created_at).label("day"),
                func.count(GradeDecision.id).label("cnt"),
            )
            .where(GradeDecision.created_at.between(start, end))
            .where(GradeDecision.status.in_(["approved", "overridden"]))
            .group_by(func.date(GradeDecision.created_at))
            .order_by(func.date(GradeDecision.created_at))
        )
        rows = db.execute(stmt).all()
        labels = [str(r.day) for r in rows]
        data = [r.cnt for r in rows]

        return {
            "labels": labels,
            "datasets": [{
                "label": "Cards Graded",
                "data": data,
                "borderColor": "rgb(54, 162, 235)",
                "backgroundColor": "rgba(54, 162, 235, 0.2)",
                "fill": True,
            }],
        }

    # ------------------------------------------------------------------
    # grade_distribution: histogram of final grades
    # ------------------------------------------------------------------
    def grade_distribution(
        self,
        db: Session,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
    ) -> dict:
        start, end = _parse_dates(date_start, date_end)

        # Use the effective grade (override if present, else final_grade)
        effective_grade = case(
            (GradeDecision.operator_override_grade.isnot(None), GradeDecision.operator_override_grade),
            else_=GradeDecision.final_grade,
        )

        stmt = (
            select(
                effective_grade.label("grade"),
                func.count(GradeDecision.id).label("cnt"),
            )
            .where(GradeDecision.created_at.between(start, end))
            .where(GradeDecision.status.in_(["approved", "overridden"]))
            .where(effective_grade.isnot(None))
            .group_by(effective_grade)
            .order_by(effective_grade)
        )
        rows = db.execute(stmt).all()

        # Build a full 1.0 - 10.0 (0.5 step) histogram with zeros for missing
        all_grades = [round(g * 0.5, 1) for g in range(2, 21)]  # 1.0 .. 10.0
        grade_map = {float(r.grade): r.cnt for r in rows}
        labels = [str(g) for g in all_grades]
        data = [grade_map.get(g, 0) for g in all_grades]

        colors = []
        for g in all_grades:
            if g >= 10:
                colors.append("rgba(255, 193, 7, 0.8)")   # gold
            elif g >= 9:
                colors.append("rgba(25, 135, 84, 0.8)")   # green
            elif g >= 7:
                colors.append("rgba(13, 202, 240, 0.8)")  # teal
            elif g >= 5:
                colors.append("rgba(255, 193, 7, 0.8)")   # yellow
            else:
                colors.append("rgba(220, 53, 69, 0.8)")   # red

        return {
            "labels": labels,
            "datasets": [{
                "label": "Cards",
                "data": data,
                "backgroundColor": colors,
            }],
        }

    # ------------------------------------------------------------------
    # override_rate: auto-approved vs overridden percentages
    # ------------------------------------------------------------------
    def override_rate(
        self,
        db: Session,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
    ) -> dict:
        start, end = _parse_dates(date_start, date_end)

        base = (
            select(func.count(GradeDecision.id))
            .where(GradeDecision.created_at.between(start, end))
        )
        total = db.execute(
            base.where(GradeDecision.status.in_(["approved", "overridden"]))
        ).scalar() or 0

        overridden = db.execute(
            base.where(GradeDecision.status == "overridden")
        ).scalar() or 0

        approved = total - overridden

        return {
            "labels": ["Auto-Approved", "Overridden"],
            "datasets": [{
                "data": [approved, overridden],
                "backgroundColor": [
                    "rgba(25, 135, 84, 0.8)",
                    "rgba(255, 193, 7, 0.8)",
                ],
            }],
            "summary": {
                "total": total,
                "approved": approved,
                "overridden": overridden,
                "override_pct": round(overridden / max(total, 1) * 100, 1),
            },
        }

    # ------------------------------------------------------------------
    # authenticity_rate: outcome percentages
    # ------------------------------------------------------------------
    def authenticity_rate(
        self,
        db: Session,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
    ) -> dict:
        start, end = _parse_dates(date_start, date_end)

        statuses = ["authentic", "suspect", "reject", "manual_review"]
        colour_map = {
            "authentic": "rgba(25, 135, 84, 0.8)",
            "suspect": "rgba(255, 193, 7, 0.8)",
            "reject": "rgba(220, 53, 69, 0.8)",
            "manual_review": "rgba(13, 202, 240, 0.8)",
        }

        # Use the effective status (override if present)
        effective_status = case(
            (AuthenticityDecision.operator_override_status.isnot(None),
             AuthenticityDecision.operator_override_status),
            else_=AuthenticityDecision.overall_status,
        )

        stmt = (
            select(
                effective_status.label("status"),
                func.count(AuthenticityDecision.id).label("cnt"),
            )
            .where(AuthenticityDecision.created_at.between(start, end))
            .group_by(effective_status)
        )
        rows = db.execute(stmt).all()
        counts = {r.status: r.cnt for r in rows}

        labels = [s.replace("_", " ").title() for s in statuses]
        data = [counts.get(s, 0) for s in statuses]
        colors = [colour_map[s] for s in statuses]

        total = sum(data)
        pcts = {s: round(counts.get(s, 0) / max(total, 1) * 100, 1) for s in statuses}

        return {
            "labels": labels,
            "datasets": [{
                "data": data,
                "backgroundColor": colors,
            }],
            "summary": {"total": total, "percentages": pcts},
        }

    # ------------------------------------------------------------------
    # processing_time: avg time from scan creation to grade approval
    # ------------------------------------------------------------------
    def processing_time(
        self,
        db: Session,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
    ) -> dict:
        start, end = _parse_dates(date_start, date_end)

        # Join cards -> scans and cards -> grades to compute time deltas
        stmt = (
            select(
                ScanSession.created_at.label("scan_time"),
                GradeDecision.approved_at.label("grade_time"),
                GradeDecision.created_at.label("grade_created"),
            )
            .join(CardRecord, CardRecord.session_id == ScanSession.id)
            .join(GradeDecision, GradeDecision.card_record_id == CardRecord.id)
            .where(GradeDecision.status.in_(["approved", "overridden"]))
            .where(GradeDecision.created_at.between(start, end))
            .where(GradeDecision.approved_at.isnot(None))
        )
        rows = db.execute(stmt).all()

        if not rows:
            return {
                "labels": ["Scan to Grade"],
                "datasets": [{"label": "Avg Minutes", "data": [0], "backgroundColor": ["rgba(54, 162, 235, 0.8)"]}],
                "summary": {"avg_minutes": 0, "sample_size": 0},
            }

        deltas = []
        for r in rows:
            if r.scan_time and r.grade_time:
                delta = (r.grade_time - r.scan_time).total_seconds() / 60.0
                if delta >= 0:
                    deltas.append(delta)

        avg_min = round(sum(deltas) / max(len(deltas), 1), 2)

        return {
            "labels": ["Scan to Grade"],
            "datasets": [{
                "label": "Avg Minutes",
                "data": [avg_min],
                "backgroundColor": ["rgba(54, 162, 235, 0.8)"],
            }],
            "summary": {"avg_minutes": avg_min, "sample_size": len(deltas)},
        }

    # ------------------------------------------------------------------
    # defect_frequency: count of each defect type
    # ------------------------------------------------------------------
    def defect_frequency(
        self,
        db: Session,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
    ) -> dict:
        start, end = _parse_dates(date_start, date_end)

        stmt = (
            select(
                DefectFinding.defect_type,
                func.count(DefectFinding.id).label("cnt"),
            )
            .where(DefectFinding.created_at.between(start, end))
            .where(DefectFinding.is_noise == False)  # noqa: E712
            .group_by(DefectFinding.defect_type)
            .order_by(func.count(DefectFinding.id).desc())
        )
        rows = db.execute(stmt).all()
        labels = [r.defect_type for r in rows]
        data = [r.cnt for r in rows]

        return {
            "labels": labels,
            "datasets": [{
                "label": "Occurrences",
                "data": data,
                "backgroundColor": "rgba(255, 99, 132, 0.8)",
            }],
        }

    # ------------------------------------------------------------------
    # top_defects: most common defects (limited)
    # ------------------------------------------------------------------
    def top_defects(
        self,
        db: Session,
        limit: int = 10,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
    ) -> dict:
        start, end = _parse_dates(date_start, date_end)

        stmt = (
            select(
                DefectFinding.defect_type,
                func.count(DefectFinding.id).label("cnt"),
            )
            .where(DefectFinding.created_at.between(start, end))
            .where(DefectFinding.is_noise == False)  # noqa: E712
            .group_by(DefectFinding.defect_type)
            .order_by(func.count(DefectFinding.id).desc())
            .limit(limit)
        )
        rows = db.execute(stmt).all()
        labels = [r.defect_type for r in rows]
        data = [r.cnt for r in rows]

        palette = [
            "rgba(255, 99, 132, 0.8)",
            "rgba(54, 162, 235, 0.8)",
            "rgba(255, 206, 86, 0.8)",
            "rgba(75, 192, 192, 0.8)",
            "rgba(153, 102, 255, 0.8)",
            "rgba(255, 159, 64, 0.8)",
            "rgba(199, 199, 199, 0.8)",
            "rgba(83, 102, 255, 0.8)",
            "rgba(255, 99, 255, 0.8)",
            "rgba(99, 255, 132, 0.8)",
        ]
        colors = palette[:len(labels)]

        return {
            "labels": labels,
            "datasets": [{
                "label": "Count",
                "data": data,
                "backgroundColor": colors,
            }],
        }

    # ------------------------------------------------------------------
    # daily_volume: cards processed per day (last 30 days)
    # ------------------------------------------------------------------
    def daily_volume(
        self,
        db: Session,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
    ) -> dict:
        start, end = _parse_dates(date_start, date_end)

        stmt = (
            select(
                func.date(CardRecord.created_at).label("day"),
                func.count(CardRecord.id).label("cnt"),
            )
            .where(CardRecord.created_at.between(start, end))
            .group_by(func.date(CardRecord.created_at))
            .order_by(func.date(CardRecord.created_at))
        )
        rows = db.execute(stmt).all()

        # Fill gaps with zero values
        day_map = {str(r.day): r.cnt for r in rows}
        current = start.date() if hasattr(start, 'date') else start
        end_d = end.date() if hasattr(end, 'date') else end
        labels = []
        data = []
        while current <= end_d:
            day_str = str(current)
            labels.append(day_str)
            data.append(day_map.get(day_str, 0))
            current += timedelta(days=1)

        return {
            "labels": labels,
            "datasets": [{
                "label": "Cards Processed",
                "data": data,
                "borderColor": "rgb(75, 192, 192)",
                "backgroundColor": "rgba(75, 192, 192, 0.2)",
                "fill": True,
                "tension": 0.3,
            }],
        }

    # ------------------------------------------------------------------
    # operator_stats: actions per operator
    # ------------------------------------------------------------------
    def operator_stats(
        self,
        db: Session,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
    ) -> dict:
        start, end = _parse_dates(date_start, date_end)

        stmt = (
            select(
                AuditEvent.operator_name,
                func.count(AuditEvent.id).label("cnt"),
            )
            .where(AuditEvent.created_at.between(start, end))
            .where(AuditEvent.operator_name.isnot(None))
            .group_by(AuditEvent.operator_name)
            .order_by(func.count(AuditEvent.id).desc())
        )
        rows = db.execute(stmt).all()

        return {
            "labels": [r.operator_name for r in rows],
            "datasets": [{
                "label": "Actions",
                "data": [r.cnt for r in rows],
                "backgroundColor": "rgba(153, 102, 255, 0.8)",
            }],
        }

    # ------------------------------------------------------------------
    # summary: top-level stats for the dashboard header
    # ------------------------------------------------------------------
    def summary(
        self,
        db: Session,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
    ) -> dict:
        start, end = _parse_dates(date_start, date_end)

        total_cards = db.execute(
            select(func.count(CardRecord.id))
            .where(CardRecord.created_at.between(start, end))
        ).scalar() or 0

        total_graded = db.execute(
            select(func.count(GradeDecision.id))
            .where(GradeDecision.created_at.between(start, end))
            .where(GradeDecision.status.in_(["approved", "overridden"]))
        ).scalar() or 0

        effective_grade = case(
            (GradeDecision.operator_override_grade.isnot(None), GradeDecision.operator_override_grade),
            else_=GradeDecision.final_grade,
        )
        avg_grade_val = db.execute(
            select(func.avg(effective_grade))
            .where(GradeDecision.created_at.between(start, end))
            .where(GradeDecision.status.in_(["approved", "overridden"]))
            .where(effective_grade.isnot(None))
        ).scalar()
        avg_grade = round(float(avg_grade_val), 2) if avg_grade_val else 0.0

        # Pass rate: grades >= 7.0
        pass_count = db.execute(
            select(func.count(GradeDecision.id))
            .where(GradeDecision.created_at.between(start, end))
            .where(GradeDecision.status.in_(["approved", "overridden"]))
            .where(effective_grade >= 7.0)
        ).scalar() or 0
        pass_rate = round(pass_count / max(total_graded, 1) * 100, 1)

        # Override count
        total_overrides = db.execute(
            select(func.count(GradeDecision.id))
            .where(GradeDecision.created_at.between(start, end))
            .where(GradeDecision.status == "overridden")
        ).scalar() or 0

        # Auth flags
        total_auth_flags = db.execute(
            select(func.count(AuthenticityDecision.id))
            .where(AuthenticityDecision.created_at.between(start, end))
            .where(AuthenticityDecision.overall_status.in_(["suspect", "reject"]))
        ).scalar() or 0

        # Avg processing time (scan to grade in minutes)
        time_stmt = (
            select(
                ScanSession.created_at.label("scan_time"),
                GradeDecision.approved_at.label("grade_time"),
            )
            .join(CardRecord, CardRecord.session_id == ScanSession.id)
            .join(GradeDecision, GradeDecision.card_record_id == CardRecord.id)
            .where(GradeDecision.status.in_(["approved", "overridden"]))
            .where(GradeDecision.created_at.between(start, end))
            .where(GradeDecision.approved_at.isnot(None))
        )
        time_rows = db.execute(time_stmt).all()
        deltas = []
        for r in time_rows:
            if r.scan_time and r.grade_time:
                d = (r.grade_time - r.scan_time).total_seconds() / 60.0
                if d >= 0:
                    deltas.append(d)
        avg_processing = round(sum(deltas) / max(len(deltas), 1), 2) if deltas else 0.0

        return {
            "total_cards": total_cards,
            "total_graded": total_graded,
            "avg_grade": avg_grade,
            "pass_rate": pass_rate,
            "total_overrides": total_overrides,
            "override_rate": round(total_overrides / max(total_graded, 1) * 100, 1),
            "total_auth_flags": total_auth_flags,
            "avg_processing_minutes": avg_processing,
        }
