"""Surface analysis for card grading."""

import logging
from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np

from app.utils.validation import round_grade

logger = logging.getLogger(__name__)


@dataclass
class SurfaceDefect:
    """A single defect found on the card surface."""
    defect_type: str           # scratch, dent, stain, print_line, silvering
    severity: str              # minor, moderate, major, severe
    score_impact: float
    bbox_x: int = 0
    bbox_y: int = 0
    bbox_w: int = 0
    bbox_h: int = 0
    confidence: float = 0.0
    details: dict = field(default_factory=dict)


@dataclass
class SurfaceResult:
    """Result of surface analysis."""
    defects: list[SurfaceDefect]
    final_score: float
    details: dict = field(default_factory=dict)


def detect_holo_texture(image: np.ndarray) -> tuple[bool, float]:
    """Detect if a card image has holographic (holo) patterns.

    Holographic cards exhibit rainbow-like iridescent patches that cause
    high saturation variance across small spatial regions.  We divide the
    image into a grid of tiles and measure the standard deviation of the
    HSV saturation channel within each tile.  A high average tile-variance
    indicates holo texture.

    Args:
        image: BGR card surface image.

    Returns:
        Tuple of (is_holo, holo_score).
        - is_holo: True if holographic texture is detected.
        - holo_score: Confidence value 0.0-1.0.
    """
    if image is None or image.size == 0:
        return False, 0.0

    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    h_img, w_img = hsv.shape[:2]

    # Use a grid of small tiles to capture local saturation variance
    tile_size = max(16, min(h_img, w_img) // 10)
    sat_channel = hsv[:, :, 1].astype(np.float32)

    tile_stds: list[float] = []
    for y in range(0, h_img - tile_size, tile_size):
        for x in range(0, w_img - tile_size, tile_size):
            tile = sat_channel[y:y + tile_size, x:x + tile_size]
            tile_stds.append(float(np.std(tile)))

    if not tile_stds:
        return False, 0.0

    avg_std = float(np.mean(tile_stds))

    # Holo cards typically show avg tile saturation std > 35
    # (non-holo cards sit around 10-25)
    HOLO_THRESHOLD = 35.0
    HOLO_STRONG = 60.0

    is_holo = avg_std > HOLO_THRESHOLD
    holo_score = min(1.0, max(0.0, (avg_std - HOLO_THRESHOLD) / (HOLO_STRONG - HOLO_THRESHOLD)))

    logger.debug(
        "Holo detection: avg_tile_sat_std=%.1f, is_holo=%s, score=%.2f",
        avg_std, is_holo, holo_score,
    )

    return is_holo, holo_score


class SurfaceAnalyzer:
    """Analyze the surface (center region) of a trading card.

    Detects scratches (via Hough line transform), dents (shadow/depth
    analysis), stains (color anomaly detection), print lines, and
    silvering (metallic reflection artifacts).

    Supports a holo tolerance mode that raises scratch and stain
    thresholds by 30% to avoid false positives on holographic cards.
    """

    # Factor by which scratch/stain thresholds are raised for holo cards
    HOLO_THRESHOLD_FACTOR = 1.30

    def __init__(
        self,
        scratch_hough_threshold: int = 50,
        scratch_min_length: int = 30,
        scratch_max_gap: int = 10,
        dent_threshold: float = 0.15,
        stain_threshold: float = 0.08,
        print_line_threshold: int = 40,
        silvering_threshold: float = 0.05,
        holo_tolerance: bool = False,
    ):
        self.scratch_hough_threshold = scratch_hough_threshold
        self.scratch_min_length = scratch_min_length
        self.scratch_max_gap = scratch_max_gap
        self.dent_threshold = dent_threshold
        self.stain_threshold = stain_threshold
        self.print_line_threshold = print_line_threshold
        self.silvering_threshold = silvering_threshold
        self.holo_tolerance = holo_tolerance

        # Apply holo tolerance: raise scratch/stain thresholds by 30%
        if self.holo_tolerance:
            self.scratch_hough_threshold = int(
                self.scratch_hough_threshold * self.HOLO_THRESHOLD_FACTOR
            )
            self.scratch_min_length = int(
                self.scratch_min_length * self.HOLO_THRESHOLD_FACTOR
            )
            self.stain_threshold = self.stain_threshold * self.HOLO_THRESHOLD_FACTOR
            logger.info(
                "Holo tolerance active: scratch_hough=%d, scratch_min_len=%d, stain=%.3f",
                self.scratch_hough_threshold, self.scratch_min_length, self.stain_threshold,
            )

    def analyze(self, surface_image: Optional[np.ndarray]) -> SurfaceResult:
        """Analyze the surface region for defects.

        Args:
            surface_image: BGR image of the card's central surface region.

        Returns:
            SurfaceResult with defects and final score.
        """
        if surface_image is None or surface_image.size == 0:
            return SurfaceResult(defects=[], final_score=10.0)

        all_defects: list[SurfaceDefect] = []

        # Run all detectors
        scratches = self._detect_scratches(surface_image)
        all_defects.extend(scratches)

        dents = self._detect_dents(surface_image)
        all_defects.extend(dents)

        stains = self._detect_stains(surface_image)
        all_defects.extend(stains)

        print_lines = self._detect_print_lines(surface_image)
        all_defects.extend(print_lines)

        silvering = self._detect_silvering(surface_image)
        all_defects.extend(silvering)

        # Calculate score
        total_impact = sum(d.score_impact for d in all_defects)
        final_score = round_grade(max(1.0, 10.0 - total_impact))

        logger.debug(
            "Surface analysis: %d defects, total_impact=%.1f, final=%.1f (holo_tol=%s)",
            len(all_defects), total_impact, final_score, self.holo_tolerance,
        )

        return SurfaceResult(
            defects=all_defects,
            final_score=final_score,
            details={
                "defect_count": len(all_defects),
                "total_impact": round(total_impact, 2),
                "holo_tolerance": self.holo_tolerance,
            },
        )

    def _detect_scratches(self, image: np.ndarray) -> list[SurfaceDefect]:
        """Detect scratches using Hough Line Transform.

        Scratches appear as thin, linear features that differ from the
        card's printed content. We use edge detection followed by
        probabilistic Hough transform to find line segments.
        """
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape

        # Apply Gaussian blur to reduce noise
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)

        # Edge detection with tight thresholds to isolate scratches
        edges = cv2.Canny(blurred, 80, 200)

        # Apply morphological operations to thin edges
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 1))
        edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)

        # Probabilistic Hough Line Transform
        lines = cv2.HoughLinesP(
            edges,
            rho=1,
            theta=np.pi / 180,
            threshold=self.scratch_hough_threshold,
            minLineLength=self.scratch_min_length,
            maxLineGap=self.scratch_max_gap,
        )

        defects: list[SurfaceDefect] = []

        if lines is None:
            return defects

        for line in lines:
            x1, y1, x2, y2 = line[0]
            length = np.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)

            # Filter out very short detections (likely print artifacts)
            if length < self.scratch_min_length:
                continue

            # Calculate bounding box
            bx = min(x1, x2)
            by = min(y1, y2)
            bw = abs(x2 - x1) + 1
            bh = abs(y2 - y1) + 1

            # Severity based on length relative to surface
            surface_diag = np.sqrt(h ** 2 + w ** 2)
            length_ratio = length / surface_diag if surface_diag > 0 else 0

            if length_ratio > 0.30:
                severity = "severe"
                impact = 2.5
            elif length_ratio > 0.15:
                severity = "major"
                impact = 1.5
            elif length_ratio > 0.08:
                severity = "moderate"
                impact = 0.8
            else:
                severity = "minor"
                impact = 0.3

            confidence = min(1.0, length_ratio / 0.30)

            defects.append(SurfaceDefect(
                defect_type="scratch",
                severity=severity,
                score_impact=impact,
                bbox_x=bx, bbox_y=by, bbox_w=bw, bbox_h=bh,
                confidence=confidence,
                details={"length_px": round(length, 1), "length_ratio": round(length_ratio, 4)},
            ))

        # Limit to top-N most significant scratches to avoid noise
        defects.sort(key=lambda d: d.score_impact, reverse=True)
        return defects[:5]

    def _detect_dents(self, image: np.ndarray) -> list[SurfaceDefect]:
        """Detect dents via shadow/depth analysis.

        Dents create subtle shadow patterns visible as local brightness
        variations. We use Laplacian-based analysis to detect depth changes.
        """
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape

        # Laplacian for second-derivative (depth changes)
        laplacian = cv2.Laplacian(gray, cv2.CV_64F)
        abs_laplacian = np.abs(laplacian)

        # Normalise to 0-1
        max_val = abs_laplacian.max()
        if max_val == 0:
            return []
        normalised = abs_laplacian / max_val

        # Block-based analysis to find regions with high depth variation
        block_size = max(16, min(h, w) // 8)
        defects: list[SurfaceDefect] = []

        for y in range(0, h - block_size, block_size):
            for x in range(0, w - block_size, block_size):
                block = normalised[y:y + block_size, x:x + block_size]
                mean_depth = np.mean(block)

                if mean_depth < self.dent_threshold:
                    continue

                if mean_depth > 0.50:
                    severity = "severe"
                    impact = 2.0
                elif mean_depth > 0.35:
                    severity = "major"
                    impact = 1.0
                elif mean_depth > 0.20:
                    severity = "moderate"
                    impact = 0.5
                else:
                    severity = "minor"
                    impact = 0.0

                confidence = min(1.0, mean_depth / 0.50)

                defects.append(SurfaceDefect(
                    defect_type="dent",
                    severity=severity,
                    score_impact=impact,
                    bbox_x=x, bbox_y=y, bbox_w=block_size, bbox_h=block_size,
                    confidence=confidence,
                    details={"mean_depth": round(mean_depth, 4)},
                ))

        defects.sort(key=lambda d: d.score_impact, reverse=True)
        return defects[:3]

    def _detect_stains(self, image: np.ndarray) -> list[SurfaceDefect]:
        """Detect stains via color anomaly detection.

        Stains appear as regions with unusual colour deviation from the
        surrounding area. We use LAB colour space for perceptual accuracy.
        """
        h, w = image.shape[:2]

        # Convert to LAB for perceptual color difference
        lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB).astype(np.float32)

        # Compute overall mean colour
        mean_lab = np.mean(lab, axis=(0, 1))

        # Compute per-pixel colour distance from mean
        diff = np.sqrt(np.sum((lab - mean_lab) ** 2, axis=2))

        # Normalise
        max_diff = diff.max()
        if max_diff == 0:
            return []
        normalised = diff / max_diff

        # Threshold to find anomalous regions
        anomaly_mask = (normalised > self.stain_threshold * 10).astype(np.uint8) * 255

        # Morphological cleanup
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        anomaly_mask = cv2.morphologyEx(anomaly_mask, cv2.MORPH_OPEN, kernel)
        anomaly_mask = cv2.morphologyEx(anomaly_mask, cv2.MORPH_CLOSE, kernel)

        # Find contours of stained areas
        contours, _ = cv2.findContours(anomaly_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        defects: list[SurfaceDefect] = []
        surface_area = h * w

        for cnt in contours:
            area = cv2.contourArea(cnt)
            area_ratio = area / surface_area if surface_area > 0 else 0

            if area_ratio < 0.005:  # ignore tiny spots
                continue

            x, y, bw, bh = cv2.boundingRect(cnt)

            if area_ratio > 0.10:
                severity = "severe"
                impact = 2.5
            elif area_ratio > 0.05:
                severity = "major"
                impact = 1.5
            elif area_ratio > 0.02:
                severity = "moderate"
                impact = 0.8
            else:
                severity = "minor"
                impact = 0.3

            confidence = min(1.0, area_ratio / 0.10)

            defects.append(SurfaceDefect(
                defect_type="stain",
                severity=severity,
                score_impact=impact,
                bbox_x=x, bbox_y=y, bbox_w=bw, bbox_h=bh,
                confidence=confidence,
                details={"area_ratio": round(area_ratio, 4)},
            ))

        defects.sort(key=lambda d: d.score_impact, reverse=True)
        return defects[:3]

    def _detect_print_lines(self, image: np.ndarray) -> list[SurfaceDefect]:
        """Detect print lines (roller lines from printing process).

        Print lines are thin, regularly-spaced horizontal or vertical lines
        caused by printing rollers. Detected using frequency domain analysis.
        """
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape

        # Use FFT to detect periodic horizontal/vertical patterns
        f_transform = np.fft.fft2(gray.astype(np.float64))
        f_shift = np.fft.fftshift(f_transform)
        magnitude = np.log1p(np.abs(f_shift))

        # Normalise magnitude
        max_mag = magnitude.max()
        if max_mag == 0:
            return []
        norm_mag = magnitude / max_mag

        # Check for strong horizontal frequency bands (print roller lines)
        center_y, center_x = h // 2, w // 2

        # Horizontal lines create vertical frequency peaks
        vert_band = norm_mag[:, center_x - 2:center_x + 3]
        vert_energy = np.mean(vert_band)

        # Vertical lines create horizontal frequency peaks
        horiz_band = norm_mag[center_y - 2:center_y + 3, :]
        horiz_energy = np.mean(horiz_band)

        defects: list[SurfaceDefect] = []

        # Check if periodic line energy exceeds threshold
        for direction, energy in [("horizontal", vert_energy), ("vertical", horiz_energy)]:
            # Only flag if the periodic energy is significantly above baseline
            baseline = np.mean(norm_mag)
            if baseline == 0:
                continue
            ratio = energy / baseline

            threshold = 1.0 + self.print_line_threshold / 10.0

            if ratio < threshold:
                continue

            if ratio > 6.0:
                severity = "major"
                impact = 1.0
            elif ratio > 4.0:
                severity = "moderate"
                impact = 0.5
            else:
                severity = "minor"
                impact = 0.0

            confidence = min(1.0, (ratio - threshold) / 5.0)

            defects.append(SurfaceDefect(
                defect_type="print_line",
                severity=severity,
                score_impact=impact,
                bbox_x=0, bbox_y=0, bbox_w=w, bbox_h=h,
                confidence=confidence,
                details={"direction": direction, "energy_ratio": round(ratio, 2)},
            ))

        return defects

    def _detect_silvering(self, image: np.ndarray) -> list[SurfaceDefect]:
        """Detect silvering (metallic reflection artifacts).

        Silvering appears as bright, metallic-looking patches on the
        card surface, often along the edges of dark printed areas.
        It's detected by looking for high-saturation bright regions
        in specific colour ranges.
        """
        h, w = image.shape[:2]
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)

        # Silvering has low saturation but high value (bright metallic)
        # Look for pixels with very high brightness but low saturation
        sat = hsv[:, :, 1].astype(np.float32)
        val = hsv[:, :, 2].astype(np.float32)

        # Silvering: high value (>200), low saturation (<40)
        silver_mask = ((val > 200) & (sat < 40)).astype(np.uint8) * 255

        # Morphological cleanup
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        silver_mask = cv2.morphologyEx(silver_mask, cv2.MORPH_OPEN, kernel)

        # Calculate coverage
        silver_ratio = np.sum(silver_mask > 0) / (h * w) if (h * w) > 0 else 0

        if silver_ratio < self.silvering_threshold:
            return []

        # Find contours of silvered regions
        contours, _ = cv2.findContours(silver_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        defects: list[SurfaceDefect] = []

        for cnt in contours:
            area = cv2.contourArea(cnt)
            area_ratio = area / (h * w)

            if area_ratio < 0.003:
                continue

            x, y, bw, bh = cv2.boundingRect(cnt)

            if area_ratio > 0.08:
                severity = "severe"
                impact = 1.5
            elif area_ratio > 0.04:
                severity = "major"
                impact = 0.8
            elif area_ratio > 0.02:
                severity = "moderate"
                impact = 0.3
            else:
                severity = "minor"
                impact = 0.0

            confidence = min(1.0, area_ratio / 0.08)

            defects.append(SurfaceDefect(
                defect_type="silvering",
                severity=severity,
                score_impact=impact,
                bbox_x=x, bbox_y=y, bbox_w=bw, bbox_h=bh,
                confidence=confidence,
                details={"area_ratio": round(area_ratio, 4)},
            ))

        defects.sort(key=lambda d: d.score_impact, reverse=True)
        return defects[:3]
