"""Agent telemetry — session timing, operator productivity, and metrics collection.

Stores metrics in a local SQLite database separate from the main app DB.
Syncs summaries to the cloud periodically.
"""

import json
import logging
import sqlite3
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_DB_PATH = Path("data/agent_telemetry.db")
_conn: Optional[sqlite3.Connection] = None


def _get_db() -> sqlite3.Connection:
    """Get or create the telemetry database connection."""
    global _conn
    if _conn is not None:
        return _conn

    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    _conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    _conn.execute("PRAGMA journal_mode=WAL")

    # Create tables
    _conn.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            card_record_id TEXT,
            serial_number TEXT,
            operator_name TEXT,
            station_id TEXT,
            started_at TEXT NOT NULL,
            scan_started_at TEXT,
            scan_completed_at TEXT,
            grade_started_at TEXT,
            grade_completed_at TEXT,
            print_started_at TEXT,
            print_completed_at TEXT,
            nfc_started_at TEXT,
            nfc_completed_at TEXT,
            completed_at TEXT,
            total_seconds REAL,
            status TEXT DEFAULT 'active'
        );

        CREATE TABLE IF NOT EXISTS metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            metric_type TEXT NOT NULL,
            metric_name TEXT NOT NULL,
            value REAL,
            metadata TEXT,
            station_id TEXT
        );

        CREATE TABLE IF NOT EXISTS custody_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            event_type TEXT NOT NULL,
            card_serial TEXT,
            operator_name TEXT,
            station_id TEXT,
            scanner_id TEXT,
            printer_id TEXT,
            image_hash TEXT,
            details TEXT
        );

        CREATE TABLE IF NOT EXISTS offline_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            endpoint TEXT NOT NULL,
            method TEXT NOT NULL,
            payload TEXT NOT NULL,
            synced INTEGER DEFAULT 0,
            synced_at TEXT
        );

        CREATE TABLE IF NOT EXISTS scanner_quality (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            station_id TEXT,
            scanner_id TEXT,
            brightness REAL,
            contrast REAL,
            sharpness REAL,
            noise_level REAL,
            overall_score REAL,
            is_calibration INTEGER DEFAULT 0
        );
    """)
    _conn.commit()
    logger.info(f"Telemetry DB initialized at {_DB_PATH}")
    return _conn


# ---- Session Timing ----

@dataclass
class GradingSession:
    """Tracks timing for a single card through the grading pipeline."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    card_record_id: str = ""
    serial_number: str = ""
    operator_name: str = ""
    station_id: str = ""
    started_at: str = ""
    scan_started_at: str = ""
    scan_completed_at: str = ""
    grade_started_at: str = ""
    grade_completed_at: str = ""
    print_started_at: str = ""
    print_completed_at: str = ""
    nfc_started_at: str = ""
    nfc_completed_at: str = ""
    completed_at: str = ""
    total_seconds: float = 0.0
    status: str = "active"


_active_sessions: dict[str, GradingSession] = {}


def start_session(operator_name: str = "", station_id: str = "") -> GradingSession:
    """Start a new grading session timer."""
    session = GradingSession(
        operator_name=operator_name,
        station_id=station_id,
        started_at=datetime.now(timezone.utc).isoformat(),
    )
    _active_sessions[session.id] = session

    db = _get_db()
    db.execute(
        "INSERT INTO sessions (id, operator_name, station_id, started_at, status) VALUES (?, ?, ?, ?, ?)",
        (session.id, operator_name, station_id, session.started_at, "active"),
    )
    db.commit()
    return session


def update_session(session_id: str, **kwargs) -> Optional[GradingSession]:
    """Update session timing fields."""
    session = _active_sessions.get(session_id)
    if not session:
        return None

    for key, value in kwargs.items():
        if hasattr(session, key):
            setattr(session, key, value)

    db = _get_db()
    fields = ", ".join(f"{k} = ?" for k in kwargs)
    values = list(kwargs.values()) + [session_id]
    db.execute(f"UPDATE sessions SET {fields} WHERE id = ?", values)
    db.commit()
    return session


