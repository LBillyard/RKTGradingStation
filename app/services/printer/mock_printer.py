"""Mock printer for development without hardware."""

import logging
import shutil
from pathlib import Path

from app.services.printer.base import BasePrinter, PrintResult

logger = logging.getLogger(__name__)


class MockPrinter(BasePrinter):
    """Simulates printing by copying the label image to an output directory."""

    def __init__(self, output_dir: str = "data/exports/mock_prints"):
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)

    def list_printers(self) -> list[str]:
        return ["Mock Epson C6000 (Development)"]

    def print_image(
        self,
        image_path: str,
        printer_name: str,
        width_mm: float,
        height_mm: float,
        dpi: int,
    ) -> PrintResult:
        """Copy image to mock output directory."""
        src = Path(image_path)
        dest = self._output_dir / src.name
        shutil.copy2(src, dest)
        logger.info(f"Mock print: saved '{src.name}' to {self._output_dir}")
        return PrintResult(
            job_id="",
            status="printed",
            image_path=str(dest),
            printer_name="Mock Epson C6000 (Development)",
        )
