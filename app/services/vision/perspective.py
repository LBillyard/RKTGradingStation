"""Perspective correction for card images."""

import logging
import cv2
import numpy as np

logger = logging.getLogger(__name__)

# Standard trading card dimensions in mm
CARD_WIDTH_MM = 63.0
CARD_HEIGHT_MM = 88.0
CARD_RATIO = CARD_HEIGHT_MM / CARD_WIDTH_MM  # ~1.397


class PerspectiveCorrector:
    """Correct perspective distortion using detected corner points."""

    def __init__(self, target_width: int = 750, border_margin_pct: float = 0.05):
        self.target_width = target_width
        self.target_height = int(target_width * CARD_RATIO)
        self.border_margin_pct = border_margin_pct

    def correct(self, image: np.ndarray, corners: np.ndarray) -> np.ndarray:
        """Apply perspective transform to straighten the card.

        Expands the detected corners outward by ``border_margin_pct`` so
        that the full card border (and a thin strip of scanner bed) is
        captured.  This is essential for centering, corner and edge
        analysis during grading.

        Args:
            image: Input image (BGR)
            corners: 4 corner points ordered as TL, TR, BR, BL

        Returns:
            Perspective-corrected card image
        """
        # Expand corners outward so card borders are fully visible
        expanded = self._expand_corners(corners, image.shape, self.border_margin_pct)

        dst = np.array([
            [0, 0],
            [self.target_width - 1, 0],
            [self.target_width - 1, self.target_height - 1],
            [0, self.target_height - 1],
        ], dtype=np.float32)

        matrix = cv2.getPerspectiveTransform(expanded, dst)
        corrected = cv2.warpPerspective(
            image, matrix, (self.target_width, self.target_height),
            flags=cv2.INTER_LANCZOS4,
            borderMode=cv2.BORDER_REPLICATE,
        )

        logger.debug(f"Perspective corrected to {self.target_width}x{self.target_height} "
                      f"(margin={self.border_margin_pct:.0%})")
        return corrected

    @staticmethod
    def _expand_corners(corners: np.ndarray, image_shape: tuple,
                        margin_pct: float) -> np.ndarray:
        """Push each card edge outward along its perpendicular normal.

        Corners are ordered TL(0), TR(1), BR(2), BL(3).
        Each edge is shifted outward by ``margin_pct`` of that edge's
        length, then the new corners are found at the edge intersections.
        This works correctly regardless of card rotation angle.
        """
        h, w = image_shape[:2]

        # Define the 4 edges as (start_idx, end_idx) going clockwise
        # Top: TL→TR, Right: TR→BR, Bottom: BR→BL, Left: BL→TL
        edges = [(0, 1), (1, 2), (2, 3), (3, 0)]

        # For each edge, compute the outward-facing normal and shift
        shifted_edges = []
        for a_idx, b_idx in edges:
            a = corners[a_idx]
            b = corners[b_idx]
            edge_vec = b - a
            edge_len = np.linalg.norm(edge_vec)
            if edge_len < 1:
                shifted_edges.append((a, b))
                continue
            # Normal pointing outward (away from card centre)
            # For clockwise winding: outward normal is (dy, -dx) normalised
            normal = np.array([edge_vec[1], -edge_vec[0]]) / edge_len
            # Check the normal points away from centroid
            centroid = corners.mean(axis=0)
            mid = (a + b) / 2
            if np.dot(normal, mid - centroid) < 0:
                normal = -normal
            offset = normal * edge_len * margin_pct
            shifted_edges.append((a + offset, b + offset))

        # Find new corners at intersection of adjacent shifted edges
        expanded = np.zeros_like(corners)
        # Corner i is the intersection of edge (i-1) and edge (i)
        # Corner order: TL=top∩left, TR=top∩right, BR=right∩bottom, BL=bottom∩left
        # Edge order:   0=top, 1=right, 2=bottom, 3=left
        corner_edge_pairs = [(3, 0), (0, 1), (1, 2), (2, 3)]
        for i, (e1, e2) in enumerate(corner_edge_pairs):
            pt = _line_intersection(shifted_edges[e1], shifted_edges[e2])
            if pt is not None:
                expanded[i] = pt
            else:
                # Parallel edges — fall back to centroid expansion
                centroid = corners.mean(axis=0)
                vec = corners[i] - centroid
                expanded[i] = centroid + vec * (1.0 + margin_pct)

            # Clamp to source image bounds
            expanded[i][0] = np.clip(expanded[i][0], 0, w - 1)
            expanded[i][1] = np.clip(expanded[i][1], 0, h - 1)

        return expanded


def _line_intersection(edge1: tuple, edge2: tuple):
    """Find intersection of two lines, each defined by two points.

    Returns the intersection point as np.ndarray or None if parallel.
    """
    p1, p2 = edge1
    p3, p4 = edge2
    d1 = p2 - p1
    d2 = p4 - p3
    cross = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(cross) < 1e-10:
        return None
    t = ((p3[0] - p1[0]) * d2[1] - (p3[1] - p1[1]) * d2[0]) / cross
    return p1 + t * d1
