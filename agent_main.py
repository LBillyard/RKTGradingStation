"""RKT Station Agent — Local hardware bridge for the cloud-hosted grading station.

Runs as a system tray application on Windows PCs with connected hardware
(scanner, printer, NFC reader). The browser-based UI at rgs.rktgrading.com
communicates with this agent via localhost:8742 for hardware operations.

Usage:
    RKTStationAgent.exe              # Normal launch (tray mode)
    RKTStationAgent.exe --console    # Debug mode with console output
"""

import asyncio
import io
import logging
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

# Fix Windows asyncio: ProactorEventLoop (default on 3.11+) breaks uvicorn HTTP handling.
# Must be set before any event loop is created.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Fix for PyInstaller --noconsole: sys.stdout/stderr are None
if sys.stdout is None:
    sys.stdout = io.StringIO()
if sys.stderr is None:
    sys.stderr = io.StringIO()

# Ensure app is importable
if getattr(sys, 'frozen', False):
    sys.path.insert(0, str(Path(sys.executable).parent))
else:
    sys.path.insert(0, str(Path(__file__).parent))

from agent_version import AGENT_VERSION, AGENT_NAME, check_for_update, auto_update

# Globals for tray status
_server_running = False
_cloud_url = "https://rgs.rktgrading.com"


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
    logger.info("=" * 50)

    # Install Canon scanner driver if needed
    _install_scanner_driver_if_needed(logger)

    # Ensure auto-start on Windows boot
    _ensure_startup_entry()

    # Check for updates
    logger.info("Checking for updates...")
    update_info = check_for_update()
    if update_info:
        logger.info(f"Update available: v{update_info['latest_version']}")
        _show_notification(
            "Update Available",
            f"RKT Station Agent v{update_info['latest_version']} is available. Updating..."
        )
        auto_update(update_info)
    else:
        logger.info(f"Agent is up to date (v{AGENT_VERSION})")

    console_mode = "--console" in sys.argv

    # Pre-import agent routes BEFORE uvicorn starts its event loop.
    # This prevents asyncio import side-effects from interfering with uvicorn.
    if settings.mode == "agent":
        import app.api.routes_agent_hw  # noqa: F401

    # Always run server directly — tray disabled for now to fix PyInstaller compatibility
    global _server_running
    _server_running = True
    _run_server(settings)


def _run_server(settings) -> None:
    """Start the agent FastAPI server."""
    import uvicorn

    if settings.mode == "agent":
        # Agent mode: build a minimal app directly to avoid create_app() deadlocks
        # on Windows (ProactorEventLoop + BaseHTTPMiddleware interaction)
        from fastapi import FastAPI
        from fastapi.middleware.cors import CORSMiddleware

        app = FastAPI(title="RKT Station Agent", version="1.0.0")
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["https://rgs.rktgrading.com", "http://localhost:8741", "http://127.0.0.1:8741"],
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
        )

        # Include agent hardware routes
        from app.api.routes_agent_hw import router as agent_hw_router
        app.include_router(agent_hw_router, prefix="/agent", tags=["Agent Hardware"])

        @app.get("/agent/status")
        def agent_status():
            return {"version": AGENT_VERSION, "mode": "agent", "station_id": settings.station_id or "not set"}
    else:
        from app.api import create_app
        app = create_app()

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=settings.server_port if settings.mode != "agent" else 8742,
        log_level="info",
        access_log=False,
    )


