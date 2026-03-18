"""Printer interface and result types."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class PrintResult:
    """Result of a print operation."""
    job_id: str
    status: str  # "printed" or "failed"
    image_path: str
    printer_name: str
    error: Optional[str] = None


class BasePrinter(ABC):
    """Abstract printer interface."""

    @abstractmethod
    def list_printers(self) -> list[str]:
        """Return available printer names."""
        ...

    @abstractmethod
    def print_image(
        self,
        image_path: str,
        printer_name: str,
        width_mm: float,
        height_mm: float,
        dpi: int,
    ) -> PrintResult:
        """Send an image to the printer."""
        ...
