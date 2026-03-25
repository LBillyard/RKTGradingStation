"""Audit log API routes — immutable event trail with filtering and export."""

import csv
import io
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.admin import AuditEvent
from app.services.reports.generator import AuditGenerator

logger = logging.getLogger(__name__)
router = APIRouter()

_audit = AuditGenerator()


# ----- Request models -----

class ExportRequest(BaseModel):
    """Filters for CSV export."""
    event_type: Optional[str] = None
    entity_type: Optional[str] = None
    operator: Optional[str] = None
    date_start: Optional[str] = None
    date_end: Optional[str] = None


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _parse_dates(date_start: Optional[str], date_end: Optional[str]):
    """Parse optional ISO date strings to datetime objects."""
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    start = None
    end = None
    if date_start:
        start = datetime.fromisoformat(date_start)
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
    if date_end:
        end = datetime.fromisoformat(date_end)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
    return start, end


def _build_query(
    event_type: Optional[str],
    entity_type: Optional[str],
    operator: Optional[str],
    date_start: Optional[str],
    date_end: Optional[str],
):
    """Build a SQLAlchemy 2.0 select statement with optional filters."""
    stmt = select(AuditEvent)

    if event_type:
        stmt = stmt.where(AuditEvent.event_type == event_type)
    if entity_type:
        stmt = stmt.where(AuditEvent.entity_type == entity_type)
    if operator:
        stmt = stmt.where(AuditEvent.operator_name == operator)

    start, end = _parse_dates(date_start, date_end)
    if start:
        stmt = stmt.where(AuditEvent.created_at >= start)
    if end:
        stmt = stmt.where(AuditEvent.created_at <= end)

    return stmt


def _event_to_dict(e: AuditEvent, include_state: bool = False) -> dict:
    """Serialise an AuditEvent row to a JSON-safe dict."""
    d = {
        "id": e.id,
        "event_type": e.event_type,
        "entity_type": e.entity_type,
        "entity_id": e.entity_id,
        "operator": e.operator_name,
        "action": e.action,
        "details": e.details,
        "created_at": e.created_at.isoformat() if e.created_at else None,
    }
    if include_state:
        d["before_state"] = e.before_state
        d["after_state"] = e.after_state
    return d


# ------------------------------------------------------------------
# GET /api/audit/events
# ------------------------------------------------------------------

@router.get("/events")
async def list_audit_events(
    event_type: Optional[str] = Query(None),
    entity_type: Optional[str] = Query(None),
    operator: Optional[str] = Query(None),
    date_start: Optional[str] = Query(None),
    date_end: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """List audit events with filters and pagination."""
    base = _build_query(event_type, entity_type, operator, date_start, date_end)

    # Total count (without pagination)
    from sqlalchemy import func
    count_stmt = select(func.count()).select_from(base.subquery())
    total = db.execute(count_stmt).scalar() or 0

    # Paginated results
    stmt = base.order_by(AuditEvent.created_at.desc()).offset(offset).limit(limit)
    events = db.execute(stmt).scalars().all()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "events": [_event_to_dict(e) for e in events],
    }


# ------------------------------------------------------------------
# GET /api/audit/events/{event_id}
# ------------------------------------------------------------------

@router.get("/events/{event_id}")
async def get_audit_event(event_id: str, db: Session = Depends(get_db)):
    """Get a single audit event with full before/after state."""
    event = _audit.get_event_by_id(event_id, db)
    if not event:
        raise HTTPException(status_code=404, detail="Audit event not found")
    return event.to_dict()


# ------------------------------------------------------------------
# GET /api/audit/entity/{entity_type}/{entity_id}
# ------------------------------------------------------------------

@router.get("/entity/{entity_type}/{entity_id}")
async def get_entity_events(
    entity_type: str,
    entity_id: str,
    db: Session = Depends(get_db),
):
    """Get all audit events for a specific entity."""
    events = _audit.get_events_for_entity(entity_type, entity_id, db)
    return {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "total": len(events),
        "events": [ev.to_dict() for ev in events],
    }


# ------------------------------------------------------------------
# GET /api/audit/event-types
# ------------------------------------------------------------------

@router.get("/event-types")
async def list_event_types(db: Session = Depends(get_db)):
    """List distinct event types currently in the system."""
    return {"event_types": _audit.get_distinct_event_types(db)}


# ------------------------------------------------------------------
# GET /api/audit/operators
# ------------------------------------------------------------------

@router.get("/operators")
async def list_operators(db: Session = Depends(get_db)):
    """List distinct operator names."""
    return {"operators": _audit.get_distinct_operators(db)}


# ------------------------------------------------------------------
# POST /api/audit/export
# ------------------------------------------------------------------

_EXPORT_BATCH_SIZE = 500


@router.post("/export")
async def export_audit_csv(
    body: ExportRequest,
    db: Session = Depends(get_db),
):
    """Export filtered audit events as a streaming CSV file download.

    Reads rows in batches to avoid loading all rows into memory at once.
    """
    import json

    stmt = _build_query(
        body.event_type,
        body.entity_type,
        body.operator,
        body.date_start,
        body.date_end,
    ).order_by(AuditEvent.created_at.desc())

    def _generate_csv():
        # Yield CSV header
        header = io.StringIO()
        writer = csv.writer(header)
        writer.writerow([
            "ID", "Timestamp", "Event Type", "Entity Type", "Entity ID",
            "Operator", "Action", "Details",
        ])
        yield header.getvalue()

        # Stream rows in batches
        offset = 0
        while True:
            batch_stmt = stmt.offset(offset).limit(_EXPORT_BATCH_SIZE)
            batch = db.execute(batch_stmt).scalars().all()
            if not batch:
                break

            for e in batch:
                row_buf = io.StringIO()
                writer = csv.writer(row_buf)
                details_str = json.dumps(e.details) if e.details else ""
                writer.writerow([
                    e.id,
                    e.created_at.isoformat() if e.created_at else "",
                    e.event_type,
                    e.entity_type or "",
                    e.entity_id or "",
                    e.operator_name or "",
                    e.action,
                    details_str,
                ])
                yield row_buf.getvalue()

            if len(batch) < _EXPORT_BATCH_SIZE:
                break
            offset += _EXPORT_BATCH_SIZE

    return StreamingResponse(
        _generate_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit_events.csv"},
    )
