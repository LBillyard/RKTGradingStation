"""Background removal for scanned card images."""

import logging
import cv2
import numpy as np

logger = logging.getLogger(__name__)


class BackgroundRemover:
    """Remove scanner background from card images."""

    def __init__(self, bg_threshold: int = 240):
        self.bg_threshold = bg_threshold

    def remove(self, image: np.ndarray) -> np.ndarray:
        """Remove scanner background (typically white or black).

        For flatbed scans, the background is usually white (>240) or black (<15).
        This crops to the actual card content area.
        """
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        # Try white background first (most common for flatbed)
        _, mask_white = cv2.threshold(gray, self.bg_threshold, 255, cv2.THRESH_BINARY_INV)
        # Try black background
        _, mask_black = cv2.threshold(gray, 15, 255, cv2.THRESH_BINARY)

        # Use whichever mask has more foreground pixels
        white_fg = cv2.countNonZero(mask_white)
        black_fg = cv2.countNonZero(mask_black)
        mask = mask_white if white_fg > black_fg else mask_black

        # Clean up mask with morphological operations
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)

        # Find bounding rectangle of the card
        coords = cv2.findNonZero(mask)
        if coords is not None:
            x, y, w, h = cv2.boundingRect(coords)
            # Add small padding
            pad = 5
            x = max(0, x - pad)
            y = max(0, y - pad)
            w = min(image.shape[1] - x, w + 2 * pad)
            h = min(image.shape[0] - y, h + 2 * pad)
            cropped = image[y:y+h, x:x+w]
            logger.debug(f"Background removed, cropped to {w}x{h}")
            return cropped

        return image
