"""Authenticity check rule definitions and thresholds.

Defines the set of checks to run, their thresholds, and weights for
the weighted confidence calculation. Rules can be adjusted per card type.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class AuthenticityRule:
    """Definition of a single authenticity check rule."""
    name: str
    check_type: str  # "text", "layout", "color", "pattern"
    threshold: float  # Minimum confidence to pass
    weight: float  # Weight in overall confidence calculation
    required: bool  # If True, failure of this check is always significant
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "check_type": self.check_type,
            "threshold": self.threshold,
            "weight": self.weight,
            "required": self.required,
            "description": self.description,
        }


# ============================================================================
# Default rules for standard trading card authenticity checks
# ============================================================================

DEFAULT_RULES: List[AuthenticityRule] = [
    # --- Text Checks ---
    AuthenticityRule(
        name="card_name_match",
        check_type="text",
        threshold=0.80,
        weight=1.0,
        required=False,
        description="Compare OCR card name against reference using Levenshtein similarity",
    ),
    AuthenticityRule(
        name="hp_match",
        check_type="text",
        threshold=0.90,
        weight=0.8,
        required=False,
        description="Verify HP value matches reference (exact numeric match)",
    ),
    AuthenticityRule(
        name="collector_number_match",
        check_type="text",
        threshold=0.90,
        weight=0.8,
        required=False,
        description="Verify collector number format and value match reference",
    ),
    AuthenticityRule(
        name="text_anomalies",
        check_type="text",
        threshold=0.70,
        weight=1.0,
        required=True,
        description="Detect unusual fonts, character artifacts, or suspicious text patterns",
    ),

    # --- Layout Checks ---
    AuthenticityRule(
        name="dimensions",
        check_type="layout",
        threshold=0.75,
        weight=1.2,
        required=True,
        description="Verify card dimensions against 63x88mm standard (tolerance +/-1mm)",
    ),
    AuthenticityRule(
        name="border_proportions",
        check_type="layout",
        threshold=0.70,
        weight=0.9,
        required=False,
        description="Verify border symmetry and expected proportions",
    ),
    AuthenticityRule(
        name="element_positioning",
        check_type="layout",
        threshold=0.65,
        weight=0.7,
        required=False,
        description="Verify key elements are in expected positions on the card",
    ),

    # --- Color Checks ---
    AuthenticityRule(
        name="histogram_comparison",
        check_type="color",
        threshold=0.70,
        weight=1.0,
        required=False,
        description="Compare color histogram correlation against reference image",
    ),
    AuthenticityRule(
        name="color_consistency",
        check_type="color",
        threshold=0.75,
        weight=1.0,
        required=True,
        description="Detect inconsistent color regions indicating print artifacts",
    ),
    AuthenticityRule(
        name="brightness_uniformity",
        check_type="color",
        threshold=0.80,
        weight=0.8,
        required=False,
        description="Detect unusual brightness variations (banding, uneven toner)",
    ),
    AuthenticityRule(
        name="dominant_colors",
        check_type="color",
        threshold=0.65,
        weight=0.7,
        required=False,
        description="Compare top-N dominant colors against reference image",
    ),

    # --- Pattern Checks ---
    AuthenticityRule(
        name="print_pattern",
        check_type="pattern",
        threshold=0.60,
        weight=1.2,
        required=True,
        description="FFT analysis of halftone rosette pattern from offset printing",
    ),
    AuthenticityRule(
        name="inkjet_artifacts",
        check_type="pattern",
        threshold=0.70,
        weight=1.1,
        required=True,
        description="Detect inkjet-specific banding and dot patterns",
    ),
    AuthenticityRule(
        name="surface_texture",
        check_type="pattern",
        threshold=0.65,
        weight=0.8,
        required=False,
        description="Texture analysis for card stock consistency",
    ),
]

# ============================================================================
# Card-type-specific overrides
# ============================================================================

# Threshold adjustments per card type (merged onto defaults)
CARD_TYPE_OVERRIDES: Dict[str, Dict[str, float]] = {
    "holo": {
        # Holographic cards have more color variation, relax color thresholds
        "histogram_comparison": 0.55,
        "dominant_colors": 0.50,
        "brightness_uniformity": 0.65,
        "color_consistency": 0.65,
    },
    "full_art": {
        # Full art cards have unusual layouts, relax positioning
        "element_positioning": 0.50,
        "border_proportions": 0.55,
    },
    "secret_rare": {
        # Secret rares often have non-standard visual features
        "histogram_comparison": 0.50,
        "dominant_colors": 0.45,
        "element_positioning": 0.50,
    },
}


def get_rules(card_type: Optional[str] = None) -> List[AuthenticityRule]:
    """Get authenticity rules, optionally adjusted for a specific card type.

    Args:
        card_type: Optional card type string (e.g., 'holo', 'full_art').
                   If provided and overrides exist, thresholds are adjusted.

    Returns:
        List of AuthenticityRule instances.
    """
    rules = [
        AuthenticityRule(
            name=r.name,
            check_type=r.check_type,
            threshold=r.threshold,
            weight=r.weight,
            required=r.required,
            description=r.description,
        )
        for r in DEFAULT_RULES
    ]

    if card_type and card_type.lower() in CARD_TYPE_OVERRIDES:
        overrides = CARD_TYPE_OVERRIDES[card_type.lower()]
        for rule in rules:
            if rule.name in overrides:
                rule.threshold = overrides[rule.name]

    return rules


def get_rule_by_name(name: str, card_type: Optional[str] = None) -> Optional[AuthenticityRule]:
    """Get a specific rule by name.

    Args:
        name: Rule name to look up.
        card_type: Optional card type for threshold overrides.

    Returns:
        The matching AuthenticityRule or None.
    """
    for rule in get_rules(card_type):
        if rule.name == name:
            return rule
    return None
