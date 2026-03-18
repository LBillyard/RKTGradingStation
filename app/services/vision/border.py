"""Border measurement for centering analysis."""

import logging
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class BorderMeasurement:
    """Measured border widths in pixels and centering ratios."""
    top: float
    bottom: float
    left: float
    right: float
    lr_ratio: str  # e.g., "52/48"
    tb_ratio: str  # e.g., "50/50"
    lr_percentage: float  # left side percentage (50 = perfect)
    tb_percentage: float  # top side percentage (50 = perfect)


class BorderMeasurer:
    """Measure the printed border widths of a card for centering calculation."""

    def __init__(self, edge_detection_margin: int = 20, sample_count: int = 50):
        self.margin = edge_detection_margin
        self.sample_count = sample_count

    def measure(self, image: np.ndarray) -> BorderMeasurement:
        """Measure border widths by detecting the inner printed frame."""
        h, w = image.shape[:2]
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        # Use edge detection to find the printed border
        edges = cv2.Canny(gray, 50, 150)

        # Measure from each side
        left = self._measure_side(edges, 'left', w, h)
        right = self._measure_side(edges, 'right', w, h)
        top = self._measure_side(edges, 'top', w, h)
        bottom = self._measure_side(edges, 'bottom', w, h)

        # Calculate centering ratios
        lr_total = left + right
        tb_total = top + bottom

        if lr_total > 0:
            lr_pct = round(left / lr_total * 100, 1)
        else:
            lr_pct = 50.0

        if tb_total > 0:
            tb_pct = round(top / tb_total * 100, 1)
        else:
            tb_pct = 50.0

        lr_ratio = f"{lr_pct:.0f}/{100-lr_pct:.0f}"
        tb_ratio = f"{tb_pct:.0f}/{100-tb_pct:.0f}"

        return BorderMeasurement(
            top=top, bottom=bottom, left=left, right=right,
            lr_ratio=lr_ratio, tb_ratio=tb_ratio,
            lr_percentage=lr_pct, tb_percentage=tb_pct,
        )

    def _measure_side(self, edges: np.ndarray, side: str, w: int, h: int) -> float:
        """Measure border width from one side by scanning for the first significant edge."""
        measurements = []

        if side == 'left':
            for y in np.linspace(h * 0.2, h * 0.8, self.sample_count, dtype=int):
                row = edges[y, :w//2]
                edge_positions = np.where(row > 0)[0]
                if len(edge_positions) > 0:
                    measurements.append(edge_positions[0])
        elif side == 'right':
            for y in np.linspace(h * 0.2, h * 0.8, self.sample_count, dtype=int):
                row = edges[y, w//2:]
                edge_positions = np.where(row > 0)[0]
                if len(edge_positions) > 0:
                    measurements.append(w - (w//2 + edge_positions[-1]))
        elif side == 'top':
            for x in np.linspace(w * 0.2, w * 0.8, self.sample_count, dtype=int):
                col = edges[:h//2, x]
                edge_positions = np.where(col > 0)[0]
                if len(edge_positions) > 0:
                    measurements.append(edge_positions[0])
        elif side == 'bottom':
            for x in np.linspace(w * 0.2, w * 0.8, self.sample_count, dtype=int):
                col = edges[h//2:, x]
                edge_positions = np.where(col > 0)[0]
                if len(edge_positions) > 0:
                    measurements.append(h - (h//2 + edge_positions[-1]))

        if measurements:
            # Use median to be robust against outliers
            return float(np.median(measurements))
        return 0.0

    def draw_borders(self, image: np.ndarray, borders: BorderMeasurement) -> np.ndarray:
        """Draw border measurements on image for debugging."""
        debug = image.copy()
        h, w = debug.shape[:2]

        # Draw border lines
        left = int(borders.left)
        right = w - int(borders.right)
        top = int(borders.top)
        bottom = h - int(borders.bottom)

        cv2.line(debug, (left, 0), (left, h), (0, 255, 0), 2)
        cv2.line(debug, (right, 0), (right, h), (0, 255, 0), 2)
        cv2.line(debug, (0, top), (w, top), (0, 255, 0), 2)
        cv2.line(debug, (0, bottom), (w, bottom), (0, 255, 0), 2)

        # Add text labels
        cv2.putText(debug, f"L:{borders.left:.0f}", (5, h//2), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        cv2.putText(debug, f"R:{borders.right:.0f}", (w-100, h//2), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        cv2.putText(debug, f"T:{borders.top:.0f}", (w//2-30, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        cv2.putText(debug, f"B:{borders.bottom:.0f}", (w//2-30, h-10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        cv2.putText(debug, f"LR: {borders.lr_ratio}", (w//2-40, h//2-20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 0), 2)
        cv2.putText(debug, f"TB: {borders.tb_ratio}", (w//2-40, h//2+20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 0), 2)

        return debug
