"""Database backup and restore routes."""

import logging
import sqlite3
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


def _backup_dir() -> Path:
    d = Path(settings.data_dir) / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


@router.post("/create")
async def create_backup():
    """Create a backup of the database using SQLite's online backup API.

    Uses VACUUM INTO which is safe for concurrent readers/writers, unlike
    a raw file copy that can produce a corrupt backup mid-transaction.
    """
    db_path = Path(settings.data_dir) / "db" / "rkt_grading.db"
    if not db_path.exists():
        raise HTTPException(status_code=404, detail="Database file not found")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"rkt_backup_{timestamp}.db"
    backup_path = _backup_dir() / backup_name

    try:
        src = sqlite3.connect(str(db_path))
        dst = sqlite3.connect(str(backup_path))
        with dst:
            src.backup(dst)
        dst.close()
        src.close()
    except Exception as e:
        # Clean up partial backup on failure
        if backup_path.exists():
            backup_path.unlink()
        logger.error("Backup failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Backup failed: {e}")

    size = backup_path.stat().st_size

    logger.info("Backup created: %s (%d bytes)", backup_name, size)
    return {
        "status": "created",
        "filename": backup_name,
        "size_bytes": size,
    }


@router.get("/list")
async def list_backups():
    """List all available backups."""
    backup_dir = _backup_dir()
    backups = []
    for f in sorted(backup_dir.glob("rkt_backup_*.db"), reverse=True):
        backups.append({
            "filename": f.name,
            "size_bytes": f.stat().st_size,
            "created_at": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
        })
    return {"backups": backups}


@router.get("/download/{filename}")
async def download_backup(filename: str):
    """Download a specific backup file."""
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    backup_path = _backup_dir() / filename
    if not backup_path.exists():
        raise HTTPException(status_code=404, detail="Backup not found")
    return FileResponse(str(backup_path), filename=filename, media_type="application/octet-stream")


@router.delete("/{filename}")
async def delete_backup(filename: str):
    """Delete a specific backup."""
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    backup_path = _backup_dir() / filename
    if not backup_path.exists():
        raise HTTPException(status_code=404, detail="Backup not found")
    backup_path.unlink()
    return {"status": "deleted", "filename": filename}
