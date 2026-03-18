"""Mock scanner for development and testing."""

import glob
import logging
import time
from pathlib import Path
from typing import List

from PIL import Image

from .base import BaseScanner, ScannerDevice, ScanResult

logger = logging.getLogger(__name__)


class MockScanner(BaseScanner):
    def __init__(self, mock_dir: str = "data/scans/mock"):
        self.mock_dir = Path(mock_dir)
        self._connected = False
        self._device_id = "mock_scanner_001"
        self._scan_index = 0

    def list_devices(self) -> List[ScannerDevice]:
        return [ScannerDevice(
            device_id=self._device_id,
            name="Mock Scanner (Development)",
            manufacturer="RKT Dev",
            is_connected=self._connected,
        )]

    def connect(self, device_id: str = None) -> bool:
        self._connected = True
        logger.info("Mock scanner connected")
        return True

    def disconnect(self) -> None:
        self._connected = False
        logger.info("Mock scanner disconnected")

    def is_connected(self) -> bool:
        return self._connected

    def scan(self, dpi: int = 600, color_mode: str = "RGB") -> ScanResult:
        if not self._connected:
            self.connect()

        # Find available images
        patterns = ["*.jpg", "*.jpeg", "*.png", "*.bmp", "*.tiff"]
        image_files = []
        for pattern in patterns:
            image_files.extend(self.mock_dir.glob(pattern))

        if not image_files:
            # Generate a blank card-sized image if no mock images available
            logger.warning("No mock images found, generating blank card image")
            w, h = int(2.5 * dpi), int(3.5 * dpi)
            img = Image.new("RGB", (w, h), color=(245, 245, 245))
            return ScanResult(image=img, dpi=dpi, device_id=self._device_id, scan_time_ms=500)

        # Cycle through available images
        image_files.sort(key=lambda f: f.name)
        file_path = image_files[self._scan_index % len(image_files)]
        self._scan_index += 1

        # Simulate scan delay
        delay = 0.5 + (hash(str(file_path)) % 1000) / 1000.0
        logger.info(f"Mock scanning: {file_path.name} (simulated {delay:.1f}s delay)")
        time.sleep(min(delay, 1.5))

        with Image.open(file_path) as _img:
            img = _img.convert("RGB")
        start = time.perf_counter()
        scan_time = int((time.perf_counter() - start) * 1000 + delay * 1000)

        return ScanResult(
            image=img,
            dpi=dpi,
            device_id=self._device_id,
            scan_time_ms=scan_time,
        )
