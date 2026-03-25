"""Operator model for authentication and access control."""

from typing import Optional

from sqlalchemy import String, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base, uuid_pk, created_at_col, updated_at_col


class Operator(Base):
    """Operator who can log in and perform grading actions."""
    __tablename__ = "operators"

    id: Mapped[uuid_pk]
    name: Mapped[str] = mapped_column(String(100), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))  # Accommodates SHA-256 hex, bcrypt, argon2, etc.
    role: Mapped[str] = mapped_column(String(20), default="operator")  # "operator" or "admin"
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[created_at_col]
    updated_at: Mapped[updated_at_col]
