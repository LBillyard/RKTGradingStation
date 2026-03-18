"""Hardware profile models: jig, material, calibration."""

from typing import Optional

from sqlalchemy import String, Float, Text, ForeignKey, JSON, Boolean, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base, uuid_pk, created_at_col


class JigProfile(Base):
    """Physical jig configuration for laser alignment."""
    __tablename__ = "jig_profiles"

    id: Mapped[uuid_pk]
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[Optional[str]] = mapped_column(Text)
    slab_position_x_mm: Mapped[float] = mapped_column(Float, default=0.0)
    slab_position_y_mm: Mapped[float] = mapped_column(Float, default=0.0)
    work_area_width_mm: Mapped[float] = mapped_column(Float, default=200.0)
    work_area_height_mm: Mapped[float] = mapped_column(Float, default=200.0)
    fiducial_positions_json: Mapped[Optional[dict]] = mapped_column(JSON)
    camera_offset_x_mm: Mapped[float] = mapped_column(Float, default=0.0)
    camera_offset_y_mm: Mapped[float] = mapped_column(Float, default=0.0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[created_at_col]


class MaterialProfile(Base):
    """Material and laser settings profile."""
    __tablename__ = "material_profiles"

    id: Mapped[uuid_pk]
    name: Mapped[str] = mapped_column(String(100))
    material_type: Mapped[str] = mapped_column(String(50), default="acrylic")
    thickness_mm: Mapped[float] = mapped_column(Float, default=3.0)
    mask_type: Mapped[Optional[str]] = mapped_column(String(50))
    coating_method: Mapped[Optional[str]] = mapped_column(String(100))
    laser_speed_mm_s: Mapped[float] = mapped_column(Float, default=1000.0)
    laser_power_min_pct: Mapped[float] = mapped_column(Float, default=15.0)
    laser_power_max_pct: Mapped[float] = mapped_column(Float, default=20.0)
    laser_passes: Mapped[int] = mapped_column(Integer, default=1)
    laser_interval_mm: Mapped[float] = mapped_column(Float, default=0.08)
    security_speed_mm_s: Mapped[float] = mapped_column(Float, default=800.0)
    security_power_pct: Mapped[float] = mapped_column(Float, default=12.0)
    cleanup_notes: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[created_at_col]


class CalibrationRun(Base):
    """Record of a calibration test run."""
    __tablename__ = "calibration_runs"

    id: Mapped[uuid_pk]
    material_profile_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("material_profiles.id"))
    jig_profile_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("jig_profiles.id"))
    test_pattern: Mapped[str] = mapped_column(String(50), default="grid_matrix")
    result_quality: Mapped[Optional[int]] = mapped_column(Integer)  # 1-10
    result_notes: Mapped[Optional[str]] = mapped_column(Text)
    settings_snapshot: Mapped[Optional[dict]] = mapped_column(JSON)
    image_path: Mapped[Optional[str]] = mapped_column(String(500))
    created_at: Mapped[created_at_col]