def _install_scanner_driver_if_needed(logger) -> None:
    """Check if Canon LiDE 400 ScanGear driver is installed, install if not."""
    try:
        # Check if the Canon ScanGear driver is already installed
        import subprocess
        result = subprocess.run(
            ["powershell", "-Command",
             "Get-WmiObject Win32_PnPSignedDriver | Where-Object { $_.DeviceName -like '*CanoScan*' -or $_.DeviceName -like '*LiDE 400*' } | Select-Object -First 1 DeviceName, DriverProviderName"],
            capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

        if "Canon" in result.stdout:
            logger.debug("Canon ScanGear driver already installed")
            return

        # Check if we have the bundled driver
        driver_path = None
        if getattr(sys, 'frozen', False):
            # PyInstaller: check in the extracted temp dir
            bundle_dir = Path(sys._MEIPASS) if hasattr(sys, '_MEIPASS') else Path(sys.executable).parent
            candidate = bundle_dir / "drivers" / "canon-lide400-driver.exe"
            if candidate.exists():
                driver_path = str(candidate)
        else:
            # Dev mode: check installer/drivers
            candidate = Path(__file__).parent / "installer" / "drivers" / "canon-lide400-driver.exe"
            if candidate.exists():
                driver_path = str(candidate)

        if not driver_path:
            logger.debug("Canon driver installer not bundled — skipping auto-install")
            return

        logger.info("Canon ScanGear driver not found — installing from bundled installer...")
        _show_notification("Installing Scanner Driver", "Installing Canon LiDE 400 driver. This may take a minute...")

        # Run the Canon installer
        # Canon's installer supports /s for silent mode
        proc = subprocess.run(
            [driver_path],
            timeout=300,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

        if proc.returncode == 0:
            logger.info("Canon ScanGear driver installed successfully")
            _show_notification("Driver Installed", "Canon LiDE 400 driver installed. Scanner is ready to use.")
        else:
            logger.warning(f"Canon driver installer returned code {proc.returncode}")

    except subprocess.TimeoutExpired:
        logger.warning("Canon driver installation timed out — may need manual install")
    except Exception as e:
        logger.debug(f"Scanner driver check/install skipped: {e}")


def _ensure_startup_entry() -> None:
    """Add the agent to Windows startup via registry."""
    if not getattr(sys, 'frozen', False):
        return  # Only for packaged exe

    try:
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        exe_path = sys.executable

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, "RKTStationAgent", 0, winreg.REG_SZ, f'"{exe_path}"')

        logging.getLogger(__name__).info("Startup entry registered")
    except Exception as e:
        logging.getLogger(__name__).debug(f"Could not set startup entry: {e}")


def _remove_startup_entry() -> None:
    """Remove the agent from Windows startup."""
    try:
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, "RKTStationAgent")
    except Exception:
        pass


