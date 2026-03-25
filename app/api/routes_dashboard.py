"""Dashboard API routes."""

import asyncio
import logging
import time
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter()

# Cache for scanner status probe (avoids blocking I/O on every dashboard load)
_scanner_cache: dict = {"available": False, "timestamp": 0.0}
_SCANNER_CACHE_TTL = 5.0  # seconds


@router.get("/summary")
async def get_dashboard_summary(db: Session = Depends(get_db)):
    """Get dashboard summary statistics."""
    from app.models.scan import ScanSession
    from app.models.grading import GradeDecision
    from app.models.authenticity import AuthenticityDecision

    total_scans = db.query(ScanSession).count()
    total_graded = db.query(GradeDecision).filter(GradeDecision.status.in_(["approved", "overridden", "graded"])).count()
    pending_review = db.query(GradeDecision).filter(GradeDecision.status == "pending").count()
    auth_alerts = db.query(AuthenticityDecision).filter(
        AuthenticityDecision.overall_status.in_(["suspect", "manual_review"])
    ).count()

    from app.config import settings

    # Probe for real scanner hardware (cached for 5s to avoid blocking every load)
    now = time.monotonic()
    if now - _scanner_cache["timestamp"] > _SCANNER_CACHE_TTL:
        try:
            from app.services.scanner.wia_scanner import WIAScanner

            def _probe_scanner() -> bool:
                scanner = WIAScanner()
                return len(scanner.list_devices()) > 0

            real_scanner_available = await asyncio.to_thread(_probe_scanner)
        except Exception as exc:
            logger.debug("Scanner probe failed: %s", exc)
            real_scanner_available = False
        _scanner_cache["available"] = real_scanner_available
        _scanner_cache["timestamp"] = now
    else:
        real_scanner_available = _scanner_cache["available"]

    return {
        "total_scans": total_scans,
        "total_graded": total_graded,
        "pending_review": pending_review,
        "auth_alerts": auth_alerts,
        "system_status": {
            "scanner_mock": settings.scanner.mock_mode,
            "scanner_connected": real_scanner_available,
            "database_connected": True,
            "pokewallet_ready": bool(settings.pokewallet.api_key),
            "openrouter_enabled": settings.openrouter.enabled,
            "openrouter_ready": bool(settings.openrouter.api_key) and settings.openrouter.enabled,
        },
    }


@router.get("/recent-activity")
async def get_recent_activity(limit: int = 20, db: Session = Depends(get_db)):
    """Get recent audit events for dashboard feed."""
    from app.models.admin import AuditEvent
    events = db.query(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(limit).all()
    return [
        {
            "id": e.id,
            "event_type": e.event_type,
            "action": e.action,
            "entity_type": e.entity_type,
            "entity_id": e.entity_id,
            "operator": e.operator_name,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in events
    ]