def complete_session(session_id: str) -> Optional[GradingSession]:
    """Mark a session as complete and calculate total time."""
    session = _active_sessions.pop(session_id, None)
    if not session:
        return None

    now = datetime.now(timezone.utc).isoformat()
    session.completed_at = now
    session.status = "completed"

    # Calculate total seconds
    try:
        start = datetime.fromisoformat(session.started_at)
        end = datetime.fromisoformat(now)
        session.total_seconds = (end - start).total_seconds()
    except Exception:
        pass

    db = _get_db()
    db.execute(
        "UPDATE sessions SET completed_at = ?, total_seconds = ?, status = ? WHERE id = ?",
        (now, session.total_seconds, "completed", session_id),
    )
    db.commit()
    return session


def get_productivity_stats(hours: int = 24) -> dict:
    """Get operator productivity stats for the last N hours."""
    db = _get_db()
    cutoff = datetime.now(timezone.utc).isoformat()

    rows = db.execute("""
        SELECT
            operator_name,
            COUNT(*) as total_cards,
            AVG(total_seconds) as avg_seconds,
            MIN(total_seconds) as fastest,
            MAX(total_seconds) as slowest,
            SUM(total_seconds) as total_time
        FROM sessions
        WHERE status = 'completed' AND completed_at IS NOT NULL
        GROUP BY operator_name
    """).fetchall()

    return {
        "operators": [dict(r) for r in rows],
        "total_completed": sum(r["total_cards"] for r in rows),
        "overall_avg_seconds": sum(r["avg_seconds"] or 0 for r in rows) / max(len(rows), 1),
    }


# ---- Metrics ----

def record_metric(metric_type: str, metric_name: str, value: float, metadata: dict = None, station_id: str = "") -> None:
    """Record a telemetry metric."""
    db = _get_db()
    db.execute(
        "INSERT INTO metrics (timestamp, metric_type, metric_name, value, metadata, station_id) VALUES (?, ?, ?, ?, ?, ?)",
        (datetime.now(timezone.utc).isoformat(), metric_type, metric_name, value,
         json.dumps(metadata) if metadata else None, station_id),
    )
    db.commit()


