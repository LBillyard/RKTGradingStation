"""Print pattern authenticity checks for trading cards.

Uses FFT analysis and texture metrics to distinguish genuine offset-printed
cards from inkjet/laser counterfeits. Genuine trading cards exhibit a
consistent halftone rosette pattern from offset lithography.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class PatternCheckDetail:
    """Result of a single pattern-based check."""
    check_name: str
    passed: bool
    confidence: float
    score: Optional[float] = None
    detail: str = ""


@dataclass
class PatternCheckResult:
    """Aggregated result of all pattern-based checks."""
    check_results: List[PatternCheckDetail] = field(default_factory=list)
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


class PatternChecker:
    """Performs print pattern analysis for card authenticity verification."""

    def __init__(self, rosette_threshold: float = 0.60,
                 inkjet_threshold: float = 0.70,
                 texture_threshold: float = 0.65):
        self.rosette_threshold = rosette_threshold
        self.inkjet_threshold = inkjet_threshold
        self.texture_threshold = texture_threshold

    def check_print_pattern(self, image: np.ndarray) -> PatternCheckDetail:
        """Analyze the halftone dot pattern using FFT.

        Genuine offset-printed cards produce a characteristic rosette pattern
        visible in the frequency domain as distinct peaks at the halftone
        screen angles. Counterfeits lack this pattern or show different
        frequency signatures.
        """
        try:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            h, w = gray.shape

            # Use a center crop for analysis to avoid border effects
            crop_size = min(h, w, 512)
            cy, cx = h // 2, w // 2
            crop = gray[
                cy - crop_size // 2:cy + crop_size // 2,
                cx - crop_size // 2:cx + crop_size // 2,
            ]

            # Apply window function to reduce spectral leakage
            window = np.outer(np.hanning(crop.shape[0]), np.hanning(crop.shape[1]))
            windowed = crop.astype(np.float64) * window

            # Compute FFT and magnitude spectrum
            fft = np.fft.fft2(windowed)
            fft_shift = np.fft.fftshift(fft)
            magnitude = np.log1p(np.abs(fft_shift))

            # Analyze frequency domain for halftone peaks
            # Genuine offset printing produces peaks at specific frequencies
            # corresponding to the halftone screen ruling (typically 150-200 LPI)
            fh, fw = magnitude.shape
            center_y, center_x = fh // 2, fw // 2

            # Create radial profile
            y_coords, x_coords = np.ogrid[:fh, :fw]
            radius = np.sqrt((y_coords - center_y) ** 2 + (x_coords - center_x) ** 2)

            # Analyze mid-frequency band (where halftone peaks appear)
            # For 600 DPI scans, halftone at 150 LPI appears at ~25% of Nyquist
            min_r = int(0.15 * min(fh, fw) / 2)
            max_r = int(0.40 * min(fh, fw) / 2)

            mid_band = magnitude.copy()
            mid_band[radius < min_r] = 0
            mid_band[radius > max_r] = 0

            # Look for peak concentration (rosette pattern has distinct peaks)
            if mid_band.max() < 1e-6:
                return PatternCheckDetail(
                    check_name="print_pattern",
                    passed=True,
                    confidence=0.5,
                    detail="Insufficient frequency content for analysis",
                )

            # Peak analysis: genuine cards have a few strong peaks in the mid-band
            threshold_val = mid_band.mean() + 2.0 * mid_band.std()
            peak_mask = mid_band > threshold_val
            peak_count = int(peak_mask.sum())
            total_pixels = int((radius >= min_r).sum() & (radius <= max_r).sum())

            if total_pixels == 0:
                peak_density = 0.0
            else:
                peak_density = peak_count / max(total_pixels, 1)

            # Genuine rosette patterns have moderate peak density
            # Too few peaks = no pattern (solid digital print)
            # Too many peaks = noise (poor quality print)
            # Sweet spot: 0.001 - 0.05 of mid-band pixels are peaks
            if 0.001 <= peak_density <= 0.05:
                rosette_score = 1.0 - abs(peak_density - 0.015) / 0.035
            elif peak_density < 0.001:
                rosette_score = peak_density / 0.001 * 0.5
            else:
                rosette_score = max(0.0, 0.5 - (peak_density - 0.05) / 0.1)

            rosette_score = max(0.0, min(1.0, rosette_score))
            passed = rosette_score >= self.rosette_threshold

            return PatternCheckDetail(
                check_name="print_pattern",
                passed=passed,
                confidence=round(rosette_score, 4),
                score=round(peak_density, 6),
                detail=f"Halftone peak density: {peak_density:.6f}, rosette score: {rosette_score:.4f}",
            )
        except Exception as e:
            logger.warning(f"Print pattern analysis failed: {e}")
            return PatternCheckDetail(
                check_name="print_pattern",
                passed=True,
                confidence=0.5,
                detail=f"Print pattern analysis error: {e}",
            )

    def detect_inkjet_artifacts(self, image: np.ndarray) -> PatternCheckDetail:
        """Detect inkjet-specific printing artifacts.

        Inkjet prints show characteristic banding (horizontal lines from
        print-head passes) and dot patterns that differ from offset
        lithography. This check looks for periodic horizontal artifacts.
        """
        try:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            h, w = gray.shape

            if h < 100 or w < 100:
                return PatternCheckDetail(
                    check_name="inkjet_artifacts",
                    passed=True,
                    confidence=0.5,
                    detail="Image too small for inkjet artifact detection",
                )

            # Analyze horizontal scan lines for banding
            # Compute row-wise mean intensity
            row_means = gray.mean(axis=1).astype(np.float64)

            # High-pass filter to isolate banding frequency
            kernel_size = min(31, h // 4)
            if kernel_size % 2 == 0:
                kernel_size += 1

            smoothed = cv2.GaussianBlur(
                row_means.reshape(-1, 1), (1, kernel_size), 0
            ).flatten()
            residual = row_means - smoothed

            # FFT of the residual to find periodic banding
            fft_residual = np.abs(np.fft.rfft(residual))
            if len(fft_residual) < 10:
                return PatternCheckDetail(
                    check_name="inkjet_artifacts",
                    passed=True,
                    confidence=0.5,
                    detail="Insufficient data for banding analysis",
                )

            # Skip DC component and very low frequencies
            fft_residual[:3] = 0
            peak_freq_idx = int(np.argmax(fft_residual))
            peak_power = float(fft_residual[peak_freq_idx])
            mean_power = float(fft_residual.mean())

            # Strong periodic peak relative to mean indicates banding
            if mean_power < 1e-6:
                power_ratio = 0.0
            else:
                power_ratio = peak_power / mean_power

            # High ratio = strong periodic banding = likely inkjet
            # Genuine offset cards have power_ratio typically < 5
            if power_ratio < 4.0:
                score = 1.0  # No banding detected = likely genuine
            elif power_ratio < 8.0:
                score = 1.0 - (power_ratio - 4.0) / 8.0  # Transition zone
            else:
                score = max(0.0, 0.5 - (power_ratio - 8.0) / 20.0)

            score = max(0.0, min(1.0, score))
            passed = score >= self.inkjet_threshold

            detail_parts = [f"Banding power ratio: {power_ratio:.2f}"]
            if power_ratio >= 4.0:
                # Convert frequency index to physical period
                period_lines = h / max(peak_freq_idx, 1)
                detail_parts.append(f"Banding period: ~{period_lines:.0f} lines")
            if not passed:
                detail_parts.append("Inkjet banding pattern detected")

            return PatternCheckDetail(
                check_name="inkjet_artifacts",
                passed=passed,
                confidence=round(score, 4),
                score=round(power_ratio, 4),
                detail="; ".join(detail_parts),
            )
        except Exception as e:
            logger.warning(f"Inkjet artifact detection failed: {e}")
            return PatternCheckDetail(
                check_name="inkjet_artifacts",
                passed=True,
                confidence=0.5,
                detail=f"Inkjet artifact detection error: {e}",
            )

    def check_surface_texture(self, image: np.ndarray) -> PatternCheckDetail:
        """Analyze surface texture for card stock consistency.

        Genuine cards have a consistent micro-texture from the card stock.
        Counterfeits printed on different paper show different texture
        characteristics detectable via local variance analysis.
        """
        try:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            h, w = gray.shape

            if h < 50 or w < 50:
                return PatternCheckDetail(
                    check_name="surface_texture",
                    passed=True,
                    confidence=0.5,
                    detail="Image too small for texture analysis",
                )

            # Compute local variance using a sliding window
            gray_f = gray.astype(np.float64)
            kernel_size = 7
            local_mean = cv2.blur(gray_f, (kernel_size, kernel_size))
            local_sq_mean = cv2.blur(gray_f ** 2, (kernel_size, kernel_size))
            local_var = local_sq_mean - local_mean ** 2
            local_var = np.maximum(local_var, 0)  # Clamp numerical noise

            # Analyze variance distribution
            mean_var = float(local_var.mean())
            std_var = float(local_var.std())

            if mean_var < 1e-6:
                return PatternCheckDetail(
                    check_name="surface_texture",
                    passed=True,
                    confidence=0.5,
                    detail="Uniform image; cannot assess texture",
                )

            # Coefficient of variation of local variance
            # Genuine cards have moderate, consistent texture (CV around 1.0-2.5)
            # Flat inkjet prints have very low variance (CV < 0.5)
            # Noisy scans have very high variance (CV > 4.0)
            cv_var = std_var / mean_var

            if 0.5 <= cv_var <= 3.5:
                score = 1.0 - abs(cv_var - 1.8) / 2.0
            elif cv_var < 0.5:
                score = cv_var / 0.5 * 0.4
            else:
                score = max(0.0, 0.5 - (cv_var - 3.5) / 5.0)

            score = max(0.0, min(1.0, score))
            passed = score >= self.texture_threshold

            detail_parts = [
                f"Texture variance CV: {cv_var:.3f}",
                f"Mean local variance: {mean_var:.1f}",
            ]
            if cv_var < 0.5:
                detail_parts.append("Unusually smooth surface (possible digital print)")
            elif cv_var > 3.5:
                detail_parts.append("Unusually rough/noisy texture")

            return PatternCheckDetail(
                check_name="surface_texture",
                passed=passed,
                confidence=round(score, 4),
                score=round(cv_var, 4),
                detail="; ".join(detail_parts),
            )
        except Exception as e:
            logger.warning(f"Surface texture check failed: {e}")
            return PatternCheckDetail(
                check_name="surface_texture",
                passed=True,
                confidence=0.5,
                detail=f"Surface texture error: {e}",
            )

    async def run_all_checks(self, image: np.ndarray) -> PatternCheckResult:
        """Run all pattern checks and return aggregated result.

        Args:
            image: BGR numpy array of the scanned card.

        Returns:
            PatternCheckResult with per-check results and overall pass/fail.
        """
        results: List[PatternCheckDetail] = []

        print_result = await asyncio.to_thread(self.check_print_pattern, image)
        results.append(print_result)

        inkjet_result = await asyncio.to_thread(self.detect_inkjet_artifacts, image)
        results.append(inkjet_result)

        texture_result = await asyncio.to_thread(self.check_surface_texture, image)
        results.append(texture_result)

        # Aggregate
        all_passed = all(r.passed for r in results)

        total_weight = 0.0
        weighted_sum = 0.0
        for r in results:
            has_real_data = r.confidence != 0.5 or not r.detail.endswith("error")
            w = 1.0 if has_real_data else 0.2
            weighted_sum += r.confidence * w
            total_weight += w

        overall_confidence = weighted_sum / total_weight if total_weight > 0 else 0.5
        anomalies = [r.detail for r in results if not r.passed]

        return PatternCheckResult(
            check_results=results,
            anomalies=anomalies,
            passed=all_passed,
            confidence=round(overall_confidence, 4),
            detail=f"{sum(1 for r in results if r.passed)}/{len(results)} pattern checks passed",
        )
