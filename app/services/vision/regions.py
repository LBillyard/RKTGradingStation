"""Region extraction for card analysis zones."""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class CardRegions:
    """Extracted card analysis regions."""
    # Corners (15% inset from each corner)
    corner_tl: Optional[np.ndarray] = None
    corner_tr: Optional[np.ndarray] = None
    corner_br: Optional[np.ndarray] = None
    corner_bl: Optional[np.ndarray] = None
    # Edges (strips along each side, excluding corners)
    edge_top: Optional[np.ndarray] = None
    edge_bottom: Optional[np.ndarray] = None
    edge_left: Optional[np.ndarray] = None
    edge_right: Optional[np.ndarray] = None
    # Surface (central area)
    surface: Optional[np.ndarray] = None
    # Full card for reference
    full: Optional[np.ndarray] = None

    def save_all(self, output_dir: Path) -> None:
        """Save all regions as images for debugging."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        for name in ['corner_tl', 'corner_tr', 'corner_br', 'corner_bl',
                      'edge_top', 'edge_bottom', 'edge_left', 'edge_right', 'surface']:
            region = getattr(self, name)
            if region is not None:
                cv2.imwrite(str(output_dir / f"{name}.png"), region)


class RegionExtractor:
    """Extract analysis zones from a processed card image."""

    def __init__(self, corner_pct: float = 0.15, edge_width_pct: float = 0.08):
        self.corner_pct = corner_pct
        self.edge_width_pct = edge_width_pct

    def extract(self, image: np.ndarray) -> CardRegions:
        """Extract all analysis regions from the card image."""
        h, w = image.shape[:2]
        corner_h = int(h * self.corner_pct)
        corner_w = int(w * self.corner_pct)
        edge_w = int(w * self.edge_width_pct)
        edge_h = int(h * self.edge_width_pct)

        regions = CardRegions(full=image)

        # Corners
        regions.corner_tl = image[0:corner_h, 0:corner_w]
        regions.corner_tr = image[0:corner_h, w-corner_w:w]
        regions.corner_br = image[h-corner_h:h, w-corner_w:w]
        regions.corner_bl = image[h-corner_h:h, 0:corner_w]

        # Edges (excluding corner zones)
        regions.edge_top = image[0:edge_h, corner_w:w-corner_w]
        regions.edge_bottom = image[h-edge_h:h, corner_w:w-corner_w]
        regions.edge_left = image[corner_h:h-corner_h, 0:edge_w]
        regions.edge_right = image[corner_h:h-corner_h, w-edge_w:w]

        # Surface (central area excluding borders)
        border = int(min(h, w) * 0.12)
        regions.surface = image[border:h-border, border:w-border]

        logger.debug(f"Extracted regions: corners={corner_w}x{corner_h}, edges={edge_w}/{edge_h}, surface={regions.surface.shape}")
        return regions
