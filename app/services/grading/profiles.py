"""Sensitivity profiles for grading engine."""

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class SensitivityProfile:
    """Sensitivity configuration that controls how aggressively defects are detected."""
    name: str
    label: str
    description: str

    # Corner thresholds
    whitening_threshold: int = 230       # brightness level to count as whitening
    whitening_area_pct: float = 0.05     # min area fraction for whitening defect
    softening_threshold: float = 0.15    # circularity ratio for softening
    deformation_threshold: float = 0.25  # convexity defect depth ratio

    # Edge thresholds
    wear_threshold: float = 0.10         # edge roughness ratio
    chip_min_depth: int = 3              # min pixel depth for a chip
    straightness_tolerance: float = 0.02 # max deviation fraction from straight

    # Surface thresholds
    scratch_hough_threshold: int = 50    # Hough accumulator threshold
    scratch_min_length: int = 30         # min scratch length in pixels
    scratch_max_gap: int = 10            # max gap in scratch line
    dent_threshold: float = 0.15         # Laplacian depth threshold
    stain_threshold: float = 0.08        # LAB colour distance threshold
    print_line_threshold: int = 40       # frequency energy ratio threshold
    silvering_threshold: float = 0.05    # silvering coverage ratio

    # Noise filtering
    noise_threshold_px: int = 3          # min bbox dimension to not be noise


# Pre-defined sensitivity profiles
SENSITIVITY_PROFILES: dict[str, SensitivityProfile] = {
    "lenient": SensitivityProfile(
        name="lenient",
        label="Lenient",
        description="Higher thresholds, fewer detections. Suitable for vintage "
                    "cards or collections where minor wear is expected.",
        # Corners: harder to trigger
        whitening_threshold=240,
        whitening_area_pct=0.10,
        softening_threshold=0.25,
        deformation_threshold=0.35,
        # Edges: harder to trigger
        wear_threshold=0.18,
        chip_min_depth=6,
        straightness_tolerance=0.04,
        # Surface: harder to trigger
        scratch_hough_threshold=70,
        scratch_min_length=50,
        scratch_max_gap=15,
        dent_threshold=0.25,
        stain_threshold=0.15,
        print_line_threshold=60,
        silvering_threshold=0.10,
        # Noise: more aggressive filtering
        noise_threshold_px=5,
    ),

    "standard": SensitivityProfile(
        name="standard",
        label="Standard",
        description="Balanced detection thresholds. Recommended for modern "
                    "cards in typical condition.",
        # Uses all defaults
    ),

    "strict": SensitivityProfile(
        name="strict",
        label="Strict",
        description="Lower thresholds, more sensitive detection. Suitable for "
                    "high-value cards where every minor defect matters.",
        # Corners: easier to trigger
        whitening_threshold=220,
        whitening_area_pct=0.03,
        softening_threshold=0.10,
        deformation_threshold=0.18,
        # Edges: easier to trigger
        wear_threshold=0.06,
        chip_min_depth=2,
        straightness_tolerance=0.01,
        # Surface: easier to trigger
        scratch_hough_threshold=35,
        scratch_min_length=20,
        scratch_max_gap=8,
        dent_threshold=0.10,
        stain_threshold=0.05,
        print_line_threshold=30,
        silvering_threshold=0.03,
        # Noise: less filtering
        noise_threshold_px=2,
    ),
}


def get_profile(name: str) -> SensitivityProfile:
    """Get a sensitivity profile by name.

    Args:
        name: Profile name ("lenient", "standard", or "strict").

    Returns:
        SensitivityProfile instance.

    Raises:
        ValueError: If the profile name is not recognized.
    """
    profile = SENSITIVITY_PROFILES.get(name)
    if profile is None:
        valid = ", ".join(SENSITIVITY_PROFILES.keys())
        raise ValueError(f"Unknown sensitivity profile '{name}'. Valid profiles: {valid}")
    return profile


def list_profiles() -> list[dict]:
    """List all available sensitivity profiles as dicts.

    Returns:
        List of profile summary dicts with name, label, description.
    """
    return [
        {
            "name": p.name,
            "label": p.label,
            "description": p.description,
        }
        for p in SENSITIVITY_PROFILES.values()
    ]
