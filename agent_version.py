"""RKT Station Agent version and auto-update system."""

import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# Bump this on each release
AGENT_VERSION = "1.4.0"
AGENT_NAME = "RKT Station Agent"

# Cloud endpoint for version checks
DEFAULT_UPDATE_URL = "https://rgs.rktgrading.com/api/agent/version"


def get_version() -> str:
    """Return the current agent version."""
    return AGENT_VERSION


def check_for_update(update_url: str = DEFAULT_UPDATE_URL) -> dict | None:
    """Check the cloud server for a newer agent version.

    Returns dict with version info if update available, None if up to date.
    """
    try:
        import httpx
        resp = httpx.get(update_url, timeout=10.0)
        resp.raise_for_status()
        data = resp.json()

        latest = data.get("latest_version", AGENT_VERSION)
        if _version_newer(latest, AGENT_VERSION):
            return {
                "current_version": AGENT_VERSION,
                "latest_version": latest,
                "download_url": data.get("download_url", ""),
                "release_notes": data.get("release_notes", ""),
                "mandatory": data.get("mandatory", False),
            }
        return None
    except Exception as e:
        logger.debug(f"Update check failed: {e}")
        return None


def _version_newer(latest: str, current: str) -> bool:
    """Compare semver strings. Returns True if latest > current."""
    try:
        latest_parts = [int(x) for x in latest.split(".")]
        current_parts = [int(x) for x in current.split(".")]
        return latest_parts > current_parts
    except (ValueError, AttributeError):
        return False


def auto_update(update_info: dict) -> bool:
    """Download and apply an agent update.

    For PyInstaller builds: downloads new exe, replaces current, restarts.
    For dev mode: just logs the availability.
    """
    download_url = update_info.get("download_url")
    if not download_url:
        logger.warning("No download URL in update info")
        return False

    # Only auto-update if running as a frozen PyInstaller exe
    if not getattr(sys, 'frozen', False):
        logger.info(
            f"Update available: {update_info['latest_version']} "
            f"(current: {AGENT_VERSION}). Running in dev mode — skipping auto-update."
        )
        return False

    try:
        import httpx

        logger.info(f"Downloading agent update v{update_info['latest_version']}...")
        with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as tmp:
            with httpx.stream("GET", download_url, follow_redirects=True, timeout=120.0) as resp:
                resp.raise_for_status()
                for chunk in resp.iter_bytes(chunk_size=8192):
                    tmp.write(chunk)
            tmp_path = tmp.name

        # Verify download integrity via SHA-256
        expected_hash = update_info.get("sha256")
        computed_hash = hashlib.sha256(Path(tmp_path).read_bytes()).hexdigest()
        if expected_hash:
            if computed_hash != expected_hash:
                logger.error(
                    "Update integrity check failed! "
                    f"Expected {expected_hash}, got {computed_hash}"
                )
                os.unlink(tmp_path)
                return False
            logger.info("Update integrity verified (SHA-256 match)")
        else:
            logger.warning(
                "No SHA-256 hash provided by server — skipping integrity check"
            )

        # Replace current exe with new one
        current_exe = sys.executable
        backup_path = current_exe + ".bak"

        # Rename current → backup, new → current
        if os.path.exists(backup_path):
            os.remove(backup_path)
        os.rename(current_exe, backup_path)
        shutil.move(tmp_path, current_exe)

        logger.info(f"Update applied. Restarting agent...")

        # Restart the process
        subprocess.Popen([current_exe] + sys.argv[1:])
        sys.exit(0)

    except Exception as e:
        logger.error(f"Auto-update failed: {e}")
        return False