def _show_notification(title: str, message: str) -> None:
    """Show a Windows toast notification."""
    try:
        from plyer import notification
        notification.notify(
            title=title,
            message=message,
            app_name=AGENT_NAME,
            timeout=5,
        )
    except ImportError:
        # Fallback: use powershell toast
        try:
            import subprocess
            # Sanitize inputs to prevent PowerShell injection
            _dangerous_chars = '"`$)()'
            safe_title = "".join(c for c in title if c not in _dangerous_chars)
            safe_message = "".join(c for c in message if c not in _dangerous_chars)
            ps_cmd = f'''
            [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
            $template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
            $textNodes = $template.GetElementsByTagName("text")
            $textNodes.Item(0).AppendChild($template.CreateTextNode("{safe_title}")) | Out-Null
            $textNodes.Item(1).AppendChild($template.CreateTextNode("{safe_message}")) | Out-Null
            $toast = [Windows.UI.Notifications.ToastNotification]::new($template)
            [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("RKT Station Agent").Show($toast)
            '''
            subprocess.Popen(
                ["powershell", "-WindowStyle", "Hidden", "-Command", ps_cmd],
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except Exception:
            pass
    except Exception:
        pass


def _get_hardware_summary() -> str:
    """Get a one-line hardware status summary."""
    try:
        import httpx
        r = httpx.get("http://localhost:8742/agent/status", timeout=2.0)
        data = r.json()
        hw = data.get("hardware", {})

        scanner = hw.get("scanner", {})
        printer = hw.get("printer", {})
        nfc = hw.get("nfc", {})

        parts = []
        s_devs = scanner.get("devices", [])
        if scanner.get("mock_mode"):
            parts.append("Scanner: Mock")
        elif s_devs:
            parts.append(f"Scanner: {len(s_devs)} found")
        else:
            parts.append("Scanner: None")

        p_list = printer.get("printers", [])
        if printer.get("mock_mode"):
            parts.append("Printer: Mock")
        elif p_list:
            parts.append(f"Printer: {p_list[0][:20]}")
        else:
            parts.append("Printer: None")

        n_list = nfc.get("readers", [])
        if nfc.get("mock_mode"):
            parts.append("NFC: Mock")
        elif n_list:
            parts.append("NFC: Connected")
        else:
            parts.append("NFC: None")

        return " | ".join(parts)
    except Exception:
        return "Status unavailable"


def _load_icon():
    """Load the rocket icon for the tray."""
    from PIL import Image as PilImage

    # Try to load from bundled icon file
    icon_paths = [
        Path(sys.executable).parent / "rkt_agent.ico" if getattr(sys, 'frozen', False) else None,
        Path(__file__).parent / "rkt_agent.ico",
        Path(__file__).parent / "app" / "ui" / "static" / "img" / "rkt-agent-icon.png",
    ]
    for p in icon_paths:
        if p and p.exists():
            return PilImage.open(str(p))

    # Fallback: generate a simple blue circle with R
    img = PilImage.new("RGBA", (64, 64), (0, 0, 0, 0))
    from PIL import ImageDraw
    draw = ImageDraw.Draw(img)
    draw.ellipse([4, 4, 60, 60], fill=(59, 130, 246, 255))
    try:
        from PIL import ImageFont
        font = ImageFont.truetype("arial.ttf", 32)
        draw.text((18, 10), "R", fill=(255, 255, 255), font=font)
    except Exception:
        pass
    return img


def _run_tray(settings, logger) -> None:
    """Run system tray icon with status menu."""
    try:
        import pystray
        from pystray import MenuItem, Menu

        icon_img = _load_icon()

        def on_open_grading(icon, item):
            webbrowser.open(_cloud_url)

        def on_open_status(icon, item):
            webbrowser.open("http://localhost:8742/agent/status")

        def on_check_update(icon, item):
            info = check_for_update()
            if info:
                logger.info(f"Update available: v{info['latest_version']}")
                _show_notification(
                    "Update Available",
                    f"v{info['latest_version']} is available (you have v{AGENT_VERSION}). Downloading..."
                )
                auto_update(info)
            else:
                _show_notification("Up to Date", f"RKT Station Agent v{AGENT_VERSION} is the latest version.")

        def on_toggle_startup(icon, item):
            # Toggle auto-start
            try:
                import winreg
                key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ) as key:
                    try:
                        winreg.QueryValueEx(key, "RKTStationAgent")
                        # Currently enabled, disable it
                        _remove_startup_entry()
                        logger.info("Auto-start disabled")
                    except FileNotFoundError:
                        # Currently disabled, enable it
                        _ensure_startup_entry()
                        logger.info("Auto-start enabled")
            except Exception:
                _ensure_startup_entry()

        def is_startup_enabled(item):
            try:
                import winreg
                key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ) as key:
                    winreg.QueryValueEx(key, "RKTStationAgent")
                    return True
            except Exception:
                return False

        def on_quit(icon, item):
            _remove_startup_entry() if False else None  # Don't remove on quit, only on toggle
            icon.stop()

        def get_status_text(item):
            return _get_hardware_summary()

        server_status = "Running on localhost:8742" if _server_running else "Starting..."
        station_label = f"Station: {settings.station_id}" if settings.station_id else "Station: Default"

        menu = Menu(
            MenuItem(f"{AGENT_NAME} v{AGENT_VERSION}", None, enabled=False),
            MenuItem(station_label, None, enabled=False),
            Menu.SEPARATOR,
            MenuItem(f"Server: {server_status}", None, enabled=False),
            MenuItem(lambda text: _get_hardware_summary(), None, enabled=False),
            Menu.SEPARATOR,
            MenuItem("Open Grading Station", on_open_grading, default=True),
            MenuItem("View Agent Status", on_open_status),
            MenuItem("Check for Updates", on_check_update),
            Menu.SEPARATOR,
            MenuItem("Start with Windows", on_toggle_startup, checked=is_startup_enabled),
            MenuItem("Quit", on_quit),
        )

        icon = pystray.Icon(
            "rkt-agent",
            icon_img,
            f"{AGENT_NAME} v{AGENT_VERSION}",
            menu,
        )
        logger.info("System tray active")
        icon.run()

    except ImportError:
        logger.warning("pystray not installed — running headless")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
