"""Card orientation detection and correction.

Ensures cards are displayed the correct way up after perspective correction.
Trading cards (Pokemon, etc.) have text/info at the bottom and artwork at
the top.  This module detects if the card is upside-down and rotates 180
degrees if necessary.
"""

import logging

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# What fraction of the card height to sample from top and bottom
_STRIP_RATIO = 0.15


class OrientationCorrector:
    """Detect and fix upside-down cards after perspective correction."""

    def __init__(self, strip_ratio: float = _STRIP_RATIO):
        self.strip_ratio = strip_ratio

    def correct(self, image: np.ndarray) -> tuple[np.ndarray, bool]:
        """Return (oriented_image, was_rotated).

        Strategy
        --------
        Pokemon / trading cards have dense text in the bottom ~15 % of the
        card (card name, HP, attacks, set info, etc.) and mostly artwork in
        the top ~15 %.  We compare horizontal-edge density and text-like
        feature density between the top and bottom strips.  If the top strip
        has significantly more text features than the bottom, the card is
        upside-down and we rotate 180 degrees.

        We use three complementary signals and vote:
        1. Horizontal Sobel edge density (text lines produce strong
           horizontal edges).
        2. High-frequency variance in small blocks — text regions have
           much higher local variance than plain artwork.
        3. Connected-component density from adaptive thresholding — text
           produces many small connected components.
        """
        h, w = image.shape[:2]
        strip_h = max(int(h * self.strip_ratio), 10)

        top_strip = image[0:strip_h, :]
        bottom_strip = image[h - strip_h:h, :]

        top_score = self._text_score(top_strip)
        bottom_score = self._text_score(bottom_strip)

        # If the top has notably more text-like features the card is
        # upside-down.  A ratio threshold of 1.3 works well — if the
        # top strip scores 30 % higher than the bottom, flip.
        threshold = 1.3
        if bottom_score > 0 and top_score / bottom_score > threshold:
            rotated = cv2.rotate(image, cv2.ROTATE_180)
            logger.info(
                "Card detected as upside-down (top_score=%.1f, "
                "bottom_score=%.1f, ratio=%.2f) — rotating 180°",
                top_score,
                bottom_score,
                top_score / bottom_score,
            )
            return rotated, True

        # Also handle the edge case where bottom_score is 0 but top has
        # significant features
        if bottom_score == 0 and top_score > 10:
            rotated = cv2.rotate(image, cv2.ROTATE_180)
            logger.info(
                "Card detected as upside-down (top_score=%.1f, "
                "bottom_score=0) — rotating 180°",
                top_score,
            )
            return rotated, True

        logger.debug(
            "Card orientation OK (top_score=%.1f, bottom_score=%.1f)",
            top_score,
            bottom_score,
        )
        return image, False

    # ------------------------------------------------------------------
    # Internal scoring helpers
    # ------------------------------------------------------------------

    def _text_score(self, strip: np.ndarray) -> float:
        """Compute a composite text-likelihood score for an image strip.

        Higher score = more text-like features.
        """
        if strip.size == 0:
            return 0.0

        gray = cv2.cvtColor(strip, cv2.COLOR_BGR2GRAY) if strip.ndim == 3 else strip

        s1 = self._horizontal_edge_density(gray)
        s2 = self._local_variance_score(gray)
        s3 = self._connected_component_density(gray)

        # Weighted combination — horizontal edges and CC density are the
        # strongest text indicators.
        return 0.35 * s1 + 0.30 * s2 + 0.35 * s3

    @staticmethod
    def _horizontal_edge_density(gray: np.ndarray) -> float:
        """Fraction of pixels with strong horizontal Sobel response."""
        sobel_h = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
        strong = np.abs(sobel_h) > 30
        density = strong.sum() / max(gray.size, 1) * 100
        return float(density)

    @staticmethod
    def _local_variance_score(gray: np.ndarray) -> float:
        """Mean local variance in 8x8 blocks — text has high variance."""
        h, w = gray.shape
        block = 8
        if h < block or w < block:
            return 0.0

        # Trim to multiple of block size
        th = (h // block) * block
        tw = (w // block) * block
        trimmed = gray[:th, :tw].astype(np.float32)

        # Reshape into blocks and compute variance per block
        blocks = trimmed.reshape(th // block, block, tw // block, block)
        variances = blocks.var(axis=(1, 3))
        # Normalise: high-variance blocks (> 200) are very text-like
        high_var_ratio = (variances > 200).sum() / max(variances.size, 1) * 100
        return float(high_var_ratio)

    @staticmethod
    def _connected_component_density(gray: np.ndarray) -> float:
        """Number of small connected components per 1000 pixels.

        Text produces many small CCs; artwork has fewer, larger blobs.
        """
        h, w = gray.shape
        if h < 4 or w < 4:
            return 0.0

        binary = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV, 15, 5,
        )
        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
            binary, connectivity=8,
        )

        # Count small components (area between 4 and 500 px) — these are
        # individual letter strokes / glyphs
        areas = stats[1:, cv2.CC_STAT_AREA]  # skip background
        small = ((areas >= 4) & (areas <= 500)).sum()

        total_pixels = max(h * w, 1)
        density = small / total_pixels * 1000
        return float(density)
