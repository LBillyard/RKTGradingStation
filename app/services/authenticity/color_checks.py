"""Color-based authenticity checks for trading cards.

Compares color histograms and dominant colors against reference images,
and detects color inconsistencies that indicate counterfeit printing.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class ColorCheckDetail:
    """Result of a single color-based check."""
    check_name: str
    passed: bool
    confidence: float
    score: Optional[float] = None
    detail: str = ""


@dataclass
class ColorCheckResult:
    """Aggregated result of all color-based checks."""
    check_results: List[ColorCheckDetail] = field(default_factory=list)
    anomalies: List[str] = field(default_factory=list)
    passed: bool = True
    confidence: float = 1.0
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "check_results": [
                {
                    "check_name": cr.check_name,
                    "passed": cr.passed,
                    "confidence": cr.confidence,
                    "score": cr.score,
                    "detail": cr.detail,
                }
                for cr in self.check_results
            ],
            "anomalies": self.anomalies,
            "passed": self.passed,
            "confidence": self.confidence,
            "detail": self.detail,
        }


class ColorChecker:
    """Performs color-based authenticity checks on trading card images."""

    def __init__(self, histogram_threshold: float = 0.70,
                 consistency_threshold: float = 0.75,
                 brightness_threshold: float = 0.80,
                 dominant_color_threshold: float = 0.65,
                 top_n_colors: int = 5):
        self.histogram_threshold = histogram_threshold
        self.consistency_threshold = consistency_threshold
        self.brightness_threshold = brightness_threshold
        self.dominant_color_threshold = dominant_color_threshold
        self.top_n_colors = top_n_colors

    def _compute_histogram(self, image: np.ndarray,
                           channels: List[int] = None,
                           bins: int = 64) -> np.ndarray:
        """Compute a normalized color histogram for the given image."""
        if channels is None:
            channels = [0, 1, 2]

        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist(
            [hsv], channels, None,
            [bins] * len(channels),
            [0, 180, 0, 256, 0, 256][:len(channels) * 2],
        )
        cv2.normalize(hist, hist, 0, 1, cv2.NORM_MINMAX)
        return hist

    def compare_histogram(self, scan_image: np.ndarray,
                          reference_image: np.ndarray) -> ColorCheckDetail:
        """Compare color histograms between scan and reference using correlation.

        Args:
            scan_image: BGR numpy array of the scanned card.
            reference_image: BGR numpy array of the reference card.

        Returns:
            ColorCheckDetail with correlation score.
        """
        try:
            scan_hist = self._compute_histogram(scan_image, channels=[0, 1])
            ref_hist = self._compute_histogram(reference_image, channels=[0, 1])

            correlation = cv2.compareHist(
                scan_hist.flatten().astype(np.float32),
                ref_hist.flatten().astype(np.float32),
                cv2.HISTCMP_CORREL,
            )
            # Correlation ranges from -1 to 1; normalize to 0-1
            score = max(0.0, (correlation + 1.0) / 2.0)
            passed = score >= self.histogram_threshold

            return ColorCheckDetail(
                check_name="histogram_comparison",
                passed=passed,
                confidence=round(score, 4),
                score=round(correlation, 4),
                detail=f"Histogram correlation: {correlation:.4f} ({'pass' if passed else 'fail'})",
            )
        except Exception as e:
            logger.warning(f"Histogram comparison failed: {e}")
            return ColorCheckDetail(
                check_name="histogram_comparison",
                passed=True,
                confidence=0.5,
                detail=f"Histogram comparison error: {e}",
            )

    def check_color_consistency(self, image: np.ndarray) -> ColorCheckDetail:
        """Detect inconsistent color regions that indicate print artifacts.

        Divides the image into a grid and checks for unusual color variance
        between adjacent regions, which can indicate inkjet banding or
        misaligned print heads.
        """
        try:
            h, w = image.shape[:2]
            grid_rows, grid_cols = 8, 6
            cell_h, cell_w = h // grid_rows, w // grid_cols

            if cell_h < 10 or cell_w < 10:
                return ColorCheckDetail(
                    check_name="color_consistency",
                    passed=True,
                    confidence=0.5,
                    detail="Image too small for grid-based consistency analysis",
                )

            hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
            cell_means = []

            for r in range(grid_rows):
                row_means = []
                for c in range(grid_cols):
                    y1, y2 = r * cell_h, (r + 1) * cell_h
                    x1, x2 = c * cell_w, (c + 1) * cell_w
                    cell = hsv[y1:y2, x1:x2]
                    row_means.append(cell.mean(axis=(0, 1)))
                cell_means.append(row_means)

            # Compare adjacent cells for abrupt color changes
            abrupt_changes = 0
            total_comparisons = 0

            for r in range(grid_rows):
                for c in range(grid_cols):
                    # Compare with right neighbor
                    if c + 1 < grid_cols:
                        diff = np.linalg.norm(
                            cell_means[r][c] - cell_means[r][c + 1]
                        )
                        total_comparisons += 1
                        if diff > 80:  # Significant color jump
                            abrupt_changes += 1
                    # Compare with bottom neighbor
                    if r + 1 < grid_rows:
                        diff = np.linalg.norm(
                            cell_means[r][c] - cell_means[r + 1][c]
                        )
                        total_comparisons += 1
                        if diff > 80:
                            abrupt_changes += 1

            if total_comparisons == 0:
                ratio = 0.0
            else:
                ratio = abrupt_changes / total_comparisons

            # Low ratio = consistent colors = good
            # Cards naturally have some color transitions (artwork edges), so
            # we allow up to ~25% of adjacent cells to differ significantly
            score = max(0.0, 1.0 - (ratio / 0.40))
            passed = score >= self.consistency_threshold

            return ColorCheckDetail(
                check_name="color_consistency",
                passed=passed,
                confidence=round(score, 4),
                score=round(ratio, 4),
                detail=f"Color discontinuity ratio: {ratio:.2%} ({abrupt_changes}/{total_comparisons} cells)",
            )
        except Exception as e:
            logger.warning(f"Color consistency check failed: {e}")
            return ColorCheckDetail(
                check_name="color_consistency",
                passed=True,
                confidence=0.5,
                detail=f"Color consistency error: {e}",
            )

    def check_brightness_uniformity(self, image: np.ndarray) -> ColorCheckDetail:
        """Detect unusual brightness variations across the card.

        Genuine cards printed with offset lithography have very uniform
        brightness. Inkjet or laser reprints often show banding or uneven
        toner distribution.
        """
        try:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            h, w = gray.shape

            # Divide into horizontal strips and compare brightness
            num_strips = 16
            strip_h = h // num_strips
            if strip_h < 5:
                return ColorCheckDetail(
                    check_name="brightness_uniformity",
                    passed=True,
                    confidence=0.5,
                    detail="Image too small for brightness analysis",
                )

            strip_means = []
            for i in range(num_strips):
                y1, y2 = i * strip_h, (i + 1) * strip_h
                strip = gray[y1:y2, :]
                strip_means.append(float(strip.mean()))

            # Calculate variance of strip means relative to global mean
            global_mean = np.mean(strip_means)
            if global_mean < 1.0:
                global_mean = 1.0

            # Coefficient of variation (normalized std)
            std_dev = float(np.std(strip_means))
            cv = std_dev / global_mean

            # Check for banding pattern: alternating high/low strips
            diffs = [abs(strip_means[i] - strip_means[i + 1]) for i in range(len(strip_means) - 1)]
            max_diff = max(diffs) if diffs else 0
            avg_diff = np.mean(diffs) if diffs else 0

            # Good cards have low CV (< 0.15) and low avg diff
            score = max(0.0, 1.0 - (cv / 0.30))
            passed = score >= self.brightness_threshold

            detail_parts = [f"Brightness CV: {cv:.4f}"]
            if max_diff > 30:
                detail_parts.append(f"Max strip brightness jump: {max_diff:.1f}")
            if cv > 0.20:
                detail_parts.append("Significant brightness banding detected")

            return ColorCheckDetail(
                check_name="brightness_uniformity",
                passed=passed,
                confidence=round(score, 4),
                score=round(cv, 4),
                detail="; ".join(detail_parts),
            )
        except Exception as e:
            logger.warning(f"Brightness uniformity check failed: {e}")
            return ColorCheckDetail(
                check_name="brightness_uniformity",
                passed=True,
                confidence=0.5,
                detail=f"Brightness uniformity error: {e}",
            )

    def _extract_dominant_colors(self, image: np.ndarray,
                                 n: int = 5) -> List[Tuple[float, ...]]:
        """Extract top-N dominant colors using K-means clustering."""
        # Resize for speed
        small = cv2.resize(image, (100, 140))
        pixels = small.reshape(-1, 3).astype(np.float32)

        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
        _, labels, centers = cv2.kmeans(
            pixels, n, None, criteria, 3, cv2.KMEANS_PP_CENTERS,
        )

        # Sort by cluster size (most dominant first)
        counts = np.bincount(labels.flatten())
        sorted_indices = np.argsort(-counts)
        sorted_centers = centers[sorted_indices]

        return [tuple(c) for c in sorted_centers.tolist()]

    def compare_dominant_colors(self, scan_image: np.ndarray,
                                reference_image: np.ndarray) -> ColorCheckDetail:
        """Compare top-N dominant colors between scan and reference.

        Uses minimum-distance matching between color cluster centers.
        """
        try:
            scan_colors = self._extract_dominant_colors(scan_image, self.top_n_colors)
            ref_colors = self._extract_dominant_colors(reference_image, self.top_n_colors)

            # For each scan color, find the closest reference color
            total_dist = 0.0
            for sc in scan_colors:
                sc_arr = np.array(sc)
                min_dist = min(np.linalg.norm(sc_arr - np.array(rc)) for rc in ref_colors)
                total_dist += min_dist

            # Normalize: max possible distance per color in BGR space is ~441 (sqrt(255^2*3))
            max_possible = 441.0 * self.top_n_colors
            avg_dist = total_dist / max_possible

            score = max(0.0, 1.0 - avg_dist * 2.5)  # Scale so 0.40 norm distance = 0.0
            passed = score >= self.dominant_color_threshold

            return ColorCheckDetail(
                check_name="dominant_colors",
                passed=passed,
                confidence=round(score, 4),
                score=round(avg_dist, 4),
                detail=f"Dominant color distance: {avg_dist:.4f} ({'pass' if passed else 'fail'})",
            )
        except Exception as e:
            logger.warning(f"Dominant color comparison failed: {e}")
            return ColorCheckDetail(
                check_name="dominant_colors",
                passed=True,
                confidence=0.5,
                detail=f"Dominant color comparison error: {e}",
            )

    async def run_all_checks(self, scan_image: np.ndarray,
                             reference_image: Optional[np.ndarray] = None) -> ColorCheckResult:
        """Run all color checks and return aggregated result.

        If no reference image is available, only consistency and brightness
        checks are performed; comparison checks are skipped.

        Args:
            scan_image: BGR numpy array of the scanned card.
            reference_image: Optional BGR numpy array of the reference card.

        Returns:
            ColorCheckResult with per-check results and overall pass/fail.
        """
        results: List[ColorCheckDetail] = []

        # Comparison checks (require reference)
        if reference_image is not None:
            hist_result = await asyncio.to_thread(
                self.compare_histogram, scan_image, reference_image
            )
            results.append(hist_result)

            dom_result = await asyncio.to_thread(
                self.compare_dominant_colors, scan_image, reference_image
            )
            results.append(dom_result)
        else:
            logger.info("No reference image available; skipping color comparison checks")
            results.append(ColorCheckDetail(
                check_name="histogram_comparison",
                passed=True,
                confidence=0.5,
                detail="Skipped: no reference image available",
            ))
            results.append(ColorCheckDetail(
                check_name="dominant_colors",
                passed=True,
                confidence=0.5,
                detail="Skipped: no reference image available",
            ))

        # Standalone checks (always run)
        consistency_result = await asyncio.to_thread(
            self.check_color_consistency, scan_image
        )
        results.append(consistency_result)

        brightness_result = await asyncio.to_thread(
            self.check_brightness_uniformity, scan_image
        )
        results.append(brightness_result)

        # Aggregate
        all_passed = all(r.passed for r in results)

        total_weight = 0.0
        weighted_sum = 0.0
        for r in results:
            has_real_data = r.confidence != 0.5 or not r.detail.startswith("Skipped")
            w = 1.0 if has_real_data else 0.2
            weighted_sum += r.confidence * w
            total_weight += w

        overall_confidence = weighted_sum / total_weight if total_weight > 0 else 0.5
        anomalies = [r.detail for r in results if not r.passed]

        return ColorCheckResult(
            check_results=results,
            anomalies=anomalies,
            passed=all_passed,
            confidence=round(overall_confidence, 4),
            detail=f"{sum(1 for r in results if r.passed)}/{len(results)} color checks passed",
        )
