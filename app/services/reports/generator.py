"""Audit event generator for tracking all significant state changes."""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.admin import AuditEvent

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Event type constants (superset of core/events.py for audit-specific usage)
# ---------------------------------------------------------------------------

class AuditEventTypes:
    """All auditable event types in the system."""
    GRADE_APPROVED = "grade.approved"
    GRADE_OVERRIDDEN = "grade.overridden"
    AUTH_DECIDED = "auth.decided"
    AUTH_OVERRIDDEN = "auth.overridden"
    SETTINGS_CHANGED = "settings.changed"
    CARD_CREATED = "card.created"
    SCAN_STARTED = "scan.started"
    SCAN_COMPLETED = "scan.completed"
    REFERENCE_APPROVED = "reference.approved"
    CALIBRATION_RUN = "calibration.run"


# ---------------------------------------------------------------------------
# Entity types for audit trail
# ---------------------------------------------------------------------------

class EntityTypes:
    """Standard entity type strings used in audit events."""
    CARD = "card"
    SCAN = "scan"
    GRADE = "grade"
    AUTHENTICITY = "authenticity"
    SETTINGS = "settings"
    REFERENCE = "reference"
    CALIBRATION = "calibration"


# ---------------------------------------------------------------------------
# Dataclass for returning event data
# ---------------------------------------------------------------------------

@dataclass
class AuditEventData:
    """Serialisable representation of an audit event."""
    id: str
    event_type: str
    entity_type: Optional[str]
    entity_id: Optional[str]
    operator_name: Optional[str]
    action: str
    details: Optional[dict]
    before_state: Optional[dict]
    after_state: Optional[dict]
    created_at: datetime

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "event_type": self.event_type,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "operator": self.operator_name,
            "action": self.action,
            "details": self.details,
            "before_state": self.before_state,
            "after_state": self.after_state,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ---------------------------------------------------------------------------
# Main generator class
# ---------------------------------------------------------------------------

class AuditGenerator:
    """Creates and queries immutable audit trail entries."""

    # Mapping of event types to human-readable action descriptions
    _action_labels: dict[str, str] = {
        AuditEventTypes.GRADE_APPROVED: "Grade approved",
        AuditEventTypes.GRADE_OVERRIDDEN: "Grade overridden by operator",
        AuditEventTypes.AUTH_DECIDED: "Authenticity decision recorded",
        AuditEventTypes.AUTH_OVERRIDDEN: "Authenticity decision overridden",
        AuditEventTypes.SETTINGS_CHANGED: "Settings changed",
        AuditEventTypes.CARD_CREATED: "Card record created",
        AuditEventTypes.SCAN_STARTED: "Scan session started",
        AuditEventTypes.SCAN_COMPLETED: "Scan session completed",
        AuditEventTypes.REFERENCE_APPROVED: "Reference card approved",
        AuditEventTypes.CALIBRATION_RUN: "Calibration run executed",
    }

    def create_audit_event(
        self,
        event_type: str,
        entity_type: Optional[str],
        entity_id: Optional[str],
        operator: Optional[str],
        details: Optional[dict],
        before_state: Optional[dict],
        after_state: Optional[dict],
        db: Session,
    ) -> AuditEventData:
        """Persist a new immutable audit event and return its data."""
        action = self._action_labels.get(event_type, event_type)
        now = datetime.now(timezone.utc)

        event = AuditEvent(
            id=str(uuid.uuid4()),
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            operator_name=operator,
            action=action,
            details=details,
            before_state=before_state,
            after_state=after_state,
            created_at=now,
        )
        db.add(event)
        db.commit()
        db.refresh(event)

        logger.info(
            "Audit event created: type=%s entity=%s/%s operator=%s",
            event_type, entity_type, entity_id, operator,
        )
        return self._to_data(event)

    def get_recent_events(self, db: Session, limit: int = 50) -> list[AuditEventData]:
        """Return the most recent audit events."""
        stmt = (
            select(AuditEvent)
            .order_by(AuditEvent.created_at.desc())
            .limit(limit)
        )
        results = db.execute(stmt).scalars().all()
        return [self._to_data(e) for e in results]

    def get_events_for_entity(
        self,
        entity_type: str,
        entity_id: str,
        db: Session,
    ) -> list[AuditEventData]:
        """Return all audit events for a specific entity."""
        stmt = (
            select(AuditEvent)
            .where(AuditEvent.entity_type == entity_type)
            .where(AuditEvent.entity_id == entity_id)
            .order_by(AuditEvent.created_at.desc())
        )
        results = db.execute(stmt).scalars().all()
        return [self._to_data(e) for e in results]

    def get_event_by_id(self, event_id: str, db: Session) -> Optional[AuditEventData]:
        """Return a single audit event by its ID."""
        stmt = select(AuditEvent).where(AuditEvent.id == event_id)
        event = db.execute(stmt).scalar_one_or_none()
        return self._to_data(event) if event else None

    def get_distinct_event_types(self, db: Session) -> list[str]:
        """Return all distinct event types that exist in the database."""
        stmt = select(AuditEvent.event_type).distinct().order_by(AuditEvent.event_type)
        return [row[0] for row in db.execute(stmt).all()]

    def get_distinct_operators(self, db: Session) -> list[str]:
        """Return all distinct operator names that exist in the database."""
        stmt = (
            select(AuditEvent.operator_name)
            .where(AuditEvent.operator_name.isnot(None))
            .distinct()
            .order_by(AuditEvent.operator_name)
        )
        return [row[0] for row in db.execute(stmt).all()]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_data(event: AuditEvent) -> AuditEventData:
        return AuditEventData(
            id=event.id,
            event_type=event.event_type,
            entity_type=event.entity_type,
            entity_id=event.entity_id,
            operator_name=event.operator_name,
            action=event.action,
            details=event.details,
            before_state=event.before_state,
            after_state=event.after_state,
            created_at=event.created_at,
        )
