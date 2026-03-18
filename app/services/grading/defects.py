"""Defect classification and hard-cap logic for card grading."""

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


# Hard caps: certain defects impose an absolute maximum grade.
# If any of these defects are found, the final grade cannot exceed the cap.
HARD_CAPS: dict[str, float] = {
    "crease": 4.0,
    "tear": 2.0,
    "water_damage": 3.0,
    "bend": 5.0,
    "heavy_scratch": 6.0,
    "hole": 1.0,
    "missing_piece": 1.0,
    "heavy_stain": 4.0,
    "delamination": 3.0,
}


# Severity levels with their general score multipliers
SEVERITY_LEVELS: dict[str, dict] = {
    "minor": {
        "label": "Minor",
        "description": "Small impact, barely noticeable without close inspection",
        "score_multiplier": 0.25,
    },
    "moderate": {
        "label": "Moderate",
        "description": "Noticeable upon examination, affects presentation",
        "score_multiplier": 0.50,
    },
    "major": {
        "label": "Major",
        "description": "Significant defect, clearly visible",
        "score_multiplier": 0.75,
    },
    "severe": {
        "label": "Severe",
        "description": "Dominates the card's condition, major grade impact",
        "score_multiplier": 1.00,
    },
}


@dataclass
class ClassifiedDefect:
    """A defect that has been classified with severity and optional hard cap."""
    category: str              # centering, corner, edge, surface
    defect_type: str           # whitening, scratch, chip, etc.
    severity: str              # minor, moderate, major, severe
    location: str              # e.g., "top_left corner", "right edge"
    score_impact: float        # grade point reduction
    hard_cap: Optional[float] = None  # maximum grade if this defect is present
    bbox_x: int = 0
    bbox_y: int = 0
    bbox_w: int = 0
    bbox_h: int = 0
    confidence: float = 0.0
    is_noise: bool = False
    is_manufacturing: bool = False  # manufacturing defect (reduced penalty)
    details: dict = field(default_factory=dict)