def get_metrics(metric_type: str = None, limit: int = 100) -> list[dict]:
    """Get recent metrics, optionally filtered by type."""
    db = _get_db()
    if metric_type:
        rows = db.execute(
            "SELECT * FROM metrics WHERE metric_type = ? ORDER BY timestamp DESC LIMIT ?",
            (metric_type, limit),
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM metrics ORDER BY timestamp DESC LIMIT ?", (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


# ---- Chain of Custody ----

def log_custody_event(
    event_type: str,
    card_serial: str = "",
    operator_name: str = "",
    station_id: str = "",
    scanner_id: str = "",
    printer_id: str = "",
    image_hash: str = "",
    details: str = "",
) -> None:
    """Log a chain of custody event for a card."""
    db = _get_db()
    db.execute(
        """INSERT INTO custody_log
        (timestamp, event_type, card_serial, operator_name, station_id, scanner_id, printer_id, image_hash, details)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (datetime.now(timezone.utc).isoformat(), event_type, card_serial,
         operator_name, station_id, scanner_id, printer_id, image_hash, details),
    )
    db.commit()


def get_custody_chain(card_serial: str) -> list[dict]:
    """Get the full chain of custody for a card."""
    db = _get_db()
    rows = db.execute(
        "SELECT * FROM custody_log WHERE card_serial = ? ORDER BY timestamp",
        (card_serial,),
    ).fetchall()
    return [dict(r) for r in rows]


# ---- Scanner Quality ----

def record_scan_quality(
    brightness: float, contrast: float, sharpness: float,
    noise_level: float, station_id: str = "", scanner_id: str = "",
    is_calibration: bool = False,
) -> dict:
    """Record scanner quality metrics from a scan."""
    overall = (brightness * 0.2 + contrast * 0.3 + sharpness * 0.35 + (100 - noise_level) * 0.15)

    db = _get_db()
    db.execute(
        """INSERT INTO scanner_quality
        (timestamp, station_id, scanner_id, brightness, contrast, sharpness, noise_level, overall_score, is_calibration)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (datetime.now(timezone.utc).isoformat(), station_id, scanner_id,
         brightness, contrast, sharpness, noise_level, overall, int(is_calibration)),
    )
    db.commit()

    # Check for quality degradation
    recent = db.execute(
        "SELECT AVG(overall_score) as avg_score FROM scanner_quality WHERE is_calibration = 0 ORDER BY timestamp DESC LIMIT 10",
    ).fetchone()

    baseline = db.execute(
        "SELECT AVG(overall_score) as avg_score FROM scanner_quality WHERE is_calibration = 1 ORDER BY timestamp DESC LIMIT 5",
    ).fetchone()

    result = {
        "overall_score": round(overall, 1),
        "brightness": round(brightness, 1),
        "contrast": round(contrast, 1),
        "sharpness": round(sharpness, 1),
        "noise_level": round(noise_level, 1),
        "warning": None,
    }

    if recent and baseline and recent["avg_score"] and baseline["avg_score"]:
        drop = baseline["avg_score"] - recent["avg_score"]
        if drop > 10:
            result["warning"] = f"Scanner quality dropped {drop:.0f}% from baseline — consider cleaning the glass"

    return result


def get_scanner_quality_trend(limit: int = 50) -> list[dict]:
    """Get recent scanner quality readings."""
    db = _get_db()
    rows = db.execute(
        "SELECT * FROM scanner_quality ORDER BY timestamp DESC LIMIT ?", (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


# ---- Offline Cache ----

def cache_for_sync(endpoint: str, method: str, payload: dict) -> None:
    """Cache a failed cloud API call for later sync."""
    db = _get_db()
    db.execute(
        "INSERT INTO offline_cache (created_at, endpoint, method, payload) VALUES (?, ?, ?, ?)",
        (datetime.now(timezone.utc).isoformat(), endpoint, method, json.dumps(payload)),
    )
    db.commit()
    logger.info(f"Cached offline: {method} {endpoint}")


def get_pending_sync() -> list[dict]:
    """Get all unsynced cached items."""
    db = _get_db()
    rows = db.execute(
        "SELECT * FROM offline_cache WHERE synced = 0 ORDER BY created_at", ()
    ).fetchall()
    return [dict(r) for r in rows]


def mark_synced(cache_id: int) -> None:
    """Mark a cached item as synced."""
    db = _get_db()
    db.execute(
        "UPDATE offline_cache SET synced = 1, synced_at = ? WHERE id = ?",
        (datetime.now(timezone.utc).isoformat(), cache_id),
    )
    db.commit()


def sync_cached_items(cloud_url: str) -> dict:
    """Attempt to sync all cached items to the cloud."""
    pending = get_pending_sync()
    if not pending:
        return {"synced": 0, "failed": 0}

    synced = 0
    failed = 0

    try:
        import httpx
        client = httpx.Client(timeout=10.0)

        for item in pending:
            try:
                url = f"{cloud_url}{item['endpoint']}"
                payload = json.loads(item["payload"])

                if item["method"] == "POST":
                    resp = client.post(url, json=payload)
                elif item["method"] == "PUT":
                    resp = client.put(url, json=payload)
                else:
                    continue

                if resp.status_code < 400:
                    mark_synced(item["id"])
                    synced += 1
                else:
                    failed += 1
            except Exception:
                failed += 1

        client.close()
    except Exception as e:
        logger.error(f"Sync failed: {e}")

    return {"synced": synced, "failed": failed, "remaining": len(pending) - synced}
