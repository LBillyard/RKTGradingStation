"""Grade scoring and weighted calculation."""

import logging
from dataclasses import dataclass, field
from typing import Optional

from app.utils.validation import VALID_GRADES, round_grade

logger = logging.getLogger(__name__)


# Default sub-grade weights (must sum to 1.0)
WEIGHTS: dict[str, float] = {
    "centering": 0.10,
    "corners": 0.30,
    "edges": 0.30,
    "surface": 0.30,
}


@dataclass
class GradeResult:
    """Complete grade calculation result."""
    sub_scores: dict[str, float]   # {"centering": 9.0, "corners": 8.5, ...}
    raw_score: float               # weighted average before caps
    caps_applied: list[dict]       # list of {"defect_type": ..., "cap": ...}
    final_grade: float             # rounded and capped grade in VALID_GRADES
    details: dict = field(default_factory=dict)


class GradeCalculator:
    """Calculate the final card grade from sub-scores and defect caps.

    Applies weighted averaging across four sub-grades, then enforces
    hard caps from detected defects, and rounds to the nearest valid
    grade on the 0.5 scale.
    """

    def __init__(self, weights: Optional[dict[str, float]] = None):
        """Initialize calculator with custom or default weights.

        Args:
            weights: Override weights dict with keys centering/corners/edges/surface.
                     Values must sum to 1.0.
        """
        self.weights = weights or WEIGHTS.copy()

        # Validate weights sum to ~1.0
        total = sum(self.weights.values())
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"Weights must sum to 1.0, got {total:.3f}")

    def calculate_weighted_score(
        self,
        centering: float,
        corners: float,
        edges: float,
        surface: float,
    ) -> float:
        """Calculate the weighted average of sub-grades.

        Args:
            centering: Centering sub-grade (1.0-10.0).
            corners: Corners sub-grade (1.0-10.0).
            edges: Edges sub-grade (1.0-10.0).
            surface: Surface sub-grade (1.0-10.0).

        Returns:
            Raw weighted score (not yet capped or rounded).
        """
        raw = (
            centering * self.weights["centering"]
            + corners * self.weights["corners"]
            + edges * self.weights["edges"]
            + surface * self.weights["surface"]
        )

        logger.debug(
            "Weighted score: %.2f (centering=%.1f*%.2f + corners=%.1f*%.2f "
            "+ edges=%.1f*%.2f + surface=%.1f*%.2f)",
            raw,
            centering, self.weights["centering"],
            corners, self.weights["corners"],
            edges, self.weights["edges"],
            surface, self.weights["surface"],
        )

        return raw

    def apply_caps(
        self,
        raw_score: float,
        defect_cap: Optional[float],
    ) -> tuple[float, list[dict]]:
        """Apply hard caps from defect findings to the raw score.

        Args:
            raw_score: The weighted average score.
            defect_cap: Minimum cap from DefectClassifier, or None.

        Returns:
            Tuple of (capped_score, list_of_caps_applied).
        """
        caps_applied: list[dict] = []
        capped = raw_score

        if defect_cap is not None and raw_score > defect_cap:
            caps_applied.append({
                "reason": "defect_hard_cap",
                "cap": defect_cap,
                "original_score": round(raw_score, 2),
            })
            capped = defect_cap
            logger.info(
                "Hard cap applied: %.2f -> %.1f",
                raw_score, defect_cap,
            )

        return capped, caps_applied

    def round_to_half(self, score: float) -> float:
        """Round a score to the nearest 0.5 and clamp to [1.0, 10.0].

        Args:
            score: Raw or capped score.

        Returns:
            Valid grade from VALID_GRADES.
        """
        return round_grade(score)

    def calculate(
        self,
        centering: float,
        corners: float,
        edges: float,
        surface: float,
        defect_cap: Optional[float] = None,
    ) -> GradeResult:
        """Full grade calculation pipeline.

        Computes weighted score, applies caps, rounds to valid grade.

        Args:
            centering: Centering sub-grade.
            corners: Corners sub-grade.
            edges: Edges sub-grade.
            surface: Surface sub-grade.
            defect_cap: Optional hard cap from defect analysis.

        Returns:
            Complete GradeResult.
        """
        sub_scores = {
            "centering": centering,
            "corners": corners,
            "edges": edges,
            "surface": surface,
        }

        raw_score = self.calculate_weighted_score(centering, corners, edges, surface)
        capped_score, caps_applied = self.apply_caps(raw_score, defect_cap)
        final_grade = self.round_to_half(capped_score)

        logger.info(
            "Grade calculated: raw=%.2f, capped=%.2f, final=%.1f, caps=%d",
            raw_score, capped_score, final_grade, len(caps_applied),
        )

        return GradeResult(
            sub_scores=sub_scores,
            raw_score=round(raw_score, 2),
            caps_applied=caps_applied,
            final_grade=final_grade,
            details={
                "weights": self.weights,
                "defect_cap": defect_cap,
            },
        )
