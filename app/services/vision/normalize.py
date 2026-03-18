"""Image normalization: rotation, scaling, cropping."""

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
        """Normalize the card image: ensure portrait orientation, scale to standard size."""
        h, w = image.shape[:2]

        # Ensure portrait orientation (height > width)
        if w > h:
            image = cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
            h, w = image.shape[:2]

        # Scale to target dimensions
        if w != self.target_width or h != self.target_height:
            image = cv2.resize(image, (self.target_width, self.target_height), interpolation=cv2.INTER_LANCZOS4)

        return image
