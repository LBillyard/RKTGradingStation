"""Card contour detection."""

import logging
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)


class ContourDetector:
    """Detect the card boundary in a scanner image."""

    def __init__(self, min_area_ratio: float = 0.03, blur_kernel: int = 5):
        self.min_area_ratio = min_area_ratio
        self.blur_kernel = blur_kernel

    def detect(self, image: np.ndarray) -> Optional[np.ndarray]:
        """Detect card contour and return 4 corner points, or None if not found.

        Returns corners in order: top-left, top-right, bottom-right, bottom-left.
        """
        h, w = image.shape[:2]
        min_area = h * w * self.min_area_ratio

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (self.blur_kernel, self.blur_kernel), 0)

        # Try multiple threshold approaches
        corners = self._try_canny(blurred, min_area)
        if corners is not None:
            return self._order_corners(corners)

        corners = self._try_adaptive_threshold(blurred, min_area)
        if corners is not None:
            return self._order_corners(corners)

        corners = self._try_otsu(blurred, min_area)
        if corners is not None:
            return self._order_corners(corners)

        return None

    def _try_canny(self, gray: np.ndarray, min_area: float) -> Optional[np.ndarray]:
        edges = cv2.Canny(gray, 30, 150)
        edges = cv2.dilate(edges, None, iterations=1)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        return self._find_card_contour(contours, min_area)

    def _try_adaptive_threshold(self, gray: np.ndarray, min_area: float) -> Optional[np.ndarray]:
        thresh = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 11, 2)
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        return self._find_card_contour(contours, min_area)

    def _try_otsu(self, gray: np.ndarray, min_area: float) -> Optional[np.ndarray]:
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        return self._find_card_contour(contours, min_area)

    def _find_card_contour(self, contours, min_area: float) -> Optional[np.ndarray]:
        for cnt in sorted(contours, key=cv2.contourArea, reverse=True):
            area = cv2.contourArea(cnt)
            if area < min_area:
                continue
            peri = cv2.arcLength(cnt, True)
            approx = cv2.approxPolyDP(cnt, 0.02 * peri, True)
            if len(approx) == 4:
                return approx.reshape(4, 2).astype(np.float32)
        return None

    def _order_corners(self, pts: np.ndarray) -> np.ndarray:
        """Order points as: top-left, top-right, bottom-right, bottom-left."""
        rect = np.zeros((4, 2), dtype=np.float32)
        s = pts.sum(axis=1)
        rect[0] = pts[np.argmin(s)]   # top-left has smallest sum
        rect[2] = pts[np.argmax(s)]   # bottom-right has largest sum
        d = np.diff(pts, axis=1)
        rect[1] = pts[np.argmin(d)]   # top-right has smallest difference
        rect[3] = pts[np.argmax(d)]   # bottom-left has largest difference
        return rect

    def detect_all(self, image: np.ndarray, max_cards: int = 8) -> list[np.ndarray]:
        """Detect ALL card contours in the image.

        Returns a list of 4-corner arrays, sorted by reading order (top-to-bottom, left-to-right).
        """
        h, w = image.shape[:2]
        # Lower min area since each card is smaller relative to the full bed
        min_area = h * w * 0.02

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (self.blur_kernel, self.blur_kernel), 0)

        all_corners = []

        # Try each threshold method and collect all card-like quadrilaterals
        for method in [self._try_canny, self._try_adaptive_threshold, self._try_otsu]:
            try:
                if method == self._try_canny:
                    edges = cv2.Canny(blurred, 30, 150)
                    edges = cv2.dilate(edges, None, iterations=1)
                    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                elif method == self._try_adaptive_threshold:
                    thresh = cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 11, 2)
                    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                else:
                    _, thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
                    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

                for cnt in contours:
                    area = cv2.contourArea(cnt)
                    if area < min_area:
                        continue
                    peri = cv2.arcLength(cnt, True)
                    approx = cv2.approxPolyDP(cnt, 0.02 * peri, True)
                    if len(approx) == 4:
                        corners = approx.reshape(4, 2).astype(np.float32)
                        ordered = self._order_corners(corners)

                        # Check card aspect ratio (2.5 x 3.5 = 0.714, tolerance ± 0.25)
                        card_w = np.linalg.norm(ordered[1] - ordered[0])
                        card_h = np.linalg.norm(ordered[3] - ordered[0])
                        if card_h == 0:
                            continue
                        ratio = min(card_w, card_h) / max(card_w, card_h)
                        if 0.45 < ratio < 0.95:
                            all_corners.append(ordered)
            except Exception as e:
                logger.warning("detect_all method failed: %s", e)

        if not all_corners:
            return []

        # Remove duplicates by IoU > 0.5
        unique = self._remove_duplicate_contours(all_corners)

        # Sort by reading order: top-to-bottom, then left-to-right
        unique.sort(key=lambda c: (c[0][1], c[0][0]))

        return unique[:max_cards]

    def _remove_duplicate_contours(self, contours: list[np.ndarray]) -> list[np.ndarray]:
        """Remove duplicate contours by comparing bounding box IoU."""
        if not contours:
            return []

        def bbox(corners):
            x_min, y_min = corners.min(axis=0)
            x_max, y_max = corners.max(axis=0)
            return x_min, y_min, x_max, y_max

        def iou(b1, b2):
            x1 = max(b1[0], b2[0])
            y1 = max(b1[1], b2[1])
            x2 = min(b1[2], b2[2])
            y2 = min(b1[3], b2[3])
            inter = max(0, x2 - x1) * max(0, y2 - y1)
            area1 = (b1[2] - b1[0]) * (b1[3] - b1[1])
            area2 = (b2[2] - b2[0]) * (b2[3] - b2[1])
            union = area1 + area2 - inter
            return inter / union if union > 0 else 0

        keep = []
        for c in contours:
            b = bbox(c)
            duplicate = False
            for existing in keep:
                if iou(b, bbox(existing)) > 0.5:
                    duplicate = True
                    break
            if not duplicate:
                keep.append(c)

        return keep

    def draw_contour(self, image: np.ndarray, corners: np.ndarray) -> np.ndarray:
        """Draw detected contour on image for debugging."""
        debug = image.copy()
        pts = corners.astype(np.int32)
        cv2.polylines(debug, [pts], True, (0, 255, 0), 3)
        for i, pt in enumerate(pts):
            cv2.circle(debug, tuple(pt), 8, (0, 0, 255), -1)
            cv2.putText(debug, str(i), tuple(pt + [10, -10]), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
        return debug
