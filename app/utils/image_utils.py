"""Image utility functions for the RKT Grading Station."""

import logging
from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)


def load_image(path: str | Path) -> Optional[np.ndarray]:
    """Load an image from disk as a BGR numpy array."""
    path = str(path)
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        logger.error(f"Failed to load image: {path}")
    return img


def save_image(image: np.ndarray, path: str | Path) -> bool:
    """Save a BGR numpy array to disk."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    success = cv2.imwrite(str(path), image)
    if not success:
        logger.error(f"Failed to save image: {path}")
    return success


def pil_to_cv2(pil_image: Image.Image) -> np.ndarray:
    """Convert a PIL Image to OpenCV BGR numpy array."""
    rgb = np.array(pil_image)
    if len(rgb.shape) == 2:
        return cv2.cvtColor(rgb, cv2.COLOR_GRAY2BGR)
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def cv2_to_pil(cv2_image: np.ndarray) -> Image.Image:
    """Convert an OpenCV BGR numpy array to PIL Image."""
    rgb = cv2.cvtColor(cv2_image, cv2.COLOR_BGR2RGB)
    return Image.fromarray(rgb)


def resize_to_max(image: np.ndarray, max_dimension: int = 2000) -> np.ndarray:
    """Resize image so its largest dimension is at most max_dimension."""
    h, w = image.shape[:2]
    if max(h, w) <= max_dimension:
        return image
    scale = max_dimension / max(h, w)
    new_w = int(w * scale)
    new_h = int(h * scale)
    return cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)


def create_thumbnail(image: np.ndarray, size: Tuple[int, int] = (300, 420)) -> np.ndarray:
    """Create a thumbnail of the card image."""
    return cv2.resize(image, size, interpolation=cv2.INTER_AREA)


def get_image_dimensions(path: str | Path) -> Optional[Tuple[int, int]]:
    """Get image dimensions (width, height) without loading fully."""
    try:
        with Image.open(str(path)) as img:
            return img.size
    except Exception as e:
        logger.error(f"Failed to get dimensions for {path}: {e}")
        return None
