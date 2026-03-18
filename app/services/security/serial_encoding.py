"""Geometric serial number encoder.

Encodes each digit of a serial number as a line segment at a specific
angle, creating a geometric pattern that can be decoded by measuring
angles and converting back to digits. This provides a human-verifiable
security feature that doubles as a visual fingerprint.

All coordinates are in millimeters.
"""

import logging
import math
from dataclasses import dataclass, field

from app.utils.crypto import hash_serial

logger = logging.getLogger(__name__)


@dataclass
class EncodedSegment:
    """A line segment encoding a single character."""
    char: str
    char_index: int
    x1: float
    y1: float
    x2: float
    y2: float
    angle_deg: float
    length_mm: float


@dataclass
class SerialEncodingResult:
    """Result of serial number geometric encoding."""
    svg: str
    segments: list[EncodedSegment] = field(default_factory=list)
    serial_number: str = ""
    verification_hash: str = ""
    zone_width_mm: float = 0.0
    zone_height_mm: float = 0.0


# Mapping: each digit 0-9 maps to an angle (digit * 36 degrees)
# Letters A-F (hex) map to 360 + index * 15 degrees for extra range
_DIGIT_ANGLE_MAP = {str(d): d * 36.0 for d in range(10)}
for i, ch in enumerate("ABCDEF"):
    _DIGIT_ANGLE_MAP[ch] = 360.0 + i * 15.0

# Special characters get fixed angles
_DIGIT_ANGLE_MAP["-"] = 180.0
_DIGIT_ANGLE_MAP["_"] = 270.0


class SerialEncoder:
    """Encodes serial numbers as geometric line-segment patterns.

    Algorithm:
        1. Parse the serial number into individual characters.
        2. Each character maps to a line segment at a specific angle:
           - Digits 0-9: angle = digit * 36 degrees
           - Hex letters A-F: 360 + index * 15 degrees
        3. Line lengths vary by position in the serial (earlier = longer).
        4. Segments are arranged in a grid pattern within the zone.

    The pattern can be decoded by measuring each segment's angle and
    reversing the mapping to recover the original serial number.
    """

    BASE_LENGTH_MM = 1.5    # base line segment length
    MIN_LENGTH_MM = 0.8     # minimum segment length
    LENGTH_DECAY = 0.95     # each successive segment is slightly shorter

    def generate(
        self,
        serial_number: str,
        zone_width_mm: float,
        zone_height_mm: float,
        offset_x: float = 0.0,
        offset_y: float = 0.0,
    ) -> SerialEncodingResult:
        """Generate geometric encoding of a serial number.

        Args:
            serial_number: Card serial number to encode.
            zone_width_mm: Width of the zone in mm.
            zone_height_mm: Height of the zone in mm.
            offset_x: Horizontal offset for positioning.
            offset_y: Vertical offset for positioning.

        Returns:
            :class:`SerialEncodingResult` with SVG and segment metadata.
        """
        verification_hash = hash_serial(serial_number)

        # Filter to encodable characters
        chars = [ch.upper() for ch in serial_number if ch.upper() in _DIGIT_ANGLE_MAP]
        if not chars:
            logger.warning("No encodable characters in serial '%s'", serial_number)
            return SerialEncodingResult(
                svg="<g/>", serial_number=serial_number,
                verification_hash=verification_hash,
                zone_width_mm=zone_width_mm, zone_height_mm=zone_height_mm,
            )

        # Determine grid layout for segments
        num_chars = len(chars)
        grid_cols = math.ceil(math.sqrt(num_chars * (zone_width_mm / zone_height_mm)))
        grid_cols = max(1, min(grid_cols, num_chars))
        grid_rows = math.ceil(num_chars / grid_cols)

        cell_w = zone_width_mm / grid_cols
        cell_h = zone_height_mm / grid_rows

        segments: list[EncodedSegment] = []
        svg_lines = [
            f'<g id="serial-encoding-{serial_number}" '
            f'data-pattern-type="serial_encoding" '
            f'data-serial="{serial_number}" '
            f'data-verification="{verification_hash[:16]}" '
            f'data-char-count="{num_chars}">',
            f'  <!-- Serial encoding: {serial_number} -->',
            f'  <!-- Grid: {grid_cols}x{grid_rows}, cell: {cell_w:.2f}x{cell_h:.2f}mm -->',
        ]

        for idx, ch in enumerate(chars):
            col = idx % grid_cols
            row = idx // grid_cols

            # Centre of this cell
            cx = offset_x + (col + 0.5) * cell_w
            cy = offset_y + (row + 0.5) * cell_h

            # Angle for this character
            angle_deg = _DIGIT_ANGLE_MAP.get(ch, 0.0)
            angle_rad = math.radians(angle_deg)

            # Line length decreases with position
            length = max(
                self.MIN_LENGTH_MM,
                self.BASE_LENGTH_MM * (self.LENGTH_DECAY ** idx),
            )
            # Clamp to half-cell size
            max_length = min(cell_w, cell_h) * 0.45
            length = min(length, max_length)

            half = length / 2.0
            x1 = cx - half * math.cos(angle_rad)
            y1 = cy - half * math.sin(angle_rad)
            x2 = cx + half * math.cos(angle_rad)
            y2 = cy + half * math.sin(angle_rad)

            seg = EncodedSegment(
                char=ch, char_index=idx,
                x1=x1, y1=y1, x2=x2, y2=y2,
                angle_deg=angle_deg, length_mm=length,
            )
            segments.append(seg)

            # Small circle at centre marks the segment origin
            svg_lines.append(
                f'  <circle cx="{cx:.4f}" cy="{cy:.4f}" r="0.05" fill="black" opacity="0.5"/>'
            )
            svg_lines.append(
                f'  <line x1="{x1:.4f}" y1="{y1:.4f}" x2="{x2:.4f}" y2="{y2:.4f}" '
                f'stroke="black" stroke-width="0.08" '
                f'data-char="{ch}" data-angle="{angle_deg:.1f}" data-idx="{idx}"/>'
            )

        svg_lines.append('</g>')

        svg_content = '\n'.join(svg_lines)
        logger.debug(
            "Generated serial encoding: %d segments for '%s'",
            len(segments), serial_number,
        )

        return SerialEncodingResult(
            svg=svg_content,
            segments=segments,
            serial_number=serial_number,
            verification_hash=verification_hash,
            zone_width_mm=zone_width_mm,
            zone_height_mm=zone_height_mm,
        )

    @staticmethod
    def decode_angles(angles_deg: list[float]) -> str:
        """Decode a list of measured angles back to a serial string.

        Args:
            angles_deg: Measured angles from the pattern.

        Returns:
            Decoded serial string (best-effort; measurement noise may
            cause errors).
        """
        reverse_map = {}
        for ch, angle in _DIGIT_ANGLE_MAP.items():
            reverse_map[angle] = ch

        result = []
        for measured in angles_deg:
            # Find the closest known angle
            best_ch = "?"
            best_diff = 360.0
            for angle, ch in reverse_map.items():
                diff = abs(((measured - angle) + 180) % 360 - 180)
                if diff < best_diff:
                    best_diff = diff
                    best_ch = ch
            result.append(best_ch)
        return "".join(result)
