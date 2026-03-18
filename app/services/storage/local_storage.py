"""Local filesystem storage backend — serves files via FastAPI /data/ mount."""

import logging
import shutil
from pathlib import Path

from app.services.storage.base import BaseStorage

logger = logging.getLogger(__name__)


class LocalStorage(BaseStorage):
    """Store files on the local filesystem under data_dir."""

    def __init__(self, data_dir: str = "data"):
        self._data_dir = Path(data_dir)

    def upload(self, file_path: str, key: str) -> str:
        """Copy file to the data directory under the given key."""
        src = Path(file_path)
        dest = self._data_dir / key
        dest.parent.mkdir(parents=True, exist_ok=True)

        if src.resolve() != dest.resolve():
            shutil.copy2(src, dest)

        logger.debug(f"LocalStorage: stored {key}")
        return key

    def get_url(self, key: str) -> str:
        """Return /data/... URL for the file."""
        if not key:
            return ""
        # If it's already an absolute path, try to make it relative
        p = Path(key)
        if p.is_absolute():
            try:
                key = str(p.relative_to(self._data_dir.resolve()))
            except ValueError:
                try:
                    key = str(p.relative_to(self._data_dir))
                except ValueError:
                    pass
        # Normalize to forward slashes
        return f"/data/{key.replace(chr(92), '/')}"

    def delete(self, key: str) -> None:
        """Delete file from local storage."""
        path = self._data_dir / key
        if path.exists():
            path.unlink()
            logger.debug(f"LocalStorage: deleted {key}")

    def exists(self, key: str) -> bool:
        """Check if file exists locally."""
        return (self._data_dir / key).exists()
