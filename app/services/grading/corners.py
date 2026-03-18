"""Corner analysis for card grading."""

import logging
from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np

from app.utils.validation import round_grade

logger = logging.getLogger(__name__)

# Corner position labels
CORNER_NAMES = ["top_left", "top_right", "bottom_right", "bottom_left"]


@dataclass
class CornerDefect:
    """A single defect found on a corner."""
    corner: str                # e.g., "top_left"
    defect_type: str           # whitening, softening, deformation
    severity: str              # minor, moderate, major, severe
    score_impact: float        # how much this defect reduces the score
    bbox_x: int = 0
    bbox_y: int = 0
    bbox_w: int = 0
    bbox_h: int = 0
    confidence: float = 0.0
    details: dict = field(default_factory=dict)


@dataclass
class CornerResult:
    """Result of corner analysis."""
    scores: dict               # per-corner scores, e.g., {"top_left": 9.0, ...}
    defects: list[CornerDefect]
    final_score: float         # average of 4 corner scores
    details: dict = field(default_factory=dict)


class CornerAnalyzer:
    """Analyze the four corners of a trading card.

    Detects whitening (bright spots), softening/rounding (contour radius),
    and deformation (shape irregularity).
    """

    def __init__(
        self,
        whitening_threshold: int = 230,
        whitening_area_pct: float = 0.05,
        softening_threshold: float = 0.15,
        deformation_threshold: float = 0.25,
    ):
        """Initialize corner analyzer.

        Args:
            whitening_threshold: Pixel brightness above which is considered whitening.
            whitening_area_pct: Fraction of corner area that triggers whitening defect.
            softening_threshold: Curvature ratio above which corner is considered soft.
            deformation_threshold: Shape deviation ratio for deformation detection.
        """
        self.whitening_threshold = whitening_threshold
        self.whitening_area_pct = whitening_area_pct
        self.softening_threshold = softening_threshold
        self.deformation_threshold = deformation_threshold

    def analyze(
        self,
        corner_images: list[Optional[np.ndarray]],
    ) -> CornerResult:
        """Analyze four corner region images.

        Args:
            corner_images: List of 4 corner images in order:
                [top_left, top_right, bottom_right, bottom_left].
                Each is an OpenCV BGR ndarray from RegionExtractor.

        Returns:
            CornerResult with per-corner scores, defects, and final score.
        """
        scores = {}
        all_defects: list[CornerDefect] = []

        for i, (name, img) in enumerate(zip(CORNER_NAMES, corner_images)):
            if img is None or img.size == 0:
                scores[name] = 10.0
                continue

            corner_score = 10.0
            corner_defects = self._analyze_single_corner(name, img)
            all_defects.extend(corner_defects)

            # Deduct from the perfect score based on defects found
            for defect in corner_defects:
                corner_score -= defect.score_impact

            scores[name] = max(1.0, corner_score)

        # Final score is the average of all 4 corners
        avg = sum(scores.values()) / len(scores) if scores else 10.0
        final_score = round_grade(avg)

        logger.debug(
            "Corner analysis: %s -> final=%.1f",
            {k: f"{v:.1f}" for k, v in scores.items()},
            final_score,
        )

        return CornerResult(
            scores=scores,
            defects=all_defects,
            final_score=final_score,
            details={"per_corner_scores": scores},
        )

    def _analyze_single_corner(
        self, corner_name: str, image: np.ndarray,
    ) -> list[CornerDefect]:
        """Analyze a single corner image for defects.

        Args:
            corner_name: Position label (e.g., "top_left").
            image: BGR corner region image.

        Returns:
            List of defects found in this corner.
        """
        defects: list[CornerDefect] = []
        h, w = image.shape[:2]

        # --- Whitening detection ---
        whitening = self._detect_whitening(image, corner_name)
        if whitening is not None:
            defects.append(whitening)

        # --- Softening / rounding detection ---
        softening = self._detect_softening(image, corner_name)
        if softening is not None:
            defects.append(softening)

        # --- Deformation detection ---
        deformation = self._detect_deformation(image, corner_name)
        if deformation is not None:
            defects.append(deformation)

        return defects

    def _detect_whitening(
        self, image: np.ndarray, corner_name: str,
    ) -> Optional[CornerDefect]:
        """Detect whitening (bright spots indicating wear) in a corner.

        Whitening appears as unusually bright pixels near the corner edge,
        typically caused by handling wear that exposes the white card stock.
        """
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape

        # Create a mask focusing on the actual corner area (triangular region)
        mask = self._corner_mask(h, w, corner_name)
        masked = cv2.bitwise_and(gray, gray, mask=mask)

        # Count bright pixels in the corner region
        bright_pixels = np.sum((masked > self.whitening_threshold) & (mask > 0))
        total_pixels = np.sum(mask > 0)

        if total_pixels == 0:
            return None

        bright_ratio = bright_pixels / total_pixels

        if bright_ratio < self.whitening_area_pct:
            return None

        # Determine severity based on extent of whitening
        if bright_ratio > 0.30:
            severity = "severe"
            impact = 2.5
        elif bright_ratio > 0.15:
            severity = "major"
            impact = 1.5
        elif bright_ratio > 0.08:
            severity = "moderate"
            impact = 0.8
        else:
            severity = "minor"
            impact = 0.3

        confidence = min(1.0, bright_ratio / 0.30)

        return CornerDefect(
            corner=corner_name,
            defect_type="whitening",
            severity=severity,
            score_impact=impact,
            bbox_x=0, bbox_y=0, bbox_w=w, bbox_h=h,
            confidence=confidence,
            details={"bright_ratio": round(bright_ratio, 4)},
        )

    def _detect_softening(
        self, image: np.ndarray, corner_name: str,
    ) -> Optional[CornerDefect]:
        """Detect corner softening/rounding via contour analysis.

        A sharp corner has a tight angle; a soft/rounded corner has a
        larger arc radius. We measure this by looking at the curvature
        of the outermost contour near the corner.
        """
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape

        # Edge detection
        edges = cv2.Canny(gray, 50, 150)

        # Dilate to connect nearby edges
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        edges = cv2.dilate(edges, kernel, iterations=1)

        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        if not contours:
            return None

        # Find the largest contour (card edge)
        largest = max(contours, key=cv2.contourArea)
        arc_length = cv2.arcLength(largest, closed=False)
        area = cv2.contourArea(largest)

        if arc_length == 0:
            return None

        # Circularity ratio: higher means more rounded
        circularity = (4 * np.pi * area) / (arc_length * arc_length)

        # Approximate the contour and measure corner sharpness
        epsilon = 0.02 * arc_length
        approx = cv2.approxPolyDP(largest, epsilon, closed=False)

        # Measure the ratio of the approximated polygon arc vs bounding rect diagonal
        bounding_diag = np.sqrt(h**2 + w**2)
        if bounding_diag == 0:
            return None

        softening_ratio = circularity

        if softening_ratio < self.softening_threshold:
            return None

        if softening_ratio > 0.60:
            severity = "severe"
            impact = 2.5
        elif softening_ratio > 0.40:
            severity = "major"
            impact = 1.5
        elif softening_ratio > 0.25:
            severity = "moderate"
            impact = 0.5
        else:
            severity = "minor"
            impact = 0.0

        confidence = min(1.0, softening_ratio / 0.60)

        return CornerDefect(
            corner=corner_name,
            defect_type="softening",
            severity=severity,
            score_impact=impact,
            bbox_x=0, bbox_y=0, bbox_w=w, bbox_h=h,
            confidence=confidence,
            details={"softening_ratio": round(softening_ratio, 4), "circularity": round(circularity, 4)},
        )

    def _detect_deformation(
        self, image: np.ndarray, corner_name: str,
    ) -> Optional[CornerDefect]:
        """Detect corner deformation (dents, bends, folding).

        Compares the corner shape against an ideal right angle. Large
        deviations indicate physical damage.
        """
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape

        # Edge detection with stronger parameters for structural features
        edges = cv2.Canny(gray, 30, 120)

        # Find contours
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        if not contours:
            return None

        largest = max(contours, key=cv2.contourArea)

        # Use convexity defects to detect deformation
        hull = cv2.convexHull(largest, returnPoints=False)

        if len(largest) < 4 or len(hull) < 3:
            return None

        try:
            defects = cv2.convexityDefects(largest, hull)
        except cv2.error:
            return None

        if defects is None:
            return None

        # Calculate total deformation depth relative to corner size
        max_defect_depth = 0.0
        total_depth = 0.0
        corner_diag = np.sqrt(h**2 + w**2)

        for i in range(defects.shape[0]):
            _, _, _, depth = defects[i, 0]
            depth_ratio = (depth / 256.0) / corner_diag
            total_depth += depth_ratio
            max_defect_depth = max(max_defect_depth, depth_ratio)

        if max_defect_depth < self.deformation_threshold:
            return None

        if max_defect_depth > 0.60:
            severity = "severe"
            impact = 2.5
        elif max_defect_depth > 0.40:
            severity = "major"
            impact = 1.5
        elif max_defect_depth > 0.30:
            severity = "moderate"
            impact = 0.8
        else:
            severity = "minor"
            impact = 0.3

        confidence = min(1.0, max_defect_depth / 0.60)

        return CornerDefect(
            corner=corner_name,
            defect_type="deformation",
            severity=severity,
            score_impact=impact,
            bbox_x=0, bbox_y=0, bbox_w=w, bbox_h=h,
            confidence=confidence,
            details={"max_defect_depth": round(max_defect_depth, 4), "total_depth": round(total_depth, 4)},
        )

    @staticmethod
    def _corner_mask(h: int, w: int, corner_name: str) -> np.ndarray:
        """Create a triangular mask for the actual corner region.

        The triangle covers roughly 50% of the corner image, focusing
        on the area nearest the card's physical corner.
        """
        mask = np.zeros((h, w), dtype=np.uint8)

        if corner_name == "top_left":
            pts = np.array([[0, 0], [w, 0], [0, h]], dtype=np.int32)
        elif corner_name == "top_right":
            pts = np.array([[0, 0], [w, 0], [w, h]], dtype=np.int32)
        elif corner_name == "bottom_right":
            pts = np.array([[w, 0], [w, h], [0, h]], dtype=np.int32)
        else:  # bottom_left
            pts = np.array([[0, 0], [w, h], [0, h]], dtype=np.int32)

        cv2.fillPoly(mask, [pts], 255)
        return mask
