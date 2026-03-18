"""Reference image comparison tools.

Provides SSIM, histogram, ORB feature matching, and difference heat-map
generation for comparing scanned card images against reference images.
"""

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from app.config import settings
from app.utils.image_utils import load_image, save_image

logger = logging.getLogger(__name__)

# Directory where debug artefacts (heat-maps, etc.) are stored
DEBUG_DIR = Path(settings.data_dir) / "debug"


@dataclass
class ComparisonResult:
    """Aggregated result of all comparison methods."""

    ssim_score: float = 0.0
    histogram_score: float = 0.0
    orb_match_count: int = 0
    orb_match_pct: float = 0.0
    diff_heatmap_path: Optional[str] = None
    overall_similarity: float = 0.0

    def to_dict(self):
        return {
            "ssim_score": round(self.ssim_score, 4),
            "histogram_score": round(self.histogram_score, 4),
            "orb_match_count": self.orb_match_count,
            "orb_match_pct": round(self.orb_match_pct, 4),
            "diff_heatmap_path": self.diff_heatmap_path,
            "overall_similarity": round(self.overall_similarity, 4),
        }


class ReferenceComparer:
    """Compare a scan image against a reference image using multiple methods.

    All heavy OpenCV work is wrapped with ``asyncio.to_thread`` so the
    methods can be awaited from async code without blocking the event loop.
    """

    # Standard dimensions both images are resized to before comparison
    _COMPARE_H = 400
    _COMPARE_W = 300

    # ------------------------------------------------------------------
    # Individual comparison methods (synchronous, CPU-bound)
    # ------------------------------------------------------------------

    def compare_ssim(self, scan_image: np.ndarray, reference_image: np.ndarray) -> float:
        """Structural Similarity Index between two images (0-1).

        Uses the same SSIM implementation as the existing VisualMatcher
        so results are consistent across the application.
        """
        img1 = cv2.resize(scan_image, (self._COMPARE_W, self._COMPARE_H))
        img2 = cv2.resize(reference_image, (self._COMPARE_W, self._COMPARE_H))

        gray1 = cv2.cvtColor(img1, cv2.COLOR_BGR2GRAY).astype(np.float64)
        gray2 = cv2.cvtColor(img2, cv2.COLOR_BGR2GRAY).astype(np.float64)

        c1 = (0.01 * 255) ** 2
        c2 = (0.03 * 255) ** 2

        mu1 = cv2.GaussianBlur(gray1, (11, 11), 1.5)
        mu2 = cv2.GaussianBlur(gray2, (11, 11), 1.5)

        mu1_sq = mu1 ** 2
        mu2_sq = mu2 ** 2
        mu1_mu2 = mu1 * mu2

        sigma1_sq = cv2.GaussianBlur(gray1 ** 2, (11, 11), 1.5) - mu1_sq
        sigma2_sq = cv2.GaussianBlur(gray2 ** 2, (11, 11), 1.5) - mu2_sq
        sigma12 = cv2.GaussianBlur(gray1 * gray2, (11, 11), 1.5) - mu1_mu2

        ssim_map = ((2 * mu1_mu2 + c1) * (2 * sigma12 + c2)) / (
            (mu1_sq + mu2_sq + c1) * (sigma1_sq + sigma2_sq + c2)
        )
        return float(np.mean(ssim_map))

    def compare_histogram(self, scan_image: np.ndarray, reference_image: np.ndarray) -> float:
        """Colour-histogram correlation score (-1 to 1, higher is better)."""
        h, w = 200, 150
        img1 = cv2.resize(scan_image, (w, h))
        img2 = cv2.resize(reference_image, (w, h))

        hist1 = cv2.calcHist([img1], [0, 1, 2], None, [8, 8, 8], [0, 256, 0, 256, 0, 256])
        hist2 = cv2.calcHist([img2], [0, 1, 2], None, [8, 8, 8], [0, 256, 0, 256, 0, 256])

        cv2.normalize(hist1, hist1)
        cv2.normalize(hist2, hist2)

        return float(cv2.compareHist(hist1, hist2, cv2.HISTCMP_CORREL))

    def compare_orb_features(
        self, scan_image: np.ndarray, reference_image: np.ndarray
    ) -> tuple[int, float]:
        """ORB keypoint matching.

        Returns ``(match_count, match_percentage)`` where
        *match_percentage* is the ratio of good matches to total keypoints
        detected in the scan image (0-1).
        """
        img1 = cv2.resize(scan_image, (self._COMPARE_W, self._COMPARE_H))
        img2 = cv2.resize(reference_image, (self._COMPARE_W, self._COMPARE_H))

        gray1 = cv2.cvtColor(img1, cv2.COLOR_BGR2GRAY)
        gray2 = cv2.cvtColor(img2, cv2.COLOR_BGR2GRAY)

        orb = cv2.ORB_create(nfeatures=500)
        kp1, des1 = orb.detectAndCompute(gray1, None)
        kp2, des2 = orb.detectAndCompute(gray2, None)

        if des1 is None or des2 is None or len(kp1) == 0:
            return 0, 0.0

        bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
        matches = bf.knnMatch(des1, des2, k=2)

        # Lowe's ratio test
        good_matches = []
        for pair in matches:
            if len(pair) == 2:
                m, n = pair
                if m.distance < 0.75 * n.distance:
                    good_matches.append(m)

        match_count = len(good_matches)
        match_pct = match_count / len(kp1) if len(kp1) > 0 else 0.0
        return match_count, match_pct

    def generate_diff_heatmap(
        self,
        scan_image: np.ndarray,
        reference_image: np.ndarray,
        output_name: Optional[str] = None,
    ) -> Optional[str]:
        """Generate an absolute-difference heat-map and save it to *data/debug/*.

        Returns the path to the saved heat-map image, or ``None`` on failure.
        """
        try:
            img1 = cv2.resize(scan_image, (self._COMPARE_W, self._COMPARE_H))
            img2 = cv2.resize(reference_image, (self._COMPARE_W, self._COMPARE_H))

            diff = cv2.absdiff(img1, img2)
            gray_diff = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)

            # Apply colour map for visual clarity
            heatmap = cv2.applyColorMap(gray_diff, cv2.COLORMAP_JET)

            if output_name is None:
                import uuid
                output_name = f"diff_{uuid.uuid4().hex[:8]}"

            dest = DEBUG_DIR / f"{output_name}.png"
            DEBUG_DIR.mkdir(parents=True, exist_ok=True)
            success = save_image(heatmap, dest)
            if success:
                return str(dest)
            return None
        except Exception as exc:
            logger.error("Failed to generate diff heatmap: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Aggregate comparison (sync helper)
    # ------------------------------------------------------------------

    def _full_comparison_sync(
        self, scan_img: np.ndarray, ref_img: np.ndarray, heatmap_name: Optional[str] = None
    ) -> ComparisonResult:
        """Run all comparisons synchronously (called via ``to_thread``)."""
        ssim = self.compare_ssim(scan_img, ref_img)
        hist = self.compare_histogram(scan_img, ref_img)
        orb_count, orb_pct = self.compare_orb_features(scan_img, ref_img)
        heatmap_path = self.generate_diff_heatmap(scan_img, ref_img, output_name=heatmap_name)

        # Weighted overall similarity
        overall = 0.40 * max(ssim, 0) + 0.30 * max(hist, 0) + 0.30 * orb_pct

        return ComparisonResult(
            ssim_score=ssim,
            histogram_score=hist,
            orb_match_count=orb_count,
            orb_match_pct=orb_pct,
            diff_heatmap_path=heatmap_path,
            overall_similarity=overall,
        )

    # ------------------------------------------------------------------
    # Async public interface
    # ------------------------------------------------------------------

    async def full_comparison(
        self,
        scan_path: str | Path,
        reference_path: str | Path,
        heatmap_name: Optional[str] = None,
    ) -> Optional[ComparisonResult]:
        """Run all comparison methods on the two image files.

        Heavy OpenCV work is offloaded to a thread so the event loop is
        never blocked.

        Returns a :class:`ComparisonResult` or ``None`` if images cannot
        be loaded.
        """
        scan_img = load_image(scan_path)
        ref_img = load_image(reference_path)

        if scan_img is None or ref_img is None:
            logger.error(
                "full_comparison: failed to load images (scan=%s, ref=%s)",
                scan_path,
                reference_path,
            )
            return None

        return await asyncio.to_thread(
            self._full_comparison_sync, scan_img, ref_img, heatmap_name
        )
