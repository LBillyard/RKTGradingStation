"""Edge analysis for card grading."""

import logging
from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np

from app.utils.validation import round_grade

logger = logging.getLogger(__name__)

# Edge position labels
EDGE_NAMES = ["top", "bottom", "left", "right"]


@dataclass
class EdgeDefect:
    """A single defect found on a card edge."""
    edge: str                  # e.g., "top"
    defect_type: str           # wear, chip, nick, straightness
    severity: str              # minor, moderate, major, severe
    score_impact: float
    bbox_x: int = 0
    bbox_y: int = 0
    bbox_w: int = 0
    bbox_h: int = 0
    confidence: float = 0.0
    details: dict = field(default_factory=dict)


@dataclass
class EdgeResult:
    """Result of edge analysis."""
    scores: dict               # per-edge scores, e.g., {"top": 9.5, ...}
    defects: list[EdgeDefect]
    final_score: float         # average of 4 edge scores
    details: dict = field(default_factory=dict)


class EdgeAnalyzer:
    """Analyze the four edges of a trading card.

    Detects wear (smoothness loss), chips/nicks (contour irregularities),
    and straightness deviations.
    """

    def __init__(
        self,
        wear_threshold: float = 0.10,
        chip_min_depth: int = 3,
        straightness_tolerance: float = 0.02,
    ):
        """Initialize edge analyzer.

        Args:
            wear_threshold: Edge roughness ratio above which wear is detected.
            chip_min_depth: Minimum pixel depth for a chip/nick contour indent.
            straightness_tolerance: Maximum deviation fraction from a straight line.
        """
        self.wear_threshold = wear_threshold
        self.chip_min_depth = chip_min_depth
        self.straightness_tolerance = straightness_tolerance

    def analyze(
        self,
        edge_images: list[Optional[np.ndarray]],
    ) -> EdgeResult:
        """Analyze four edge region images.

        Args:
            edge_images: List of 4 edge images in order:
                [top, bottom, left, right].
                Each is an OpenCV BGR ndarray from RegionExtractor.

        Returns:
            EdgeResult with per-edge scores, defects, and final score.
        """
        scores = {}
        all_defects: list[EdgeDefect] = []

        for name, img in zip(EDGE_NAMES, edge_images):
            if img is None or img.size == 0:
                scores[name] = 10.0
                continue

            edge_score = 10.0
            edge_defects = self._analyze_single_edge(name, img)
            all_defects.extend(edge_defects)

            for defect in edge_defects:
                edge_score -= defect.score_impact

            scores[name] = max(1.0, edge_score)

        avg = sum(scores.values()) / len(scores) if scores else 10.0
        final_score = round_grade(avg)

        logger.debug(
            "Edge analysis: %s -> final=%.1f",
            {k: f"{v:.1f}" for k, v in scores.items()},
            final_score,
        )

        return EdgeResult(
            scores=scores,
            defects=all_defects,
            final_score=final_score,
            details={"per_edge_scores": scores},
        )

    def _analyze_single_edge(
        self, edge_name: str, image: np.ndarray,
    ) -> list[EdgeDefect]:
        """Analyze a single edge image for defects."""
        defects: list[EdgeDefect] = []

        wear = self._detect_wear(image, edge_name)
        if wear is not None:
            defects.append(wear)

        chips = self._detect_chips(image, edge_name)
        defects.extend(chips)

        straightness = self._detect_straightness_issues(image, edge_name)
        if straightness is not None:
            defects.append(straightness)

        return defects

    def _detect_wear(
        self, image: np.ndarray, edge_name: str,
    ) -> Optional[EdgeDefect]:
        """Detect edge wear by measuring roughness of the card boundary.

        Wear manifests as irregular micro-texture along the edge, where
        the paper fibres become exposed and fuzzy.
        """
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape

        # Apply edge detection
        edges = cv2.Canny(gray, 40, 120)

        # For horizontal edges (top/bottom), examine the outer edge row region
        # For vertical edges (left/right), examine the outer edge column region
        if edge_name in ("top", "bottom"):
            # The actual card edge is at the top for "top" edge, bottom for "bottom"
            strip_h = max(1, h // 4)
            if edge_name == "top":
                strip = edges[0:strip_h, :]
            else:
                strip = edges[h - strip_h:h, :]
            edge_length = w
        else:
            strip_w = max(1, w // 4)
            if edge_name == "left":
                strip = edges[:, 0:strip_w]
            else:
                strip = edges[:, w - strip_w:w]
            edge_length = h

        if strip.size == 0:
            return None

        # Measure edge density (high density = rough/worn)
        edge_pixel_count = np.sum(strip > 0)
        total_pixels = strip.size
        roughness = edge_pixel_count / total_pixels if total_pixels > 0 else 0.0

        if roughness < self.wear_threshold:
            return None

        if roughness > 0.40:
            severity = "severe"
            impact = 2.0
        elif roughness > 0.25:
            severity = "major"
            impact = 1.5
        elif roughness > 0.15:
            severity = "moderate"
            impact = 0.8
        else:
            severity = "minor"
            impact = 0.3

        confidence = min(1.0, roughness / 0.40)

        return EdgeDefect(
            edge=edge_name,
            defect_type="wear",
            severity=severity,
            score_impact=impact,
            bbox_x=0, bbox_y=0, bbox_w=w, bbox_h=h,
            confidence=confidence,
            details={"roughness": round(roughness, 4)},
        )

    def _detect_chips(
        self, image: np.ndarray, edge_name: str,
    ) -> list[EdgeDefect]:
        """Detect chips and nicks along the edge.

        Chips are small indentations in the card edge caused by impact
        or handling. They appear as concave deviations from the straight
        edge line.
        """
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape

        # Threshold to find the card boundary
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        # Find contours
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        if not contours:
            return []

        largest = max(contours, key=cv2.contourArea)

        # Use convexity defects to find chips
        hull = cv2.convexHull(largest, returnPoints=False)

        if len(largest) < 5 or len(hull) < 3:
            return []

        try:
            defect_points = cv2.convexityDefects(largest, hull)
        except cv2.error:
            return []

        if defect_points is None:
            return []

        chips: list[EdgeDefect] = []
        edge_length = w if edge_name in ("top", "bottom") else h

        for i in range(defect_points.shape[0]):
            start_idx, end_idx, far_idx, depth = defect_points[i, 0]
            depth_px = depth / 256.0

            if depth_px < self.chip_min_depth:
                continue

            # Get the position of the chip
            far_point = tuple(largest[far_idx][0])

            if depth_px > 15:
                severity = "severe"
                impact = 2.0
            elif depth_px > 8:
                severity = "major"
                impact = 1.5
            elif depth_px > 5:
                severity = "moderate"
                impact = 0.8
            else:
                severity = "minor"
                impact = 0.3

            confidence = min(1.0, depth_px / 15.0)

            chips.append(EdgeDefect(
                edge=edge_name,
                defect_type="chip",
                severity=severity,
                score_impact=impact,
                bbox_x=max(0, far_point[0] - 5),
                bbox_y=max(0, far_point[1] - 5),
                bbox_w=10,
                bbox_h=10,
                confidence=confidence,
                details={"depth_px": round(depth_px, 2)},
            ))

        return chips

    def _detect_straightness_issues(
        self, image: np.ndarray, edge_name: str,
    ) -> Optional[EdgeDefect]:
        """Detect edge straightness deviations.

        A card edge should be perfectly straight. Bowing, waviness, or
        bends are detected by fitting a line and measuring deviation.
        """
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape

        edges = cv2.Canny(gray, 50, 150)

        # Extract edge profile along the card boundary
        if edge_name in ("top", "bottom"):
            # Look at the boundary row
            row_idx = 0 if edge_name == "top" else h - 1
            # Scan a few rows to find the edge
            profile = []
            for col in range(w):
                for row in range(min(h, 10) if edge_name == "top" else max(0, h - 10), h if edge_name == "top" else h):
                    if edges[row, col] > 0:
                        profile.append(row)
                        break
                else:
                    profile.append(row_idx)
        else:
            col_idx = 0 if edge_name == "left" else w - 1
            profile = []
            for row in range(h):
                for col in range(min(w, 10) if edge_name == "left" else max(0, w - 10), w if edge_name == "left" else w):
                    if edges[row, col] > 0:
                        profile.append(col)
                        break
                else:
                    profile.append(col_idx)

        if len(profile) < 3:
            return None

        profile_arr = np.array(profile, dtype=np.float64)

        # Fit a straight line
        x = np.arange(len(profile_arr))
        coeffs = np.polyfit(x, profile_arr, 1)
        fitted_line = np.polyval(coeffs, x)

        # Measure deviation from the fitted line
        deviations = np.abs(profile_arr - fitted_line)
        max_deviation = np.max(deviations)
        mean_deviation = np.mean(deviations)

        edge_length = w if edge_name in ("top", "bottom") else h
        deviation_ratio = max_deviation / edge_length if edge_length > 0 else 0.0

        if deviation_ratio < self.straightness_tolerance:
            return None

        if deviation_ratio > 0.08:
            severity = "severe"
            impact = 2.0
        elif deviation_ratio > 0.05:
            severity = "major"
            impact = 1.5
        elif deviation_ratio > 0.03:
            severity = "moderate"
            impact = 0.5
        else:
            severity = "minor"
            impact = 0.3

        confidence = min(1.0, deviation_ratio / 0.08)

        return EdgeDefect(
            edge=edge_name,
            defect_type="straightness",
            severity=severity,
            score_impact=impact,
            bbox_x=0, bbox_y=0, bbox_w=w, bbox_h=h,
            confidence=confidence,
            details={
                "max_deviation_px": round(max_deviation, 2),
                "mean_deviation_px": round(mean_deviation, 2),
                "deviation_ratio": round(deviation_ratio, 4),
            },
        )
