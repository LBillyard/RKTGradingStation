"""Grading engine enhancements — grade curve, smart rounding, diminishing returns,
vintage detection, holo intelligence, quick grade, confidence routing, grade
explanations, cross-validation, and known issues.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ============================================================
# Grade Curve Targeting
# ============================================================

@dataclass
class GradeCurveConfig:
    """Configurable grade curve that shifts the distribution."""
    enabled: bool = True
    # Positive = shift grades UP (more 9s/10s), negative = shift down
    curve_offset: float = 0.3
    # Only apply to cards above this raw score (don't inflate truly bad cards)
    min_raw_score: float = 6.0
    # Maximum offset (tapers near 10.0 to avoid everything being a 10)
    max_grade_after_curve: float = 10.0


_curve_config = GradeCurveConfig()


def apply_grade_curve(raw_score: float, config: GradeCurveConfig = None) -> float:
    """Apply a grade curve to shift the distribution toward higher grades.

    The curve adds an offset that tapers as the grade approaches 10.0,
    preventing unrealistic inflation while pushing borderline cards up.
    """
    cfg = config or _curve_config
    if not cfg.enabled or raw_score < cfg.min_raw_score:
        return raw_score

    # Taper: full offset at 6.0, zero offset at 10.0
    headroom = cfg.max_grade_after_curve - raw_score
    taper = min(1.0, headroom / 4.0)  # Linear taper over 4-point range
    adjusted = raw_score + (cfg.curve_offset * taper)

    return min(adjusted, cfg.max_grade_after_curve)


def get_curve_config() -> dict:
    return {
        "enabled": _curve_config.enabled,
        "curve_offset": _curve_config.curve_offset,
        "min_raw_score": _curve_config.min_raw_score,
    }


def set_curve_config(enabled: bool = None, curve_offset: float = None, min_raw_score: float = None):
    global _curve_config
    if enabled is not None:
        _curve_config.enabled = enabled
    if curve_offset is not None:
        _curve_config.curve_offset = max(-1.0, min(1.0, curve_offset))
    if min_raw_score is not None:
        _curve_config.min_raw_score = min_raw_score


# ============================================================
# Smart Rounding (Round Up on Doubt)
# ============================================================

def smart_round(raw_score: float, confidence: float = 100.0, threshold: float = 0.1) -> float:
    """Round to nearest 0.5, but round UP if within threshold of next increment
    and confidence is below 70%.

    This naturally pushes borderline cards toward higher grades.
    """
    nearest_half = round(raw_score * 2) / 2
    next_half = nearest_half + 0.5

    # How close to the next 0.5 increment?
    distance_to_next = next_half - raw_score

    if distance_to_next <= threshold and confidence < 70.0 and next_half <= 10.0:
        logger.debug(f"Smart round UP: {raw_score:.2f} -> {next_half} (confidence={confidence:.0f}%, distance={distance_to_next:.2f})")
        return next_half

    return max(1.0, min(10.0, nearest_half))


# ============================================================
# Defect Severity Diminishing Returns
# ============================================================

def apply_diminishing_returns(defects: list[dict]) -> list[dict]:
    """Apply diminishing returns to multiple minor defects in the same category.

    The 4th+ minor defect in the same category has 50% less score_impact.
    This prevents unfair grade drops from accumulated normal wear.
    """
    category_counts: dict[str, int] = {}
    adjusted = []

    for defect in defects:
        cat = defect.get("category", "unknown")
        severity = defect.get("severity", "minor")
        impact = defect.get("score_impact", 0)

        category_counts[cat] = category_counts.get(cat, 0) + 1
        count = category_counts[cat]

        if severity == "minor" and count > 3:
            # Diminishing returns: 50% reduction for 4th+ minor defect
            reduction = 0.5
            original_impact = impact
            impact = impact * reduction
            defect = {**defect, "score_impact": round(impact, 4),
                      "diminished": True, "original_impact": original_impact}
            logger.debug(f"Diminishing returns: {cat} minor #{count}, impact {original_impact:.3f} -> {impact:.3f}")

        adjusted.append(defect)

    return adjusted


# ============================================================
# Vintage vs Modern Profile Auto-Detection
# ============================================================

# Cards from sets released before this year get vintage treatment
VINTAGE_CUTOFF_YEAR = 2010

# Known vintage sets (partial list — expand as needed)
VINTAGE_SETS = {
    "base set", "jungle", "fossil", "team rocket", "gym heroes",
    "gym challenge", "neo genesis", "neo discovery", "neo revelation",
    "neo destiny", "legendary collection", "expedition",
    "aquapolis", "skyridge", "ruby & sapphire", "sandstorm",
    "dragon", "team magma vs team aqua", "hidden legends",
    "firered & leafgreen", "team rocket returns", "deoxys",
    "emerald", "unseen forces", "delta species",
    "base set 2", "bs2", "wizards black star promos",
}


def detect_era(set_name: str = "", language: str = "en") -> str:
    """Detect if a card is vintage or modern based on set name.

    Returns 'vintage' or 'modern'.
    """
    if not set_name:
        return "modern"

    set_lower = set_name.lower().strip()

    # Check against known vintage sets
    for vintage_set in VINTAGE_SETS:
        if vintage_set in set_lower:
            return "vintage"

    return "modern"


def get_era_profile_name(era: str, base_profile: str = "standard") -> str:
    """Get the appropriate sensitivity profile for a card's era.

    Vintage cards use 'lenient', modern cards use the configured profile.
    """
    if era == "vintage":
        return "lenient"
    return base_profile


# ============================================================
# Holographic Card Intelligence
# ============================================================

HOLO_TYPES = {
    "cosmos", "reverse", "full art", "rainbow rare", "gold",
    "secret rare", "v", "vmax", "vstar", "ex", "gx",
    "illustration rare", "special art", "alt art",
}


def detect_holo_type(card_name: str = "", rarity: str = "") -> Optional[str]:
    """Detect the holographic type from card name and rarity."""
    combined = f"{card_name} {rarity}".lower()
    for holo in HOLO_TYPES:
        if holo in combined:
            return holo
    return None


def get_holo_surface_tolerance(holo_type: Optional[str]) -> float:
    """Get the surface analysis tolerance multiplier for holo cards.

    Holo cards have rainbow patterns that look like scratches.
    Returns a multiplier (1.0 = no change, 1.3 = 30% more tolerant).
    """
    if not holo_type:
        return 1.0

    # Full art / illustration rare have the most pattern interference
    high_tolerance = {"full art", "illustration rare", "special art", "alt art", "rainbow rare"}
    medium_tolerance = {"reverse", "cosmos", "gold", "secret rare"}

    if holo_type in high_tolerance:
        return 1.5  # 50% more tolerant
    elif holo_type in medium_tolerance:
        return 1.3  # 30% more tolerant
    return 1.2  # 20% more tolerant for all other holos


# ============================================================
# Quick Grade Mode
# ============================================================

def should_quick_grade(initial_quality_score: float, threshold: float = 92.0) -> bool:
    """Determine if a card qualifies for quick grading (skip deep analysis).

    Cards with initial quality above the threshold are likely mint/near-mint
    and don't need exhaustive defect scanning.
    """
    return initial_quality_score >= threshold


# ============================================================
# Confidence-Based Routing
# ============================================================

@dataclass
class GradeRouting:
    """Routing decision for a graded card."""
    route: str  # "auto_approve", "standard_review", "senior_review"
    reason: str
    confidence: float


def route_grade(confidence: float, final_grade: float) -> GradeRouting:
    """Determine the review routing based on AI confidence and grade.

    - High confidence (90%+): auto-approve
    - Medium confidence (70-90%): standard operator review
    - Low confidence (<70%): route to senior grader
    """
    if confidence >= 90.0:
        return GradeRouting(
            route="auto_approve",
            reason=f"High confidence ({confidence:.0f}%) — auto-approved",
            confidence=confidence,
        )
    elif confidence >= 70.0:
        return GradeRouting(
            route="standard_review",
            reason=f"Medium confidence ({confidence:.0f}%) — standard review",
            confidence=confidence,
        )
    else:
        return GradeRouting(
            route="senior_review",
            reason=f"Low confidence ({confidence:.0f}%) — needs senior grader review",
            confidence=confidence,
        )


# ============================================================
# Grade Explanation Generator
# ============================================================

def generate_explanation(
    final_grade: float,
    sub_scores: dict,
    defects: list[dict],
    caps_applied: list[dict],
    card_name: str = "",
) -> str:
    """Generate a human-readable explanation of why a card received its grade.

    Example: "This card received an 8.5. The centering is excellent (9.5)
    with near-perfect borders. The corners show minor whitening (-0.5)..."
    """
    grade_words = {
        10.0: "Gem Mint", 9.5: "Mint+", 9.0: "Mint",
        8.5: "Near Mint-Mint", 8.0: "Near Mint",
        7.5: "Near Mint-", 7.0: "Excellent-Mint",
        6.5: "Excellent+", 6.0: "Excellent",
        5.5: "Excellent-", 5.0: "Very Good-Excellent",
    }
    grade_label = grade_words.get(final_grade, f"Grade {final_grade}")

    def score_word(score):
        if score >= 9.5: return "pristine"
        if score >= 9.0: return "excellent"
        if score >= 8.5: return "very good"
        if score >= 8.0: return "good"
        if score >= 7.0: return "acceptable"
        if score >= 6.0: return "fair"
        return "poor"

    parts = [f"This card received a {final_grade} ({grade_label})."]

    # Centering
    c = sub_scores.get("centering", 0)
    parts.append(f"Centering is {score_word(c)} ({c:.1f}).")

    # Corners
    co = sub_scores.get("corners", 0)
    corner_defects = [d for d in defects if d.get("category") == "corner"]
    if corner_defects:
        issues = ", ".join(set(d.get("defect_type", "wear") for d in corner_defects[:3]))
        parts.append(f"Corners show {issues} ({co:.1f}).")
    else:
        parts.append(f"Corners are {score_word(co)} ({co:.1f}) with no defects detected.")

    # Edges
    e = sub_scores.get("edges", 0)
    edge_defects = [d for d in defects if d.get("category") == "edge"]
    if edge_defects:
        issues = ", ".join(set(d.get("defect_type", "wear") for d in edge_defects[:3]))
        parts.append(f"Edges show {issues} ({e:.1f}).")
    else:
        parts.append(f"Edges are {score_word(e)} ({e:.1f}) with clean edges throughout.")

    # Surface
    s = sub_scores.get("surface", 0)
    surface_defects = [d for d in defects if d.get("category") == "surface"]
    if surface_defects:
        issues = ", ".join(set(d.get("defect_type", "mark") for d in surface_defects[:3]))
        parts.append(f"Surface shows {issues} ({s:.1f}).")
    else:
        parts.append(f"Surface is {score_word(s)} ({s:.1f}) with no visible defects.")

    # Caps
    if caps_applied:
        cap_reasons = [c.get("reason", "defect") for c in caps_applied]
        parts.append(f"Grade was capped due to: {', '.join(cap_reasons)}.")

    return " ".join(parts)


# ============================================================
# Cross-Validation on Re-Grades
# ============================================================

def cross_validate_grade(new_grade: float, previous_grade: float, tolerance: float = 0.5) -> dict:
    """Check if a re-grade is consistent with the previous grade.

    Returns validation result with flag if inconsistent.
    """
    delta = abs(new_grade - previous_grade)
    consistent = delta <= tolerance

    return {
        "consistent": consistent,
        "delta": round(delta, 1),
        "new_grade": new_grade,
        "previous_grade": previous_grade,
        "warning": None if consistent else f"Grade changed by {delta:.1f} (previous: {previous_grade}, new: {new_grade}). Review recommended.",
    }


# ============================================================
# Set-Specific Known Issues Database
# ============================================================

# Known manufacturing defects that should NOT count against the grade
KNOWN_ISSUES: dict[str, list[dict]] = {
    "base set": [
        {"card_pattern": "charizard", "issue": "print_line", "location": "back", "description": "Known print line on back of Base Set Charizard"},
        {"card_pattern": "blastoise", "issue": "centering", "description": "Base Set Blastoise commonly off-center by 55/45"},
    ],
    "jungle": [
        {"card_pattern": "*", "issue": "silvering", "description": "Jungle set 1st Edition commonly shows edge silvering"},
    ],
    "fossil": [
        {"card_pattern": "*", "issue": "print_line", "location": "back", "description": "Fossil set cards often have faint horizontal print lines"},
    ],
    "sword & shield": [
        {"card_pattern": "v", "issue": "centering", "description": "Sword & Shield V cards have known centering issues from factory"},
    ],
}


def get_known_issues(set_name: str, card_name: str = "") -> list[dict]:
    """Get known manufacturing defects for a card's set.

    Returns list of known issues that should be discounted during grading.
    """
    if not set_name:
        return []

    set_lower = set_name.lower().strip()
    issues = []

    for set_key, set_issues in KNOWN_ISSUES.items():
        if set_key in set_lower:
            for issue in set_issues:
                pattern = issue.get("card_pattern", "*")
                if pattern == "*" or (card_name and pattern.lower() in card_name.lower()):
                    issues.append(issue)

    return issues


def discount_known_issues(defects: list[dict], known_issues: list[dict]) -> list[dict]:
    """Reduce the score impact of defects that match known manufacturing issues.

    Known issues get their impact halved.
    """
    if not known_issues:
        return defects

    known_types = {ki["issue"] for ki in known_issues}

    adjusted = []
    for defect in defects:
        if defect.get("defect_type") in known_types:
            defect = {**defect,
                      "score_impact": defect.get("score_impact", 0) * 0.5,
                      "known_issue": True,
                      "original_impact": defect.get("score_impact", 0)}
            logger.debug(f"Known issue discount: {defect['defect_type']} impact halved")
        adjusted.append(defect)

    return adjusted


# ============================================================
# Smart Queue Prioritisation
# ============================================================

def prioritise_queue(cards: list[dict]) -> list[dict]:
    """Sort cards by priority — higher value cards first.

    Uses grade potential and card value indicators.
    """
    def priority_score(card):
        # Higher rarity = higher priority
        rarity_scores = {
            "secret rare": 100, "illustration rare": 95,
            "special art rare": 90, "ultra rare": 85,
            "rare holo": 70, "rare": 50,
            "uncommon": 20, "common": 10,
        }
        rarity = (card.get("rarity") or "").lower()
        r_score = 30  # default
        for key, val in rarity_scores.items():
            if key in rarity:
                r_score = val
                break

        return r_score

    return sorted(cards, key=priority_score, reverse=True)


# ============================================================
# Defect Photo Evidence
# ============================================================

def crop_defect_region(
    image_path: str,
    bbox_x: int, bbox_y: int, bbox_w: int, bbox_h: int,
    padding: int = 50,
    output_dir: str = "data/exports/defect_crops",
) -> Optional[str]:
    """Crop a region around a defect for evidence photos.

    Returns the path to the cropped image, or None on failure.
    """
    try:
        from PIL import Image

        img = Image.open(image_path)
        w, h = img.size

        # Add padding
        x1 = max(0, bbox_x - padding)
        y1 = max(0, bbox_y - padding)
        x2 = min(w, bbox_x + bbox_w + padding)
        y2 = min(h, bbox_y + bbox_h + padding)

        crop = img.crop((x1, y1, x2, y2))

        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        import uuid
        filename = f"defect_{uuid.uuid4().hex[:8]}.png"
        out_path = out_dir / filename
        crop.save(str(out_path), "PNG")

        return str(out_path)
    except Exception as e:
        logger.error(f"Failed to crop defect region: {e}")
        return None


# ============================================================
# Daily Grade Target Dashboard Data
# ============================================================

def get_daily_targets(operator_name: str = "", target_cards_per_day: int = 50) -> dict:
    """Calculate daily grading progress and pace."""
    # This would normally query the database for today's grades
    # For now, return the structure that the UI can populate
    return {
        "target": target_cards_per_day,
        "graded_today": 0,  # Populated by API route from DB query
        "remaining": target_cards_per_day,
        "pace_cards_per_hour": 0,
        "estimated_completion": None,
        "operator": operator_name,
    }


# ============================================================
# Auto-Slab Routing
# ============================================================

def should_auto_slab(final_grade: float, confidence: float, min_grade: float = 9.0) -> bool:
    """Determine if a card should be fast-tracked to slab assembly.

    Cards grading 9+ with high confidence skip manual review.
    """
    return final_grade >= min_grade and confidence >= 85.0


# ============================================================
# Scanner Profile Auto-Detection
# ============================================================

@dataclass
class ScannerProfile:
    """Calibration profile for a specific scanner."""
    scanner_id: str
    brightness_offset: float = 0.0
    contrast_multiplier: float = 1.0
    colour_temp_offset: float = 0.0
    created_at: str = ""


_scanner_profiles: dict[str, ScannerProfile] = {}


def get_scanner_profile(scanner_id: str) -> Optional[ScannerProfile]:
    """Get calibration profile for a scanner."""
    return _scanner_profiles.get(scanner_id)


def create_scanner_profile(scanner_id: str, reference_metrics: dict) -> ScannerProfile:
    """Create a scanner profile from a reference card scan.

    The reference metrics (brightness, contrast) establish the baseline
    for this scanner. Future scans are normalised against this baseline.
    """
    # Ideal reference values (from a known-good scanner)
    ideal_brightness = 50.0
    ideal_contrast = 50.0

    brightness = reference_metrics.get("brightness", ideal_brightness)
    contrast = reference_metrics.get("contrast", ideal_contrast)

    profile = ScannerProfile(
        scanner_id=scanner_id,
        brightness_offset=ideal_brightness - brightness,
        contrast_multiplier=ideal_contrast / max(contrast, 1.0),
        created_at=datetime.utcnow().isoformat(),
    )
    _scanner_profiles[scanner_id] = profile
    logger.info(f"Scanner profile created: {scanner_id} (brightness_offset={profile.brightness_offset:.1f})")
    return profile
