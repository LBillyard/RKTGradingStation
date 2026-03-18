"""File system utility functions."""

import logging
import shutil
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def ensure_directory(path: str | Path) -> Path:
    """Ensure a directory exists, creating it if necessary."""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_filename(name: str) -> str:
    """Sanitize a string for use as a filename."""
    keepchars = (' ', '.', '_', '-')
    return "".join(c for c in name if c.isalnum() or c in keepchars).strip()


def get_file_size(path: str | Path) -> Optional[int]:
    """Get file size in bytes, or None if file doesn't exist."""
    try:
        return Path(path).stat().st_size
    except (OSError, FileNotFoundError):
        return None


def copy_file(src: str | Path, dst: str | Path) -> Path:
    """Copy a file, creating destination directory if needed."""
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    return Path(shutil.copy2(str(src), str(dst)))
