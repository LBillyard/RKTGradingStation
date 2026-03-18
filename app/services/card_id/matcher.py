"""Template and visual matching utilities for card identification."""

import logging
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)


class VisualMatcher:
    """Compare card images against reference library for visual matching."""

    def compare_ssim(self, image1: np.ndarray, image2: np.ndarray) -> float:
        """Compute structural similarity index between two images."""
        # Resize both to same dimensions
        h, w = 400, 300
        img1 = cv2.resize(image1, (w, h))
        img2 = cv2.resize(image2, (w, h))

        gray1 = cv2.cvtColor(img1, cv2.COLOR_BGR2GRAY)
        gray2 = cv2.cvtColor(img2, cv2.COLOR_BGR2GRAY)

        # Compute SSIM using OpenCV
        c1 = (0.01 * 255) ** 2
        c2 = (0.03 * 255) ** 2

        mu1 = cv2.GaussianBlur(gray1.astype(np.float64), (11, 11), 1.5)
        mu2 = cv2.GaussianBlur(gray2.astype(np.float64), (11, 11), 1.5)

        mu1_sq = mu1 ** 2
        mu2_sq = mu2 ** 2
        mu1_mu2 = mu1 * mu2

        sigma1_sq = cv2.GaussianBlur(gray1.astype(np.float64) ** 2, (11, 11), 1.5) - mu1_sq
        sigma2_sq = cv2.GaussianBlur(gray2.astype(np.float64) ** 2, (11, 11), 1.5) - mu2_sq
        sigma12 = cv2.GaussianBlur(gray1.astype(np.float64) * gray2.astype(np.float64), (11, 11), 1.5) - mu1_mu2

        ssim_map = ((2 * mu1_mu2 + c1) * (2 * sigma12 + c2)) / ((mu1_sq + mu2_sq + c1) * (sigma1_sq + sigma2_sq + c2))
        return float(np.mean(ssim_map))

    def compare_histogram(self, image1: np.ndarray, image2: np.ndarray) -> float:
        """Compare color histograms of two images."""
        h, w = 200, 150
        img1 = cv2.resize(image1, (w, h))
        img2 = cv2.resize(image2, (w, h))

        hist1 = cv2.calcHist([img1], [0, 1, 2], None, [8, 8, 8], [0, 256, 0, 256, 0, 256])
        hist2 = cv2.calcHist([img2], [0, 1, 2], None, [8, 8, 8], [0, 256, 0, 256, 0, 256])

        cv2.normalize(hist1, hist1)
        cv2.normalize(hist2, hist2)

        return float(cv2.compareHist(hist1, hist2, cv2.HISTCMP_CORREL))
