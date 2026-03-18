"""Windows GDI printer for Epson C6000 label printing."""

import logging
from typing import Optional

from PIL import Image

from app.services.printer.base import BasePrinter, PrintResult

logger = logging.getLogger(__name__)


class GdiPrinter(BasePrinter):
    """Print labels via Windows GDI print spooler."""

    def list_printers(self) -> list[str]:
        """List available Windows printers."""
        try:
            import win32print
            flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
            printers = win32print.EnumPrinters(flags, None, 1)
            return [p[2] for p in printers]
        except ImportError:
            logger.warning("pywin32 not installed — cannot list printers")
            return []
        except Exception as e:
            logger.error(f"Failed to enumerate printers: {e}")
            return []

    def print_image(
        self,
        image_path: str,
        printer_name: str,
        width_mm: float,
        height_mm: float,
        dpi: int,
    ) -> PrintResult:
        """Print a label image via Windows GDI."""
        try:
            import win32print
            import win32ui
            import win32con
            from PIL import ImageWin

            img = Image.open(image_path)

            # Open printer device context
            hdc = win32ui.CreateDC()
            hdc.CreatePrinterDC(printer_name)

            # Get printable area in pixels
            printer_dpi_x = hdc.GetDeviceCaps(win32con.LOGPIXELSX)
            printer_dpi_y = hdc.GetDeviceCaps(win32con.LOGPIXELSY)

            # Convert mm to pixels at printer DPI
            target_width_px = int(width_mm / 25.4 * printer_dpi_x)
            target_height_px = int(height_mm / 25.4 * printer_dpi_y)

            hdc.StartDoc(f"RKT Label - {image_path}")
            hdc.StartPage()

            # Scale and draw image
            dib = ImageWin.Dib(img)
            dib.draw(hdc.GetHandleOutput(), (0, 0, target_width_px, target_height_px))

            hdc.EndPage()
            hdc.EndDoc()
            hdc.DeleteDC()

            logger.info(f"Printed label to '{printer_name}' ({width_mm}x{height_mm}mm)")
            return PrintResult(
                job_id="",
                status="printed",
                image_path=image_path,
                printer_name=printer_name,
            )

        except ImportError:
            error = "pywin32 not installed — cannot print"
            logger.error(error)
            return PrintResult(
                job_id="",
                status="failed",
                image_path=image_path,
                printer_name=printer_name,
                error=error,
            )
        except Exception as e:
            error = f"Print failed: {e}"
            logger.error(error)
            return PrintResult(
                job_id="",
                status="failed",
                image_path=image_path,
                printer_name=printer_name,
                error=str(e),
            )
