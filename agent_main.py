"""RKT Station Agent — Local hardware bridge for the cloud-hosted grading station.

Runs as a small background service on Windows PCs with connected hardware
(scanner, printer, NFC reader). The browser-based UI at rktgradingstation.co.uk
communicates with this agent via localhost:8742 for hardware operations.

Usage:
    python agent_main.py          # Run with console output
    python agent_main.py --tray   # Run with system tray icon (background)
"""

import logging
import sys
import threading
from pathlib import Path

# Ensure app is importable
sys.path.insert(0, str(Path(__file__).parent))


def main() -> None:
    """Start the RKT Station Agent."""
    import os
    os.environ.setdefault("RKT_MODE", "agent")

    from app.config import settings
    from app.core.logging_config import setup_logging

    setup_logging(settings.log_level, settings.data_dir)
    logger = logging.getLogger(__name__)
    logger.info("=" * 50)
    logger.info("RKT Station Agent starting")
    logger.info(f"Station ID: {settings.station_id or 'not set'}")
    logger.info(f"Scanner mock: {settings.scanner.mock_mode}")
    logger.info(f"Printer mock: {settings.printer.mock_mode}")
    logger.info(f"NFC mock: {settings.nfc.mock_mode}")
    logger.info("=" * 50)

    use_tray = "--tray" in sys.argv

    if use_tray:
        # Run server in background, system tray in foreground
        server_thread = threading.Thread(
            target=_run_server,
            args=(settings,),
            daemon=True,
            name="agent-server",
        )
        server_thread.start()
        _run_tray(settings, logger)
    else:
        # Run server directly (console mode)
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

        # Create a simple icon (green square with RKT text)
        icon_img = PilImage.new("RGB", (64, 64), color=(34, 139, 34))

        def on_quit(icon, item):
            icon.stop()

        def on_status(icon, item):
            logger.info("Agent is running on localhost:8742")

        menu = pystray.Menu(
            pystray.MenuItem("RKT Station Agent", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Status: Online", on_status),
            pystray.MenuItem(f"Station: {settings.station_id or 'default'}", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", on_quit),
        )

        icon = pystray.Icon("rkt-agent", icon_img, "RKT Station Agent", menu)
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
