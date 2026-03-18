"""RKT Station Agent — Local hardware bridge for the cloud-hosted grading station.

Runs as a small background service on Windows PCs with connected hardware
(scanner, printer, NFC reader). The browser-based UI at rktgradingstation.co.uk
communicates with this agent via localhost:8742 for hardware operations.

Usage:
    python agent_main.py          # Run with console output
    python agent_main.py --tray   # Run with system tray icon (background)
"""

import io
import logging
import os
import sys
import threading
from pathlib import Path

# Fix for PyInstaller --noconsole: sys.stdout/stderr are None which crashes uvicorn logging
if sys.stdout is None:
    sys.stdout = io.StringIO()
if sys.stderr is None:
    sys.stderr = io.StringIO()

# Ensure app is importable
if getattr(sys, 'frozen', False):
    # PyInstaller: use the exe's directory
    sys.path.insert(0, str(Path(sys.executable).parent))
else:
    sys.path.insert(0, str(Path(__file__).parent))

from agent_version import AGENT_VERSION, AGENT_NAME, check_for_update, auto_update


def main() -> None:
    """Start the RKT Station Agent."""
    os.environ.setdefault("RKT_MODE", "agent")

    from app.config import settings
    from app.core.logging_config import setup_logging

    setup_logging(settings.log_level, settings.data_dir)
    logger = logging.getLogger(__name__)
    logger.info("=" * 50)
    logger.info(f"{AGENT_NAME} v{AGENT_VERSION}")
    logger.info(f"Station ID: {settings.station_id or 'not set'}")
    logger.info(f"Scanner mock: {settings.scanner.mock_mode}")
    logger.info(f"Printer mock: {settings.printer.mock_mode}")
    logger.info(f"NFC mock: {settings.nfc.mock_mode}")
    logger.info("=" * 50)

    # Check for updates on startup
    logger.info("Checking for updates...")
    update_info = check_for_update()
    if update_info:
        logger.info(
            f"Update available: v{update_info['latest_version']} "
            f"(current: v{AGENT_VERSION})"
        )
        if update_info.get("mandatory"):
            auto_update(update_info)
        else:
            logger.info("Optional update — will apply on next restart")
    else:
        logger.info(f"Agent is up to date (v{AGENT_VERSION})")

    use_tray = "--tray" in sys.argv

    if use_tray:
        server_thread = threading.Thread(
            target=_run_server,
            args=(settings,),
            daemon=True,
            name="agent-server",
        )
        server_thread.start()
        _run_tray(settings, logger)
    else:
        _run_server(settings)


def _run_server(settings) -> None:
    """Start the agent FastAPI server."""
    import uvicorn
    from app.api import create_app

    app = create_app()
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8742,
        log_level="info",
        access_log=False,
    )


def _run_tray(settings, logger) -> None:
    """Run system tray icon (blocks until quit)."""
    try:
        import pystray
        from PIL import Image as PilImage

        icon_img = PilImage.new("RGB", (64, 64), color=(34, 139, 34))

        def on_quit(icon, item):
            icon.stop()

        def on_status(icon, item):
            logger.info("Agent is running on localhost:8742")

        menu = pystray.Menu(
            pystray.MenuItem(f"{AGENT_NAME} v{AGENT_VERSION}", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Status: Online", on_status),
            pystray.MenuItem(f"Station: {settings.station_id or 'default'}", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", on_quit),
        )

        icon = pystray.Icon("rkt-agent", icon_img, f"{AGENT_NAME} v{AGENT_VERSION}", menu)
        logger.info("System tray icon active")
        icon.run()
    except ImportError:
        logger.warning("pystray not installed — running without system tray")
        logger.info("Agent running on localhost:8742. Press Ctrl+C to stop.")
        try:
            while True:
                import time
                time.sleep(1)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
