"""Shared test fixtures for RKT Grading Station tests."""

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

# Set test environment before importing app
os.environ["RKT_ENV"] = "test"
os.environ["RKT_DEBUG"] = "false"
os.environ["RKT_LOG_LEVEL"] = "WARNING"


@pytest.fixture
def tmp_data_dir(tmp_path):
    """Create a temporary data directory structure."""
    for subdir in [
        "scans", "scans/mock", "exports", "references",
        "debug", "calibration", "db", "logs", "backups",
    ]:
        (tmp_path / subdir).mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.fixture
def db_session(tmp_data_dir):
    """Create a fresh in-memory database session for testing.

    Initializes all tables so that models are available for queries.
    """
    from app.db.database import init_db, get_session

    db_url = "sqlite:///:memory:"
    init_db(db_url, echo=False)
    session = get_session()
    yield session
    session.close()


@pytest.fixture
def test_app(tmp_data_dir, monkeypatch):
    """Create a FastAPI TestClient with a file-based SQLite database.

    Uses check_same_thread=False to avoid threading issues with
    FastAPI/Starlette's async request handling and SQLite.
    Patches the settings data_dir so backup routes use tmp_data_dir.
    """
    from app.db.database import init_db

    # Use a file-based DB in the temp directory with check_same_thread=False
    db_path = tmp_data_dir / "db" / "test.db"
    db_url = f"sqlite:///{db_path}?check_same_thread=False"
    init_db(db_url, echo=False)

    # Patch settings to use temp data dir for backups, exports, etc.
    from app.config import settings
    monkeypatch.setattr(settings, "data_dir", tmp_data_dir)

    # Create the real backup database file so backup/create works
    db_dir = tmp_data_dir / "db"
    db_dir.mkdir(parents=True, exist_ok=True)
    db_file = db_dir / "rkt_grading.db"
    if not db_file.exists():
        db_file.write_bytes(b"")  # empty file is enough for copy

    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    # Build a minimal test app with the real routers
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from app.api.routes_grading import router as grading_router
    from app.api.routes_backup import router as backup_router
    from app.api.routes_reports import router as reports_router
    from app.api.routes_pdf import router as pdf_router

    app.include_router(grading_router, prefix="/api/grading")
    app.include_router(backup_router, prefix="/api/backup")
    app.include_router(reports_router, prefix="/api/reports")
    app.include_router(pdf_router, prefix="/api/reports")

    client = TestClient(app)
    yield client


@pytest.fixture
def test_db_session(test_app):
    """Provide a database session linked to the test app's database."""
    from app.db.database import get_session
    session = get_session()
    yield session
    session.close()


@pytest.fixture
def test_card(test_db_session):
    """Create a test card record in the database and return its ID."""
    from app.models.scan import ScanSession
    from app.models.card import CardRecord

    session = test_db_session
    card_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())

    # Create a scan session first (required FK)
    scan_session = ScanSession(
        id=session_id,
        operator_name="test_operator",
        status="completed",
    )
    session.add(scan_session)
    session.flush()

    # Create the card record
    card = CardRecord(
        id=card_id,
        session_id=session_id,
        card_name="Charizard",
        set_name="Base Set",
        collector_number="4/102",
        language="en",
        rarity="holo_rare",
        status="graded",
    )
    session.add(card)
    session.commit()

    return card_id


@pytest.fixture
def test_grade_decision(test_db_session, test_card):
    """Create a test grade decision and return the card_id it is linked to."""
    from app.models.grading import GradeDecision

    session = test_db_session
    decision = GradeDecision(
        card_record_id=test_card,
        centering_score=9.0,
        corners_score=8.5,
        edges_score=8.0,
        surface_score=9.5,
        raw_grade=8.65,
        final_grade=8.5,
        auto_grade=8.5,
        centering_ratio_lr="50/50",
        centering_ratio_tb="52/48",
        sensitivity_profile="standard",
        status="graded",
        defect_count=2,
        grading_confidence=85.0,
    )
    session.add(decision)
    session.commit()

    return test_card
