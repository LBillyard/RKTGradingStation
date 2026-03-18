"""Abstract scanner interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional

from PIL import Image


@dataclass
class ScannerDevice:
    device_id: str
    name: str
    manufacturer: str = ""
    is_connected: bool = False


@dataclass
class ScanResult:
    image: Image.Image
    dpi: int
    device_id: str
    scan_time_ms: int
    width_px: int = 0
    height_px: int = 0

    def __post_init__(self):
        if self.image and not self.width_px:
            self.width_px, self.height_px = self.image.size


class BaseScanner(ABC):
    @abstractmethod
    def list_devices(self) -> List[ScannerDevice]: ...
    @abstractmethod
    def connect(self, device_id: str) -> bool: ...
    @abstractmethod
    def disconnect(self) -> None: ...
    @abstractmethod
    def is_connected(self) -> bool: ...
    @abstractmethod
    def scan(self, dpi: int = 600, color_mode: str = "RGB") -> ScanResult: ...
