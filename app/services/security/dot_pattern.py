"""Dot constellation security pattern generator.

Generates a deterministic arrangement of small dots within a rectangular
zone. The dot positions are derived from the SHA-256 hash of the serial
number so that the same serial always produces an identical pattern,
enabling verification by regeneration and comparison.

All coordinates are in millimeters.
"""

import logging
import math
from dataclasses import dataclass, field

from app.utils.crypto import hash_serial, serial_to_seed_bytes

logger = logging.getLogger(__name__)


@dataclass
class DotPosition:
    """A single dot in the constellation."""
    x_mm: float
    y_mm: float
    radius_mm: float

    def to_dict(self) -> dict:
        return {"x_mm": self.x_mm, "y_mm": self.y_mm, "radius_mm": self.radius_mm}


@dataclass
class DotPatternResult:
    """Result of dot constellation generation."""
    svg: str
    dot_count: int
    grid_cols: int
    grid_rows: int
    zone_width_mm: float
    zone_height_mm: float
    serial_number: str
    verification_hash: str
    dots: list[DotPosition] = field(default_factory=list)


class DotPatternGenerator:
    """Generates dot constellation patterns from serial numbers.

    Algorithm:
        1. serial -> SHA-256 hash -> raw bytes (32 bytes)
        2. If more bytes are needed, chain hashes: H(serial), H(H(serial)), ...
        3. Extract bit pairs from hash bytes
        4. Each bit pair maps to a grid cell (2 bits = 4 possible sub-positions)
        5. Place dots at computed grid positions
        6. Target ~30-50% grid cell occupancy for visual clarity
    """

    DEFAULT_DOT_RADIUS_MM = 0.1
    MIN_DOT_RADIUS_MM = 0.05
    MAX_DOT_RADIUS_MM = 0.5
    TARGET_FILL_RATIO = 0.40  # aim for 40% of grid cells filled

    def generate(
        self,
        serial_number: str,
        zone_width_mm: float,
        zone_height_mm: float,
        dot_radius_mm: float = 0.1,
        dot_count: int = 64,
        offset_x: float = 0.0,
        offset_y: float = 0.0,
    ) -> DotPatternResult:
        """Generate a dot constellation within a rectangular zone.

        Args:
            serial_number: Card serial number.
            zone_width_mm: Width of the zone in mm.
            zone_height_mm: Height of the zone in mm.
            dot_radius_mm: Radius of each dot in mm.
            dot_count: Target number of dots to place.
            offset_x: Horizontal offset for positioning.
            offset_y: Vertical offset for positioning.

        Returns:
            :class:`DotPatternResult` with the SVG group and metadata.
        """
        dot_radius_mm = max(self.MIN_DOT_RADIUS_MM, min(self.MAX_DOT_RADIUS_MM, dot_radius_mm))
        verification_hash = hash_serial(serial_number)

        # Calculate grid dimensions -- each cell is 2*radius + small gap
        cell_size = dot_radius_mm * 4  # spacing between potential dot centres
        grid_cols = max(1, int(zone_width_mm / cell_size))
        grid_rows = max(1, int(zone_height_mm / cell_size))
        total_cells = grid_cols * grid_rows

        # Cap dot count to something reasonable
        dot_count = min(dot_count, total_cells)

        # Generate enough deterministic bytes for all dot decisions
        seed_bytes = self._expand_seed(serial_number, total_cells)

        # Decide which cells get dots using the seed bytes
        occupied = set()
        dots: list[DotPosition] = []

        for byte_idx in range(len(seed_bytes)):
            if len(dots) >= dot_count:
                break

            byte_val = seed_bytes[byte_idx]
            # Map byte to a grid cell
            cell_index = byte_val % total_cells
            if cell_index in occupied:
                # Linear probe to next free cell
                for probe in range(1, total_cells):
                    candidate = (cell_index + probe) % total_cells
                    if candidate not in occupied:
                        cell_index = candidate
                        break
                else:
                    continue  # grid completely full

            if cell_index in occupied:
                continue

            occupied.add(cell_index)

            col = cell_index % grid_cols
            row = cell_index // grid_cols

            # Place dot at cell centre with small sub-pixel jitter from next byte
            jitter_byte = seed_bytes[(byte_idx + 1) % len(seed_bytes)]
            jitter_x = ((jitter_byte & 0x0F) / 15.0 - 0.5) * cell_size * 0.3
            jitter_y = ((jitter_byte >> 4) / 15.0 - 0.5) * cell_size * 0.3

            cx = offset_x + (col + 0.5) * cell_size + jitter_x
            cy = offset_y + (row + 0.5) * cell_size + jitter_y

            # Clamp to zone boundaries
            cx = max(offset_x + dot_radius_mm, min(offset_x + zone_width_mm - dot_radius_mm, cx))
            cy = max(offset_y + dot_radius_mm, min(offset_y + zone_height_mm - dot_radius_mm, cy))

            dots.append(DotPosition(x_mm=cx, y_mm=cy, radius_mm=dot_radius_mm))

        # Build SVG
        svg_lines = [
            f'<g id="dot-pattern-{serial_number}" '
            f'data-pattern-type="dot_pattern" '
            f'data-serial="{serial_number}" '
            f'data-verification="{verification_hash[:16]}" '
            f'data-dot-count="{len(dots)}" '
            f'data-grid="{grid_cols}x{grid_rows}">',
            f'  <!-- Dot constellation: {len(dots)} dots in {grid_cols}x{grid_rows} grid -->',
            f'  <!-- Verification hash: {verification_hash} -->',
        ]

        for idx, dot in enumerate(dots):
            svg_lines.append(
                f'  <circle cx="{dot.x_mm:.4f}" cy="{dot.y_mm:.4f}" '
                f'r="{dot.radius_mm:.4f}" fill="black" '
                f'data-idx="{idx}"/>'
            )

        svg_lines.append('</g>')

        svg_content = '\n'.join(svg_lines)
        logger.debug(
            "Generated dot pattern: %d dots in %dx%d grid, zone=%.1fx%.1fmm",
            len(dots), grid_cols, grid_rows, zone_width_mm, zone_height_mm,
        )

        return DotPatternResult(
            svg=svg_content,
            dot_count=len(dots),
            grid_cols=grid_cols,
            grid_rows=grid_rows,
            zone_width_mm=zone_width_mm,
            zone_height_mm=zone_height_mm,
            serial_number=serial_number,
            verification_hash=verification_hash,
            dots=dots,
        )

    @staticmethod
    def _expand_seed(serial_number: str, min_bytes: int) -> bytes:
        """Expand serial number into enough deterministic bytes.

        Chains SHA-256 hashes: H(serial), H(H(serial)), ... to produce
        as many bytes as needed.
        """
        import hashlib

        result = bytearray()
        current = serial_number.encode()
        while len(result) < min_bytes:
            digest = hashlib.sha256(current).digest()
            result.extend(digest)
            current = digest  # chain: next round hashes the previous digest
        return bytes(result[:min_bytes])

    def get_expected_dots(self, serial_number: str, zone_width_mm: float,
                          zone_height_mm: float, dot_radius_mm: float = 0.1,
                          dot_count: int = 64) -> list[DotPosition]:
        """Regenerate expected dot positions for verification.

        Convenience wrapper that returns just the dot list without SVG.
        """
        result = self.generate(
            serial_number, zone_width_mm, zone_height_mm,
            dot_radius_mm=dot_radius_mm, dot_count=dot_count,
        )
        return result.dots
