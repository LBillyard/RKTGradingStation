"""Build the RKT Station Agent as a standalone Windows executable.

Usage:
    python build_agent.py

Creates a clean venv with only agent dependencies (no ML libs),
then builds with PyInstaller.

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
    venv_dir = Path("build_venv")

    # Clean previous builds
    for d in [dist_dir / "RKTStationAgent", build_dir / "RKTStationAgent"]:
        if d.exists():
            shutil.rmtree(d)
    old_exe = dist_dir / "RKTStationAgent.exe"
    if old_exe.exists():
        old_exe.unlink()

    # Remove old spec file
    spec_file = Path("RKTStationAgent.spec")
    if spec_file.exists():
        spec_file.unlink()

    # Step 1: Create a clean venv with only agent deps
    print("\n=== Creating clean build venv ===")
    if venv_dir.exists():
        shutil.rmtree(venv_dir)

    subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)

    venv_python = str(venv_dir / "Scripts" / "python.exe")
    venv_pip = str(venv_dir / "Scripts" / "pip.exe")

    print("Installing agent dependencies (no ML libs)...")
    subprocess.run(
        [venv_python, "-m", "pip", "install", "--upgrade", "pip", "-q"],
        check=False,  # pip upgrade can fail, that's ok
    )
    subprocess.run(
        [venv_python, "-m", "pip", "install", "-r", "agent_requirements.txt", "-q"],
        check=True,
    )
    subprocess.run(
        [venv_python, "-m", "pip", "install", "pyinstaller", "-q"],
        check=True,
    )

    # Step 2: Build with PyInstaller from the clean venv
    print("\n=== Building with PyInstaller ===")
    cmd = [
        venv_python, "-m", "PyInstaller",
        "--name", "RKTStationAgent",
        "--onefile",
        "--console",
        "--icon", "rkt_agent.ico",
        # Bundle the icon file
        "--add-data", "rkt_agent.ico;.",
        "--add-data", "installer/drivers/canon-lide400-driver.exe;drivers",
        # Include app package as data
        "--add-data", "app;app",
        "--add-data", "agent_version.py;.",
        "--add-data", "agent.env.example;.",
        # Hidden imports for uvicorn internals
        "--hidden-import", "uvicorn.logging",
        "--hidden-import", "uvicorn.protocols.http",
        "--hidden-import", "uvicorn.protocols.http.auto",
        "--hidden-import", "uvicorn.protocols.http.h11_impl",
        "--hidden-import", "uvicorn.protocols.websockets",
        "--hidden-import", "uvicorn.protocols.websockets.auto",
        "--hidden-import", "uvicorn.lifespan",
        "--hidden-import", "uvicorn.lifespan.on",
        "--hidden-import", "uvicorn.lifespan.off",
        # App imports
        "--hidden-import", "app.api",
        "--hidden-import", "app.api.routes_agent_hw",
        "--hidden-import", "app.config",
        "--hidden-import", "app.core.events",
        "--hidden-import", "app.core.logging_config",
        "--hidden-import", "app.db.database",
        "--hidden-import", "app.middleware.security",
        "--hidden-import", "app.models.scan",
        "--hidden-import", "app.models.card",
        "--hidden-import", "app.models.ocr",
        "--hidden-import", "app.models.grading",
        "--hidden-import", "app.models.authenticity",
        "--hidden-import", "app.models.security",
        "--hidden-import", "app.models.hardware",
        "--hidden-import", "app.models.admin",
        "--hidden-import", "app.models.reference",
        "--hidden-import", "app.models.operator",
        "--hidden-import", "app.models.slab",
        "--hidden-import", "app.models.station",
        "--hidden-import", "app.services.scanner.mock_scanner",
        "--hidden-import", "app.services.scanner.wia_scanner",
        "--hidden-import", "app.services.printer.mock_printer",
        "--hidden-import", "app.services.printer.gdi_printer",
        "--hidden-import", "app.services.printer.renderer",
        "--hidden-import", "app.services.nfc.mock_nfc",
        "--hidden-import", "app.services.nfc.reader",
        "--hidden-import", "app.services.nfc.ntag213",
        "--hidden-import", "app.services.nfc.ntag424",
        "--hidden-import", "app.services.nfc.crypto_nfc",
        "--hidden-import", "app.services.storage",
        # Windows hardware
        "--hidden-import", "comtypes",
        "--hidden-import", "comtypes.client",
        "--hidden-import", "win32print",
        "--hidden-import", "win32ui",
        "--hidden-import", "win32con",
        "--hidden-import", "smartcard",
        "--hidden-import", "smartcard.System",
        "--hidden-import", "pystray",
        "--hidden-import", "pystray._win32",
        # Exclude heavy packages the agent doesn't need
        "--exclude-module", "torch",
        "--exclude-module", "torchvision",
        "--exclude-module", "paddleocr",
        "--exclude-module", "paddlepaddle",
        "--exclude-module", "paddlex",
        "--exclude-module", "scipy",
        "--exclude-module", "pandas",
        "--exclude-module", "matplotlib",
        "--exclude-module", "numpy",
        "--exclude-module", "cv2",
        "--exclude-module", "opencv",
        "--exclude-module", "sklearn",
        "--exclude-module", "tensorflow",
        "--exclude-module", "transformers",
        "--exclude-module", "datasets",
        "--exclude-module", "huggingface_hub",
        "--exclude-module", "boto3",
        "--exclude-module", "botocore",
        "--exclude-module", "pytest",
        "--exclude-module", "tkinter",
        "--exclude-module", "_tkinter",
        # Entry point
        "agent_main.py",
    ]

    result = subprocess.run(cmd, capture_output=False)

    if result.returncode != 0:
        print("\nBuild FAILED!")
        sys.exit(1)

    exe_path = dist_dir / "RKTStationAgent.exe"
    if exe_path.exists():
        size_mb = exe_path.stat().st_size / (1024 * 1024)

        print(f"\n{'='*50}")
        print(f"BUILD SUCCESS!")
        print(f"  Exe:     {exe_path}")
        print(f"  Size:    {size_mb:.1f} MB (single file, no dependencies needed)")
        print(f"  Version: {AGENT_VERSION}")
        print(f"{'='*50}")
    else:
        print("Build produced no output!")
        sys.exit(1)

    # Clean up build venv
    print("\nCleaning up build venv...")
    shutil.rmtree(venv_dir, ignore_errors=True)
    print("Done!")


if __name__ == "__main__":
    build()
