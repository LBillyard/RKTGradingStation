"""Image processing pipeline orchestrator."""

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from app.config import settings
from .contour import ContourDetector
from .perspective import PerspectiveCorrector
from .normalize import ImageNormalizer
from .background import BackgroundRemover
from .border import BorderMeasurer, BorderMeasurement
from .regions import RegionExtractor, CardRegions
from .orientation import OrientationCorrector

logger = logging.getLogger(__name__)


@dataclass
class ProcessedCard:
    corrected_image: np.ndarray
    regions: Optional[CardRegions] = None
    borders: Optional[BorderMeasurement] = None
    contour_found: bool = False
    perspective_corrected: bool = False
    orientation_rotated: bool = False
    debug_dir: Optional[str] = None
    processing_time_ms: int = 0
    errors: List[str] = field(default_factory=list)


class VisionPipeline:
    """Processes raw card scans through detection, correction, and analysis steps."""

    def __init__(self, debug_dir: Path = None):
        self.debug_dir = Path(debug_dir) if debug_dir else Path("data/debug")
        self.contour_detector = ContourDetector()
        self.perspective_corrector = PerspectiveCorrector()
        self.normalizer = ImageNormalizer()
        self.background_remover = BackgroundRemover()
        self.border_measurer = BorderMeasurer()
        self.region_extractor = RegionExtractor()
        self.orientation_corrector = OrientationCorrector()

    def process(self, image: np.ndarray, scan_id: str, side: str = "front") -> ProcessedCard:
        """Run the full image processing pipeline."""
        start = time.perf_counter()
        _debug = settings.debug
        if _debug:
            debug_subdir = self.debug_dir / scan_id / side
            debug_subdir.mkdir(parents=True, exist_ok=True)
        else:
            debug_subdir = None

        result = ProcessedCard(corrected_image=image)
        current = image.copy()

        # Save original (debug only)
        if _debug:
            cv2.imwrite(str(debug_subdir / "00_original.png"), current)

        # Step 1: Detect card contour
        try:
            corners = self.contour_detector.detect(current)
            if corners is not None:
                result.contour_found = True
                if _debug:
                    debug_img = self.contour_detector.draw_contour(current, corners)
                    cv2.imwrite(str(debug_subdir / "01_contour.png"), debug_img)
                logger.info(f"[{scan_id}/{side}] Contour detected with 4 corners")
            else:
                result.errors.append("No card contour detected")
                logger.warning(f"[{scan_id}/{side}] No card contour found, using full image")
        except Exception as e:
            result.errors.append(f"Contour detection failed: {e}")
            corners = None

        # Step 2: Perspective correction
        if corners is not None:
            try:
                current = self.perspective_corrector.correct(current, corners)
                result.perspective_corrected = True
                if _debug:
                    cv2.imwrite(str(debug_subdir / "02_perspective.png"), current)
            except Exception as e:
                result.errors.append(f"Perspective correction failed: {e}")

        # Step 3: Normalize (rotate, scale, crop)
        try:
            current = self.normalizer.normalize(current)
            if _debug:
                cv2.imwrite(str(debug_subdir / "03_normalized.png"), current)
        except Exception as e:
            result.errors.append(f"Normalization failed: {e}")

        # Step 3b: Orientation correction — ensure card is right-way-up
        if result.perspective_corrected:
            try:
                current, was_rotated = self.orientation_corrector.correct(current)
                result.orientation_rotated = was_rotated
                if _debug:
                    cv2.imwrite(str(debug_subdir / "03b_orientation.png"), current)
                if was_rotated:
                    logger.info(f"[{scan_id}/{side}] Card was upside-down, rotated 180°")
            except Exception as e:
                result.errors.append(f"Orientation correction failed: {e}")

        # Step 4: Background removal — only when contour was NOT found.
        # When perspective correction succeeded the card is already isolated
        # with a small margin; background removal would crop the card borders.
        if result.perspective_corrected:
            cleaned = current
            logger.info(f"[{scan_id}/{side}] Skipping background removal (perspective-corrected)")
        else:
            try:
                cleaned = self.background_remover.remove(current)
                if _debug:
                    cv2.imwrite(str(debug_subdir / "04_bg_removed.png"), cleaned)
            except Exception as e:
                result.errors.append(f"Background removal failed: {e}")
                cleaned = current

        # Step 5: Border measurement
        try:
            borders = self.border_measurer.measure(cleaned)
            result.borders = borders
            if _debug:
                border_debug = self.border_measurer.draw_borders(cleaned, borders)
                cv2.imwrite(str(debug_subdir / "05_borders.png"), border_debug)
        except Exception as e:
            result.errors.append(f"Border measurement failed: {e}")

        # Step 6: Region extraction
        try:
            regions = self.region_extractor.extract(cleaned)
            result.regions = regions
            if _debug:
                regions.save_all(debug_subdir / "regions")
        except Exception as e:
            result.errors.append(f"Region extraction failed: {e}")

        result.corrected_image = cleaned
        result.debug_dir = str(debug_subdir) if _debug else None
        result.processing_time_ms = int((time.perf_counter() - start) * 1000)

        logger.info(f"[{scan_id}/{side}] Pipeline complete in {result.processing_time_ms}ms, {len(result.errors)} errors")
        return result

    def process_multi(self, image: np.ndarray, scan_id: str, side: str = "front") -> list[ProcessedCard]:
        """Detect multiple cards and process each individually.

        Falls back to single-card process() if no cards are detected.
        """
        start = time.perf_counter()

        # Detect all card contours
        all_corners = self.contour_detector.detect_all(image)

        if not all_corners:
            logger.info("[%s/%s] No individual cards detected, falling back to single-card", scan_id, side)
            return [self.process(image, scan_id, side)]

        logger.info("[%s/%s] Detected %d cards", scan_id, side, len(all_corners))

        _debug = settings.debug
        results = []
        for i, corners in enumerate(all_corners):
            card_id = f"{scan_id}_card{i}"
            if _debug:
                debug_subdir = self.debug_dir / card_id / side
                debug_subdir.mkdir(parents=True, exist_ok=True)
            else:
                debug_subdir = None

            result = ProcessedCard(corrected_image=image)
            result.contour_found = True

            try:
                # Perspective-correct this card
                corrected = self.perspective_corrector.correct(image, corners)
                result.perspective_corrected = True
                if _debug:
                    cv2.imwrite(str(debug_subdir / "02_perspective.png"), corrected)

                # Normalize
                try:
                    corrected = self.normalizer.normalize(corrected)
                    if _debug:
                        cv2.imwrite(str(debug_subdir / "03_normalized.png"), corrected)
                except Exception as e:
                    result.errors.append(f"Normalization failed: {e}")

                # Orientation correction
                if result.perspective_corrected:
                    try:
                        corrected, was_rotated = self.orientation_corrector.correct(corrected)
                        result.orientation_rotated = was_rotated
                        if _debug:
                            cv2.imwrite(str(debug_subdir / "03b_orientation.png"), corrected)
                    except Exception as e:
                        result.errors.append(f"Orientation correction failed: {e}")

                # Background removal — skip for perspective-corrected cards
                # to preserve card borders for centering/corner/edge analysis
                if result.perspective_corrected:
                    cleaned = corrected
                else:
                    try:
                        cleaned = self.background_remover.remove(corrected)
                        if _debug:
                            cv2.imwrite(str(debug_subdir / "04_bg_removed.png"), cleaned)
                    except Exception as e:
                        result.errors.append(f"Background removal failed: {e}")
                        cleaned = corrected

                # Border measurement
                try:
                    borders = self.border_measurer.measure(cleaned)
                    result.borders = borders
                except Exception as e:
                    result.errors.append(f"Border measurement failed: {e}")

                # Region extraction
                try:
                    regions = self.region_extractor.extract(cleaned)
                    result.regions = regions
                    if _debug:
                        regions.save_all(debug_subdir / "regions")
                except Exception as e:
                    result.errors.append(f"Region extraction failed: {e}")

                result.corrected_image = cleaned
                result.debug_dir = str(debug_subdir) if _debug else None
            except Exception as e:
                result.errors.append(f"Card {i} processing failed: {e}")
                logger.error("[%s/%s] Card %d failed: %s", scan_id, side, i, e)

            result.processing_time_ms = int((time.perf_counter() - start) * 1000)
            results.append(result)

        logger.info("[%s/%s] Multi-card pipeline: %d cards in %dms",
                    scan_id, side, len(results),
                    int((time.perf_counter() - start) * 1000))
        return results
