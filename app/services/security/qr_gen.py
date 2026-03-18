"""QR code and DataMatrix security pattern generator.

Generates machine-readable 2D barcodes containing card verification
data. The QR code encodes a compact JSON payload with the serial
number, grade, card ID, timestamp, and a verification hash.

Uses the ``qrcode`` library for QR generation with HIGH error
correction for durability against laser engraving artefacts.

All coordinates are in millimeters.
"""

import io
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from app.utils.crypto import hash_serial

logger = logging.getLogger(__name__)


@dataclass
class QRResult:
    """Result of QR/DataMatrix generation."""
    svg: str
    data_payload: str
    code_type: str  # "qr" or "datamatrix"
    size_mm: float
    module_count: int
    serial_number: str
    verification_hash: str


class QRGenerator:
    """Generates QR codes and DataMatrix codes for slab labels.

    The encoded data is a compact JSON string containing verification
    information. QR codes use HIGH error correction level (30% recovery)
    to survive potential laser imperfections.
    """

    DEFAULT_SIZE_MM = 8.0
    MIN_SIZE_MM = 4.0
    MAX_SIZE_MM = 20.0

    def build_payload(
        self,
        serial_number: str,
        grade: str = "",
        card_id: str = "",
        timestamp: str = "",
    ) -> str:
        """Build the compact JSON payload for encoding.

        Args:
            serial_number: Card serial number.
            grade: Grade value (e.g. "9.5").
            card_id: Card record identifier.
            timestamp: ISO timestamp; auto-generated if empty.

        Returns:
            Compact JSON string for QR encoding.
        """
        if not timestamp:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

        verification_hash = hash_serial(serial_number)

        payload = {
            "s": serial_number,         # serial
            "g": grade,                 # grade
            "c": card_id[:12] if card_id else "",  # card id (truncated)
            "t": timestamp,             # timestamp
            "v": verification_hash[:12],  # verification (truncated)
        }
        return json.dumps(payload, separators=(",", ":"))

    def generate_qr(
        self,
        data: str,
        size_mm: float = 8.0,
        offset_x: float = 0.0,
        offset_y: float = 0.0,
        serial_number: str = "",
    ) -> QRResult:
        """Generate a QR code as an SVG group.

        Args:
            data: String data to encode in the QR code.
            size_mm: Target size of the QR code in mm.
            offset_x: Horizontal offset for positioning.
            offset_y: Vertical offset for positioning.
            serial_number: Serial number for metadata.

        Returns:
            :class:`QRResult` with the SVG group and metadata.
        """
        size_mm = max(self.MIN_SIZE_MM, min(self.MAX_SIZE_MM, size_mm))
        verification_hash = hash_serial(serial_number) if serial_number else hash_serial(data)

        try:
            import qrcode
            import qrcode.image.svg

            qr = qrcode.QRCode(
                version=None,  # auto-size
                error_correction=qrcode.constants.ERROR_CORRECT_H,
                box_size=10,
                border=1,
            )
            qr.add_data(data)
            qr.make(fit=True)

            module_count = qr.modules_count
            module_size = size_mm / module_count

            svg_lines = [
                f'<g id="qr-{serial_number or "code"}" '
                f'data-pattern-type="qr_code" '
                f'data-serial="{serial_number}" '
                f'data-verification="{verification_hash[:16]}" '
                f'data-modules="{module_count}">',
                f'  <!-- QR Code: {module_count}x{module_count} modules, '
                f'size={size_mm:.1f}mm -->',
            ]

            for row_idx, row in enumerate(qr.modules):
                for col_idx, is_dark in enumerate(row):
                    if is_dark:
                        x = offset_x + col_idx * module_size
                        y = offset_y + row_idx * module_size
                        svg_lines.append(
                            f'  <rect x="{x:.4f}" y="{y:.4f}" '
                            f'width="{module_size:.4f}" height="{module_size:.4f}" '
                            f'fill="black"/>'
                        )

            svg_lines.append('</g>')
            svg_content = '\n'.join(svg_lines)

            logger.debug(
                "Generated QR code: %dx%d modules, size=%.1fmm",
                module_count, module_count, size_mm,
            )

            return QRResult(
                svg=svg_content,
                data_payload=data,
                code_type="qr",
                size_mm=size_mm,
                module_count=module_count,
                serial_number=serial_number,
                verification_hash=verification_hash,
            )

        except ImportError:
            logger.warning("qrcode library not available; generating placeholder QR")
            return self._generate_placeholder_qr(
                data, size_mm, offset_x, offset_y, serial_number, verification_hash,
            )

    def generate_datamatrix(
        self,
        data: str,
        size_mm: float = 8.0,
        offset_x: float = 0.0,
        offset_y: float = 0.0,
        serial_number: str = "",
    ) -> QRResult:
        """Generate a DataMatrix code as an SVG group.

        Falls back to QR code if the ``pylibdmtx`` library is not
        available.

        Args:
            data: String data to encode.
            size_mm: Target size in mm.
            offset_x: Horizontal offset for positioning.
            offset_y: Vertical offset for positioning.
            serial_number: Serial number for metadata.

        Returns:
            :class:`QRResult` with the SVG group and metadata.
        """
        size_mm = max(self.MIN_SIZE_MM, min(self.MAX_SIZE_MM, size_mm))
        verification_hash = hash_serial(serial_number) if serial_number else hash_serial(data)

        try:
            from pylibdmtx.pylibdmtx import encode as dmtx_encode
            from PIL import Image

            encoded = dmtx_encode(data.encode("utf-8"))
            img = Image.frombytes("RGB", (encoded.width, encoded.height), encoded.pixels)

            # Convert image to module grid
            # DataMatrix images have 1px per module (with some padding)
            pixels = img.load()
            width_px, height_px = img.size

            module_size = size_mm / max(width_px, height_px)

            svg_lines = [
                f'<g id="datamatrix-{serial_number or "code"}" '
                f'data-pattern-type="datamatrix" '
                f'data-serial="{serial_number}" '
                f'data-verification="{verification_hash[:16]}" '
                f'data-size="{width_px}x{height_px}">',
                f'  <!-- DataMatrix: {width_px}x{height_px}px, size={size_mm:.1f}mm -->',
            ]

            for py in range(height_px):
                for px in range(width_px):
                    r, g, b = pixels[px, py]
                    if r < 128:  # dark module
                        x = offset_x + px * module_size
                        y = offset_y + py * module_size
                        svg_lines.append(
                            f'  <rect x="{x:.4f}" y="{y:.4f}" '
                            f'width="{module_size:.4f}" height="{module_size:.4f}" '
                            f'fill="black"/>'
                        )

            svg_lines.append('</g>')
            svg_content = '\n'.join(svg_lines)

            logger.debug(
                "Generated DataMatrix: %dx%dpx, size=%.1fmm",
                width_px, height_px, size_mm,
            )

            return QRResult(
                svg=svg_content,
                data_payload=data,
                code_type="datamatrix",
                size_mm=size_mm,
                module_count=max(width_px, height_px),
                serial_number=serial_number,
                verification_hash=verification_hash,
            )

        except ImportError:
            logger.info("pylibdmtx not available; falling back to QR code")
            result = self.generate_qr(data, size_mm, offset_x, offset_y, serial_number)
            # Mark as fallback
            result.code_type = "qr_fallback"
            return result

    def _generate_placeholder_qr(
        self,
        data: str,
        size_mm: float,
        offset_x: float,
        offset_y: float,
        serial_number: str,
        verification_hash: str,
    ) -> QRResult:
        """Generate a simple hash-based placeholder when qrcode lib is missing.

        This produces a visually distinctive grid pattern derived from the
        data hash, but is NOT a decodable QR code. It serves as a visual
        placeholder and unique fingerprint.
        """
        import hashlib

        grid_size = 21  # QR version 1 is 21x21
        module_size = size_mm / grid_size
        hash_bytes = hashlib.sha256(data.encode()).digest()

        svg_lines = [
            f'<g id="qr-placeholder-{serial_number or "code"}" '
            f'data-pattern-type="qr_placeholder" '
            f'data-serial="{serial_number}">',
            '  <!-- Placeholder QR: qrcode library not installed -->',
        ]

        # Generate grid from hash bytes
        byte_idx = 0
        for row in range(grid_size):
            for col in range(grid_size):
                # Finder patterns in corners (always present in QR)
                in_finder = (
                    (row < 7 and col < 7) or
                    (row < 7 and col >= grid_size - 7) or
                    (row >= grid_size - 7 and col < 7)
                )

                if in_finder:
                    # Draw finder pattern borders
                    is_border = (
                        row in (0, 6) or col in (0, 6) or
                        (2 <= row <= 4 and 2 <= col <= 4)
                    )
                    is_dark = is_border
                else:
                    # Hash-derived module
                    bit_pos = (row * grid_size + col) % (len(hash_bytes) * 8)
                    byte_val = hash_bytes[bit_pos // 8]
                    is_dark = bool(byte_val & (1 << (bit_pos % 8)))

                if is_dark:
                    x = offset_x + col * module_size
                    y = offset_y + row * module_size
                    svg_lines.append(
                        f'  <rect x="{x:.4f}" y="{y:.4f}" '
                        f'width="{module_size:.4f}" height="{module_size:.4f}" '
                        f'fill="black"/>'
                    )

        svg_lines.append('</g>')

        return QRResult(
            svg='\n'.join(svg_lines),
            data_payload=data,
            code_type="qr_placeholder",
            size_mm=size_mm,
            module_count=grid_size,
            serial_number=serial_number,
            verification_hash=verification_hash,
        )
