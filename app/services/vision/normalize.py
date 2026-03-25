"""Image normalization: rotation, scaling, cropping, and fine deskew."""

import logging
import cv2
import numpy as np

logger = logging.getLogger(__name__)

CARD_RATIO = 88.0 / 63.0  # height/width for portrait orientation


class ImageNormalizer:
    """Normalize card image orientation and scale."""

    def __init__(self, target_width: int = 750):
        self.target_width = target_width
        self.target_height = int(target_width * CARD_RATIO)

    def normalize(self, image: np.ndarray) -> np.ndarray:
        """Normalize the card image: ensure portrait orientation, deskew, scale to standard size."""
        h, w = image.shape[:2]

        # Ensure portrait orientation (height > width)
        if w > h:
            image = cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
            h, w = image.shape[:2]

        # Fine deskew — correct small residual rotation that persists after
        # perspective correction (e.g. from imprecise contour corners).
        image = self._fine_deskew(image)

        # Scale to target dimensions maintaining standard card aspect ratio
        if w != self.target_width or h != self.target_height:
            image = cv2.resize(
                image,
                (self.target_width, self.target_height),
                interpolation=cv2.INTER_LANCZOS4,
            )

        return image

    def _fine_deskew(self, image: np.ndarray) -> np.ndarray:
        """Correct small rotational skew (up to ~5 degrees).

        Uses Hough line detection on edges to estimate the dominant angle
        of near-horizontal and near-vertical lines (card borders), then
        rotates to make them perfectly axis-aligned.
        """
        h, w = image.shape[:2]
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
        edges = cv2.Canny(gray, 50, 150, apertureSize=3)

        lines = cv2.HoughLinesP(
            edges,
            rho=1,
            theta=np.pi / 720,  # 0.25-degree precision
            threshold=min(w, h) // 4,
            minLineLength=min(w, h) // 3,
            maxLineGap=10,
        )

        if lines is None or len(lines) == 0:
            return image

        # Collect angles of near-horizontal lines (within ~10 degrees of 0)
        angles = []
        for line in lines:
            x1, y1, x2, y2 = line[0]
            dx = x2 - x1
            dy = y2 - y1
            angle = np.degrees(np.arctan2(dy, dx))
            # Near-horizontal: angle close to 0 or 180
            if abs(angle) < 10:
                angles.append(angle)
            elif abs(angle - 180) < 10:
                angles.append(angle - 180)
            elif abs(angle + 180) < 10:
                angles.append(angle + 180)
            # Near-vertical: angle close to 90 or -90 (convert to horizontal offset)
            elif abs(abs(angle) - 90) < 10:
                vert_offset = angle - 90 if angle > 0 else angle + 90
                angles.append(vert_offset)

        if not angles:
            return image

        # Use the median angle to be robust against outlier lines
        median_angle = float(np.median(angles))

        # Only correct small skew (< 5 degrees) — anything larger is likely
        # a misdetection or the perspective correction already handled it
        if abs(median_angle) < 0.1 or abs(median_angle) > 5.0:
            return image

        # Rotate around image centre
        center = (w / 2, h / 2)
        rot_matrix = cv2.getRotationMatrix2D(center, median_angle, 1.0)
        deskewed = cv2.warpAffine(
            image, rot_matrix, (w, h),
            flags=cv2.INTER_LANCZOS4,
            borderMode=cv2.BORDER_REPLICATE,
        )

        logger.info("Fine deskew: corrected %.2f° rotation", median_angle)
        return deskewed
