"""Witness mark security pattern generator.

Generates three types of marks for tamper detection and alignment:

1. **Seam witnesses** -- Small marks along slab edges whose spacing
   encodes the serial number. If the slab halves are separated and
   reassembled incorrectly, the marks will not align.

2. **Alignment marks** -- Cross-hair registration marks at corners
   for front/back alignment during engraving.

3. **Hidden patterns** -- Extremely small dot patterns only visible
   under magnification, providing a covert verification layer.

All coordinates are in millimeters.
"""

import hashlib
import logging
import math
from dataclasses import dataclass, field

from app.utils.crypto import hash_serial, serial_to_seed_bytes

logger = logging.getLogger(__name__)


@dataclass
class WitnessMarkPosition:
    """Position of a single witness mark."""
    x_mm: float
    y_mm: float
    edge: str  # "top", "bottom", "left", "right"
    mark_index: int


@dataclass
class WitnessResult:
    """Result of witness mark generation."""
    svg: str
    mark_type: str  # "seam", "alignment", "hidden"
    mark_count: int
    serial_number: str
    verification_hash: str


class WitnessMarkGenerator:
    """Generates witness marks for tamper detection and alignment.

    Seam witnesses encode the serial number in the spacing between
    marks along each edge. The spacing pattern is deterministic --
    derived from the serial hash -- so that any reassembly after
    tampering will produce misaligned marks.
    """

    # Mark dimensions
    SEAM_MARK_LENGTH_MM = 0.8
    SEAM_MARK_WIDTH_MM = 0.15
    ALIGNMENT_CROSS_SIZE_MM = 2.0
    ALIGNMENT_LINE_WIDTH_MM = 0.1
    HIDDEN_DOT_RADIUS_MM = 0.04  # extremely small -- magnification needed

    # Edge insets
    EDGE_INSET_MM = 1.0  # distance from slab edge to mark centre

    def generate_seam_witnesses(
        self,
        serial_number: str,
        slab_width_mm: float,
        slab_height_mm: float,
        marks_per_edge: int = 8,
    ) -> WitnessResult:
        """Generate witness marks along slab edges.

        The spacing between marks on each edge encodes part of the
        serial hash. Marks on opposite edges (top/bottom, left/right)
        must align -- any mis-reassembly breaks this alignment.

        Args:
            serial_number: Card serial number.
            slab_width_mm: Outer slab width in mm.
            slab_height_mm: Outer slab height in mm.
            marks_per_edge: Number of marks per edge.

        Returns:
            :class:`WitnessResult` with the SVG group.
        """
        verification_hash = hash_serial(serial_number)
        seed = serial_to_seed_bytes(serial_number)

        svg_lines = [
            f'<g id="seam-witnesses-{serial_number}" '
            f'data-pattern-type="witness_seam" '
            f'data-serial="{serial_number}" '
            f'data-verification="{verification_hash[:16]}">',
            f'  <!-- Seam witnesses: {marks_per_edge} marks/edge -->',
        ]

        total_marks = 0

        for edge_idx, edge_name in enumerate(["top", "bottom", "left", "right"]):
            # Generate deterministic spacing from seed bytes
            edge_seed_offset = edge_idx * marks_per_edge
            positions = self._compute_edge_positions(
                seed, edge_seed_offset, marks_per_edge,
                slab_width_mm if edge_name in ("top", "bottom") else slab_height_mm,
            )

            for mark_idx, pos in enumerate(positions):
                if edge_name == "top":
                    x = pos
                    y = self.EDGE_INSET_MM
                    x1, y1 = x, y - self.SEAM_MARK_LENGTH_MM / 2
                    x2, y2 = x, y + self.SEAM_MARK_LENGTH_MM / 2
                elif edge_name == "bottom":
                    x = pos
                    y = slab_height_mm - self.EDGE_INSET_MM
                    x1, y1 = x, y - self.SEAM_MARK_LENGTH_MM / 2
                    x2, y2 = x, y + self.SEAM_MARK_LENGTH_MM / 2
                elif edge_name == "left":
                    x = self.EDGE_INSET_MM
                    y = pos
                    x1, y1 = x - self.SEAM_MARK_LENGTH_MM / 2, y
                    x2, y2 = x + self.SEAM_MARK_LENGTH_MM / 2, y
                else:  # right
                    x = slab_width_mm - self.EDGE_INSET_MM
                    y = pos
                    x1, y1 = x - self.SEAM_MARK_LENGTH_MM / 2, y
                    x2, y2 = x + self.SEAM_MARK_LENGTH_MM / 2, y

                svg_lines.append(
                    f'  <line x1="{x1:.4f}" y1="{y1:.4f}" '
                    f'x2="{x2:.4f}" y2="{y2:.4f}" '
                    f'stroke="black" stroke-width="{self.SEAM_MARK_WIDTH_MM}" '
                    f'data-edge="{edge_name}" data-idx="{mark_idx}"/>'
                )
                total_marks += 1

        svg_lines.append('</g>')

        logger.debug(
            "Generated %d seam witnesses for '%s' on %.0fx%.0fmm slab",
            total_marks, serial_number, slab_width_mm, slab_height_mm,
        )

        return WitnessResult(
            svg='\n'.join(svg_lines),
            mark_type="seam",
            mark_count=total_marks,
            serial_number=serial_number,
            verification_hash=verification_hash,
        )

    def generate_alignment_marks(
        self,
        slab_width_mm: float,
        slab_height_mm: float,
        inset_mm: float = 3.0,
    ) -> WitnessResult:
        """Generate cross-hair alignment marks at corners.

        These marks enable precise front/back registration when the
        slab is flipped for double-sided engraving.

        Args:
            slab_width_mm: Outer slab width in mm.
            slab_height_mm: Outer slab height in mm.
            inset_mm: Distance from corner to mark centre.

        Returns:
            :class:`WitnessResult` with the SVG group.
        """
        half = self.ALIGNMENT_CROSS_SIZE_MM / 2

        corners = [
            ("top-left", inset_mm, inset_mm),
            ("top-right", slab_width_mm - inset_mm, inset_mm),
            ("bottom-left", inset_mm, slab_height_mm - inset_mm),
            ("bottom-right", slab_width_mm - inset_mm, slab_height_mm - inset_mm),
        ]

        svg_lines = [
            '<g id="alignment-marks" data-pattern-type="alignment">',
            '  <!-- Alignment cross-hairs at corners -->',
        ]

        for name, cx, cy in corners:
            # Horizontal line
            svg_lines.append(
                f'  <line x1="{cx - half:.4f}" y1="{cy:.4f}" '
                f'x2="{cx + half:.4f}" y2="{cy:.4f}" '
                f'stroke="black" stroke-width="{self.ALIGNMENT_LINE_WIDTH_MM}" '
                f'data-corner="{name}"/>'
            )
            # Vertical line
            svg_lines.append(
                f'  <line x1="{cx:.4f}" y1="{cy - half:.4f}" '
                f'x2="{cx:.4f}" y2="{cy + half:.4f}" '
                f'stroke="black" stroke-width="{self.ALIGNMENT_LINE_WIDTH_MM}" '
                f'data-corner="{name}"/>'
            )
            # Small circle at centre
            svg_lines.append(
                f'  <circle cx="{cx:.4f}" cy="{cy:.4f}" '
                f'r="{self.ALIGNMENT_LINE_WIDTH_MM * 2:.4f}" fill="none" '
                f'stroke="black" stroke-width="{self.ALIGNMENT_LINE_WIDTH_MM}" '
                f'data-corner="{name}"/>'
            )

        svg_lines.append('</g>')

        logger.debug("Generated alignment marks for %.0fx%.0fmm slab", slab_width_mm, slab_height_mm)

        return WitnessResult(
            svg='\n'.join(svg_lines),
            mark_type="alignment",
            mark_count=len(corners),
            serial_number="",
            verification_hash="",
        )

    def generate_hidden_pattern(
        self,
        serial_number: str,
        zone_width_mm: float,
        zone_height_mm: float,
        dot_count: int = 32,
        offset_x: float = 0.0,
        offset_y: float = 0.0,
    ) -> WitnessResult:
        """Generate a hidden micro-dot pattern for covert verification.

        These dots are extremely small (r ~0.04mm) and only visible
        under magnification. They provide an additional verification
        layer that is difficult to detect without knowing to look for it.

        Args:
            serial_number: Card serial number.
            zone_width_mm: Width of the zone in mm.
            zone_height_mm: Height of the zone in mm.
            dot_count: Number of hidden dots.
            offset_x: Horizontal offset.
            offset_y: Vertical offset.

        Returns:
            :class:`WitnessResult` with the SVG group.
        """
        verification_hash = hash_serial(serial_number)
        # Use a salted hash for the hidden pattern so it differs from
        # the main dot constellation
        hidden_seed = hashlib.sha256(
            f"HIDDEN:{serial_number}:WITNESS".encode()
        ).digest()

        svg_lines = [
            f'<g id="hidden-pattern-{serial_number}" '
            f'data-pattern-type="witness_hidden" '
            f'data-serial="{serial_number}" '
            f'data-verification="{verification_hash[:16]}" '
            f'opacity="0.6">',
            f'  <!-- Hidden pattern: {dot_count} micro-dots -->',
        ]

        # Expand seed if needed
        seed_bytes = bytearray(hidden_seed)
        while len(seed_bytes) < dot_count * 2:
            hidden_seed = hashlib.sha256(hidden_seed).digest()
            seed_bytes.extend(hidden_seed)

        for i in range(dot_count):
            # Two bytes per dot: one for X, one for Y
            bx = seed_bytes[i * 2]
            by = seed_bytes[i * 2 + 1]

            x = offset_x + (bx / 255.0) * (zone_width_mm - 2 * self.HIDDEN_DOT_RADIUS_MM) + self.HIDDEN_DOT_RADIUS_MM
            y = offset_y + (by / 255.0) * (zone_height_mm - 2 * self.HIDDEN_DOT_RADIUS_MM) + self.HIDDEN_DOT_RADIUS_MM

            svg_lines.append(
                f'  <circle cx="{x:.5f}" cy="{y:.5f}" '
                f'r="{self.HIDDEN_DOT_RADIUS_MM:.4f}" fill="black"/>'
            )

        svg_lines.append('</g>')

        logger.debug(
            "Generated hidden pattern: %d micro-dots in %.1fx%.1fmm zone",
            dot_count, zone_width_mm, zone_height_mm,
        )

        return WitnessResult(
            svg='\n'.join(svg_lines),
            mark_type="hidden",
            mark_count=dot_count,
            serial_number=serial_number,
            verification_hash=verification_hash,
        )

    @staticmethod
    def _compute_edge_positions(
        seed: bytes,
        offset: int,
        count: int,
        edge_length_mm: float,
    ) -> list[float]:
        """Compute deterministic mark positions along an edge.

        The spacing between marks is derived from seed bytes so that
        the pattern uniquely identifies the serial. Marks are distributed
        within the central 80% of the edge to avoid corners.

        Args:
            seed: Deterministic seed bytes.
            offset: Byte offset into the seed for this edge.
            count: Number of marks to place.
            edge_length_mm: Total edge length in mm.

        Returns:
            List of positions (mm) along the edge.
        """
        margin = edge_length_mm * 0.1  # 10% margin on each end
        usable = edge_length_mm - 2 * margin
        base_spacing = usable / (count + 1)

        positions = []
        for i in range(count):
            # Base position (evenly spaced)
            base = margin + (i + 1) * base_spacing

            # Add deterministic jitter from seed
            seed_idx = (offset + i) % len(seed)
            jitter_frac = (seed[seed_idx] / 255.0 - 0.5) * 0.6  # +/-30% of spacing
            jitter = jitter_frac * base_spacing

            pos = max(margin, min(edge_length_mm - margin, base + jitter))
            positions.append(pos)

        return sorted(positions)
