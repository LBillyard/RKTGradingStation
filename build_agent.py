"""Build the RKT Station Agent as a standalone Windows executable.

Usage:
    python build_agent.py

Requirements:
    pip install pyinstaller

Output:
    dist/RKTStationAgent/RKTStationAgent.exe
"""

import subprocess
import sys
import shutil
from pathlib import Path

from agent_version import AGENT_VERSION, AGENT_NAME


def build():
    print(f"Building {AGENT_NAME} v{AGENT_VERSION}...")

    dist_dir = Path("dist")
    build_dir = Path("build")

    # Clean previous builds
    for d in [dist_dir / "RKTStationAgent", build_dir / "RKTStationAgent"]:
        if d.exists():
            shutil.rmtree(d)

    # PyInstaller command
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "RKTStationAgent",
        "--onedir",
        "--noconsole",
        "--icon", "NONE",
        # Include agent modules
        "--add-data", "agent_version.py;.",
        "--add-data", "agent.env.example;.",
        # Include app package
        "--add-data", "app;app",
        # Hidden imports that PyInstaller might miss
        "--hidden-import", "uvicorn.logging",
        "--hidden-import", "uvicorn.protocols.http",
        "--hidden-import", "uvicorn.protocols.http.auto",
        "--hidden-import", "uvicorn.protocols.websockets",
        "--hidden-import", "uvicorn.protocols.websockets.auto",
        "--hidden-import", "uvicorn.lifespan",
        "--hidden-import", "uvicorn.lifespan.on",
        "--hidden-import", "app.api",
        "--hidden-import", "app.api.routes_agent_hw",
        "--hidden-import", "app.config",
        "--hidden-import", "app.services.scanner.mock_scanner",
        "--hidden-import", "app.services.printer.mock_printer",
        "--hidden-import", "app.services.nfc.mock_nfc",
        "--hidden-import", "pystray",
        "--hidden-import", "comtypes",
        "--hidden-import", "win32print",
        "--hidden-import", "win32ui",
        "--hidden-import", "win32con",
        "--hidden-import", "smartcard",
        # Entry point
        "agent_main.py",
    ]

    print(f"Running: {' '.join(cmd[:6])}...")
    result = subprocess.run(cmd, capture_output=False)

    if result.returncode != 0:
        print("Build FAILED!")
        sys.exit(1)

    exe_path = dist_dir / "RKTStationAgent" / "RKTStationAgent.exe"
    if exe_path.exists():
        size_mb = exe_path.stat().st_size / (1024 * 1024)
        print(f"\nBuild SUCCESS!")
        print(f"  Output: {exe_path}")
        print(f"  Size: {size_mb:.1f} MB")
        print(f"  Version: {AGENT_VERSION}")

        # Copy agent.env.example
        shutil.copy2("agent.env.example", dist_dir / "RKTStationAgent" / "agent.env.example")
        print(f"  Config: agent.env.example copied")

        # Write version file
        (dist_dir / "RKTStationAgent" / "VERSION").write_text(AGENT_VERSION)
        print(f"  Version file written")
    else:
        print("Build produced no output!")
        sys.exit(1)


if __name__ == "__main__":
    build()
