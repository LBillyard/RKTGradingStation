"""WIA (Windows Image Acquisition) scanner implementation using win32com."""

import logging
import os
import tempfile
import time
from typing import List, Optional

from PIL import Image

from .base import BaseScanner, ScannerDevice, ScanResult

logger = logging.getLogger(__name__)

# WIA Constants
WIA_DEVICE_TYPE_SCANNER = 1
WIA_IMG_FORMAT_BMP = "{B96B3CAB-0728-11D3-9D7B-0000F81EF32E}"
WIA_IMG_FORMAT_PNG = "{B96B3CAF-0728-11D3-9D7B-0000F81EF32E}"
WIA_IMG_FORMAT_JPEG = "{B96B3CAE-0728-11D3-9D7B-0000F81EF32E}"
WIA_IMG_FORMAT_TIFF = "{B96B3CB1-0728-11D3-9D7B-0000F81EF32E}"


class WIAScanner(BaseScanner):
    """Scanner using Windows Image Acquisition COM API via win32com.

    COM objects are created fresh per-call to handle cross-thread usage
    (FastAPI runs scan() in a thread via asyncio.to_thread).
    """

    def __init__(self):
        self._device_id: Optional[str] = None

    def _create_manager(self):
        """Create a fresh WIA DeviceManager (thread-safe)."""
        import pythoncom
        pythoncom.CoInitialize()
        import win32com.client
        return win32com.client.Dispatch("WIA.DeviceManager")

    def list_devices(self) -> List[ScannerDevice]:
        try:
            import pythoncom
            pythoncom.CoInitialize()
            manager = self._create_manager()
            devices = []
            for i in range(1, manager.DeviceInfos.Count + 1):
                info = manager.DeviceInfos.Item(i)
                if info.Type == WIA_DEVICE_TYPE_SCANNER:
                    try:
                        name = info.Properties("Name").Value
                    except Exception:
                        name = f"Scanner {i}"
                    try:
                        manufacturer = info.Properties("Manufacturer").Value
                    except Exception:
                        manufacturer = ""
                    devices.append(ScannerDevice(
                        device_id=info.DeviceID,
                        name=name,
                        manufacturer=manufacturer,
                        is_connected=True,
                    ))
            return devices
        except Exception as e:
            logger.error(f"Failed to list WIA devices: {e}")
            return []

    def connect(self, device_id: str) -> bool:
        """Store the device ID for later use. Actual COM connection happens in scan()."""
        self._device_id = device_id
        logger.info(f"Scanner target set: {device_id}")
        return True

    def disconnect(self) -> None:
        self._device_id = None
        logger.info("Scanner disconnected")

    def is_connected(self) -> bool:
        return self._device_id is not None

    def scan(self, dpi: int = 600, color_mode: str = "RGB") -> ScanResult:
        """Perform a scan. Creates fresh COM objects for thread safety."""
        if not self._device_id:
            raise RuntimeError("No scanner target set. Call connect() first.")

        start_time = time.perf_counter()

        # Initialize COM for this thread
        import pythoncom
        pythoncom.CoInitialize()
        try:
            import win32com.client
            manager = win32com.client.Dispatch("WIA.DeviceManager")

            # Find and connect to the device
            device = None
            for i in range(1, manager.DeviceInfos.Count + 1):
                info = manager.DeviceInfos.Item(i)
                if info.DeviceID == self._device_id:
                    device = info.Connect()
                    break

            if device is None:
                raise RuntimeError(f"Scanner device not found: {self._device_id}")

            item = device.Items(1)

            # Set DPI
            item.Properties("Horizontal Resolution").Value = dpi
            item.Properties("Vertical Resolution").Value = dpi

            logger.info(f"Scanning at {dpi}dpi, extent: {item.Properties('Horizontal Extent').Value}x{item.Properties('Vertical Extent').Value}")

            # Transfer image — try default format first, then specific formats
            image_file = None
            temp_ext = ".bmp"

            # Try 1: Default format (no format GUID — let scanner decide)
            try:
                result_file = item.Transfer()
                if result_file is not None:
                    image_file = result_file
                    temp_ext = ".bmp"
                    logger.info("Transfer successful with default format")
            except Exception as def_err:
                logger.debug(f"Default format failed: {def_err}")

            # Try 2: Specific formats
            if image_file is None:
                for fmt, ext in [
                    (WIA_IMG_FORMAT_BMP, ".bmp"),
                    (WIA_IMG_FORMAT_PNG, ".png"),
                    (WIA_IMG_FORMAT_JPEG, ".jpg"),
                    (WIA_IMG_FORMAT_TIFF, ".tiff"),
                ]:
                    try:
                        result_file = item.Transfer(fmt)
                        if result_file is not None:
                            image_file = result_file
                            temp_ext = ext
                            logger.info(f"Transfer successful with format {ext}")
                            break
                    except Exception as fmt_err:
                        logger.debug(f"Format {ext} not supported: {fmt_err}")

            if image_file is None:
                raise RuntimeError("Scanner did not return image data — no supported transfer format found")

            # Save to temp file and load with PIL
            temp_path = os.path.join(tempfile.gettempdir(), f"rkt_scan_{int(time.time())}{temp_ext}")
            image_file.SaveFile(temp_path)
            with Image.open(temp_path) as _raw:
                img = _raw.convert("RGB")

            # Clean up temp file
            try:
                os.unlink(temp_path)
            except OSError:
                pass

            scan_time = int((time.perf_counter() - start_time) * 1000)
            logger.info(f"Scan complete: {img.size[0]}x{img.size[1]} @ {dpi}dpi in {scan_time}ms")

            return ScanResult(
                image=img,
                dpi=dpi,
                device_id=self._device_id,
                scan_time_ms=scan_time,
            )
        except Exception as e:
            logger.error(f"Scan failed: {e}")
            raise
        finally:
            pythoncom.CoUninitialize()
