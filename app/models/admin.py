"""Administrative models: audit events, operator actions, settings profiles."""

from typing import Optional

from sqlalchemy import String, Text, JSON, Boolean, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base, uuid_pk, created_at_col, updated_at_col


class AuditEvent(Base):
    """Immutable audit trail entry."""
    __tablename__ = "audit_events"

    id: Mapped[uuid_pk]
    event_type: Mapped[str] = mapped_column(String(50))
    entity_type: Mapped[Optional[str]] = mapped_column(String(50))
    entity_id: Mapped[Optional[str]] = mapped_column(String(36))
    operator_name: Mapped[Optional[str]] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(100))
    details: Mapped[Optional[dict]] = mapped_column(JSON)
    before_state: Mapped[Optional[dict]] = mapped_column(JSON)
    after_state: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[created_at_col]


class OperatorAction(Base):
    """Record of an operator's action on a card record."""
    __tablename__ = "operator_actions"

    id: Mapped[uuid_pk]
    card_record_id: Mapped[Optional[str]] = mapped_column(String(36))
    operator_name: Mapped[str] = mapped_column(String(100))
    action_type: Mapped[str] = mapped_column(String(50))
    description: Mapped[Optional[str]] = mapped_column(Text)
    details: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[created_at_col]


class SettingsProfile(Base):
    """Saved settings profile."""
    __tablename__ = "settings_profiles"

    id: Mapped[uuid_pk]
    profile_name: Mapped[str] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(50))
    settings_json: Mapped[dict] = mapped_column(JSON)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[created_at_col]
    updated_at: Mapped[updated_at_col]
