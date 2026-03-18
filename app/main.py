"""RKT Grading Station - Desktop Application Launcher.

Starts FastAPI on a background thread and opens a pywebview window.
"""

import logging
import sys
import threading
import time
from pathlib import Path

# Ensure app is importable
sys.path.insert(0, str(Path(__file__).parent.parent))


def start_server(port: int, host: str = "127.0.0.1") -> None:
    """Start the FastAPI server in the current thread."""
    import uvicorn
    from app.api import create_app

    app = create_app()
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="warning",
        access_log=False,
    )


def main() -> None:
    """Main entry point for the RKT Grading Station desktop application."""
    from app.config import settings
    from app.core.logging_config import setup_logging

    # Initialize logging first
    setup_logging(settings.log_level, settings.data_dir)
    logger = logging.getLogger(__name__)
    logger.info("=" * 60)
    logger.info("RKT Grading Station starting")
    logger.info(f"Environment: {settings.env}")
    logger.info(f"Data directory: {settings.data_dir}")
    logger.info(f"Server port: {settings.server_port}")
    logger.info("=" * 60)

    # Cloud mode: run server directly (no pywebview, bind to all interfaces)
    if settings.mode == "cloud":
        logger.info("Cloud mode — starting server on 0.0.0.0:%d", settings.server_port)
        start_server(settings.server_port, host="0.0.0.0")
        return

    # Agent mode: different port, no pywebview
    if settings.mode == "agent":
        logger.info("Agent mode — starting hardware agent on 0.0.0.0:8742")
        start_server(8742, host="0.0.0.0")
        return

    # Desktop mode: server in background thread, pywebview in foreground
    server_thread = threading.Thread(
        target=start_server,
        args=(settings.server_port,),
        daemon=True,
        name="rkt-api-server",
    )
    server_thread.start()

    # Wait for server to be ready
    import httpx
    server_url = f"http://127.0.0.1:{settings.server_port}"
    for attempt in range(30):
        try:
            resp = httpx.get(f"{server_url}/api/dashboard/summary", timeout=1.0)
            if resp.status_code == 200:
                logger.info(f"Server ready at {server_url}")
                break
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout, httpx.TimeoutException):
            pass
        time.sleep(0.3)
    else:
        logger.error("Server failed to start within timeout")
        sys.exit(1)

    # Create and start pywebview window
    try:
        import webview

        window = webview.create_window(
            title="RKT Grading Station",
            url=server_url,
            width=settings.window_width,
            height=settings.window_height,
            resizable=True,
            min_size=(1024, 700),
            confirm_close=True,
            text_select=True,
        )
        logger.info("Opening desktop window")
        webview.start(debug=settings.debug)
    except Exception as e:
        logger.error(f"pywebview failed: {e}")
        logger.info(f"You can still access the app at {server_url}")
        logger.info("Press Ctrl+C to stop the server")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass

    logger.info("RKT Grading Station shutting down")


if __name__ == "__main__":
    main()
