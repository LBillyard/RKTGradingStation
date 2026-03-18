"""Microtext security pattern generator.

Generates repeating microtext lines within a rectangular zone. The text
content is derived from the serial number to create a visually dense,
difficult-to-reproduce security layer for laser-engraved slab labels.

All coordinates are in millimeters for direct integration into the
engraving SVG pipeline.
"""

import logging
import math
from dataclasses import dataclass

from app.utils.crypto import hash_serial

logger = logging.getLogger(__name__)

# Character width-to-height ratio for monospace fonts
_CHAR_ASPECT_RATIO = 0.6


@dataclass
class MicrotextResult:
    """Result of microtext generation."""
    svg: str
    line_count: int
    char_height_mm: float
    zone_width_mm: float
    zone_height_mm: float
    serial_number: str
    verification_hash: str


class MicrotextGenerator:
    """Generates repeating microtext lines for security patterns.

    The microtext consists of the serial number repeated with separators
    across multiple lines within the given zone. Character sizes are
    intentionally very small (0.3-0.5 mm) to make reproduction difficult
    without specialised equipment.
    """

    SEPARATOR = " \u2022 "  # bullet separator between repetitions
    MIN_CHAR_HEIGHT = 0.2
    MAX_CHAR_HEIGHT = 1.0

    def generate(
        self,
        serial_number: str,
        zone_width_mm: float,
        zone_height_mm: float,
        char_height_mm: float = 0.4,
        offset_x: float = 0.0,
        offset_y: float = 0.0,
    ) -> MicrotextResult:
        """Generate microtext lines filling a rectangular zone.

        Args:
            serial_number: Card serial number (e.g. ``RKT-240308-A1B2C3``).
            zone_width_mm: Width of the zone in mm.
            zone_height_mm: Height of the zone in mm.
            char_height_mm: Character height in mm (0.3-0.5 recommended).
            offset_x: Horizontal offset for positioning within the slab SVG.
            offset_y: Vertical offset for positioning within the slab SVG.

        Returns:
            :class:`MicrotextResult` with the SVG group and metadata.
        """
        char_height_mm = max(self.MIN_CHAR_HEIGHT, min(self.MAX_CHAR_HEIGHT, char_height_mm))
        verification_hash = hash_serial(serial_number)

        line_spacing = char_height_mm * 1.5
        char_width = char_height_mm * _CHAR_ASPECT_RATIO

        # Build the repeating text unit
        unit = f"{serial_number}{self.SEPARATOR}"
        unit_width_mm = len(unit) * char_width

        # How many characters fit on one line
        if unit_width_mm <= 0:
            logger.warning("Microtext unit has zero width for serial '%s'", serial_number)
            return MicrotextResult(
                svg="<g/>", line_count=0, char_height_mm=char_height_mm,
                zone_width_mm=zone_width_mm, zone_height_mm=zone_height_mm,
                serial_number=serial_number, verification_hash=verification_hash,
            )

        chars_per_line = max(1, int(zone_width_mm / char_width))
        # Build a single line of text by repeating the unit
        repetitions = math.ceil(chars_per_line / len(unit)) + 1
        line_text = (unit * repetitions)[:chars_per_line]

        # Calculate number of lines that fit in the zone
        num_lines = max(1, int(zone_height_mm / line_spacing))

        # Generate deterministic per-line offsets from the hash so that
        # adjacent lines are not perfectly aligned (adds visual texture)
        hash_bytes = bytes.fromhex(verification_hash)

        svg_lines = []
        svg_lines.append(
            f'<g id="microtext-{serial_number}" '
            f'data-pattern-type="microtext" '
            f'data-serial="{serial_number}" '
            f'data-verification="{verification_hash[:16]}">'
        )

        for i in range(num_lines):
            y = offset_y + (i * line_spacing) + char_height_mm
            # Deterministic horizontal stagger derived from hash byte
            hash_byte = hash_bytes[i % len(hash_bytes)]
            stagger = (hash_byte / 255.0) * unit_width_mm * 0.5
            x = offset_x + stagger

            # Alternate lines use the serial reversed for additional complexity
            if i % 2 == 1:
                display_text = (serial_number[::-1] + self.SEPARATOR) * repetitions
                display_text = display_text[:chars_per_line]
            else:
                display_text = line_text

            svg_lines.append(
                f'  <text x="{x:.4f}" y="{y:.4f}" '
                f'font-family="monospace" '
                f'font-size="{char_height_mm:.2f}mm" '
                f'fill="black" '
                f'letter-spacing="0" '
                f'text-rendering="geometricPrecision">'
                f'{_escape_xml(display_text)}'
                f'</text>'
            )

        svg_lines.append('</g>')

        svg_content = '\n'.join(svg_lines)
        logger.debug(
            "Generated microtext: %d lines, char_height=%.2fmm, zone=%.1fx%.1fmm",
            num_lines, char_height_mm, zone_width_mm, zone_height_mm,
        )

        return MicrotextResult(
            svg=svg_content,
            line_count=num_lines,
            char_height_mm=char_height_mm,
            zone_width_mm=zone_width_mm,
            zone_height_mm=zone_height_mm,
            serial_number=serial_number,
            verification_hash=verification_hash,
        )


def _escape_xml(text: str) -> str:
    """Escape XML special characters in text content."""
    return (
        text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )
