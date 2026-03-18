"""Station (local agent) tracking model."""

from datetime import datetime
from typing import Optional

from sqlalchemy import String, Boolean, Text, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base, uuid_pk, created_at_col, updated_at_col


class Station(Base):
    """Tracks a connected local hardware agent."""
    __tablename__ = "stations"

    id: Mapped[uuid_pk]
    station_name: Mapped[str] = mapped_column(String(100))
    station_id: Mapped[str] = mapped_column(String(100), unique=True)
    agent_version: Mapped[Optional[str]] = mapped_column(String(50))
    is_online: Mapped[bool] = mapped_column(Boolean, default=False)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    hardware_info: Mapped[Optional[dict]] = mapped_column(JSON)
    operator_id: Mapped[Optional[str]] = mapped_column(String(36))
    created_at: Mapped[created_at_col]
    updated_at: Mapped[updated_at_col]