class DefectClassifier:
    """Classify detected defects and determine hard caps.

    Takes raw defect detections from the individual analyzers,
    normalises severity, determines if any hard caps apply,
    and filters out noise.
    """

    def __init__(self, noise_threshold_px: int = 3):
        """Initialize defect classifier.

        Args:
            noise_threshold_px: Minimum bounding box dimension in pixels
                for a defect to be considered real (not noise).
        """
        self.noise_threshold_px = noise_threshold_px

    def classify_defect(
        self,
        defect_type: str,
        area: float,
        intensity: float,
    ) -> str:
        """Classify a defect's severity based on area and intensity.

        Args:
            defect_type: Type of defect (e.g., "scratch", "whitening").
            area: Relative area of the defect (0.0 to 1.0).
            intensity: How pronounced the defect is (0.0 to 1.0).

        Returns:
            Severity string: "minor", "moderate", "major", or "severe".
        """
        combined = (area + intensity) / 2.0

        if combined > 0.70:
            return "severe"
        elif combined > 0.40:
            return "major"
        elif combined > 0.15:
            return "moderate"
        else:
            return "minor"

    def apply_noise_threshold(
        self,
        defects: list[ClassifiedDefect],
        threshold: Optional[int] = None,
    ) -> list[ClassifiedDefect]:
        """Filter out defects that are likely noise.

        Defects with bounding boxes smaller than the threshold in both
        dimensions are marked as noise and excluded from scoring.

        Args:
            defects: List of classified defects.
            threshold: Minimum pixel dimension. Uses instance default if None.

        Returns:
            Filtered list with noise defects marked.
        """
        threshold = threshold if threshold is not None else self.noise_threshold_px
        result = []

        for defect in defects:
            if defect.bbox_w > 0 and defect.bbox_h > 0:
                if defect.bbox_w < threshold and defect.bbox_h < threshold:
                    defect.is_noise = True
                    logger.debug(
                        "Filtered noise defect: %s at (%d,%d) size %dx%d",
                        defect.defect_type, defect.bbox_x, defect.bbox_y,
                        defect.bbox_w, defect.bbox_h,
                    )
            result.append(defect)

        return result

    def get_cap_for_defects(
        self, defects: list[ClassifiedDefect],
    ) -> Optional[float]:
        """Get the minimum hard cap imposed by all defects.

        Args:
            defects: List of classified defects (noise already filtered).

        Returns:
            The minimum cap value, or None if no hard caps apply.
        """
        caps: list[float] = []

        for defect in defects:
            if defect.is_noise:
                continue
            if defect.hard_cap is not None:
                caps.append(defect.hard_cap)

        if not caps:
            return None

        min_cap = min(caps)
        logger.debug("Hard cap determined: %.1f from %d capping defects", min_cap, len(caps))
        return min_cap

    def classify_from_corner(
        self, corner_defect, corner_offset_x: int = 0, corner_offset_y: int = 0,
    ) -> ClassifiedDefect:
        """Convert a CornerDefect to a ClassifiedDefect.

        Args:
            corner_defect: CornerDefect instance from CornerAnalyzer.
            corner_offset_x: X offset of the corner region in the full image.
            corner_offset_y: Y offset of the corner region in the full image.

        Returns:
            ClassifiedDefect instance.
        """
        hard_cap = HARD_CAPS.get(corner_defect.defect_type)

        return ClassifiedDefect(
            category="corner",
            defect_type=corner_defect.defect_type,
            severity=corner_defect.severity,
            location=f"{corner_defect.corner} corner",
            score_impact=corner_defect.score_impact,
            hard_cap=hard_cap,
            bbox_x=corner_defect.bbox_x + corner_offset_x,
            bbox_y=corner_defect.bbox_y + corner_offset_y,
            bbox_w=corner_defect.bbox_w,
            bbox_h=corner_defect.bbox_h,
            confidence=corner_defect.confidence,
            details=corner_defect.details,
        )

    def classify_from_edge(
        self, edge_defect, edge_offset_x: int = 0, edge_offset_y: int = 0,
    ) -> ClassifiedDefect:
        """Convert an EdgeDefect to a ClassifiedDefect.

        Args:
            edge_defect: EdgeDefect instance from EdgeAnalyzer.
            edge_offset_x: X offset of the edge region in the full image.
            edge_offset_y: Y offset of the edge region in the full image.

        Returns:
            ClassifiedDefect instance.
        """
        hard_cap = HARD_CAPS.get(edge_defect.defect_type)

        return ClassifiedDefect(
            category="edge",
            defect_type=edge_defect.defect_type,
            severity=edge_defect.severity,
            location=f"{edge_defect.edge} edge",
            score_impact=edge_defect.score_impact,
            hard_cap=hard_cap,
            bbox_x=edge_defect.bbox_x + edge_offset_x,
            bbox_y=edge_defect.bbox_y + edge_offset_y,
            bbox_w=edge_defect.bbox_w,
            bbox_h=edge_defect.bbox_h,
            confidence=edge_defect.confidence,
            details=edge_defect.details,
        )

    def classify_from_surface(
        self, surface_defect, surface_offset_x: int = 0, surface_offset_y: int = 0,
    ) -> ClassifiedDefect:
        """Convert a SurfaceDefect to a ClassifiedDefect.

        Args:
            surface_defect: SurfaceDefect instance from SurfaceAnalyzer.
            surface_offset_x: X offset of the surface region in the full image.
            surface_offset_y: Y offset of the surface region in the full image.

        Returns:
            ClassifiedDefect instance.
        """
        # Map surface defect types to hard cap types
        cap_type_map = {
            "scratch": None,
            "dent": None,
            "stain": None,
            "print_line": None,
            "silvering": None,
        }

        # Severe scratches become "heavy_scratch" for cap purposes
        defect_type = surface_defect.defect_type
        hard_cap = None
        if defect_type == "scratch" and surface_defect.severity == "severe":
            hard_cap = HARD_CAPS.get("heavy_scratch")
        elif defect_type == "stain" and surface_defect.severity == "severe":
            hard_cap = HARD_CAPS.get("heavy_stain")
        else:
            hard_cap = HARD_CAPS.get(defect_type)

        # Manufacturing defects: print lines and silvering are factory-origin
        is_mfg = defect_type in ("print_line", "silvering")

        return ClassifiedDefect(
            category="surface",
            defect_type=defect_type,
            severity=surface_defect.severity,
            location="surface",
            score_impact=surface_defect.score_impact,
            hard_cap=hard_cap,
            bbox_x=surface_defect.bbox_x + surface_offset_x,
            bbox_y=surface_defect.bbox_y + surface_offset_y,
            bbox_w=surface_defect.bbox_w,
            bbox_h=surface_defect.bbox_h,
            confidence=surface_defect.confidence,
            is_manufacturing=is_mfg,
            details=surface_defect.details,
        )
