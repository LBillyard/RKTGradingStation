"""Centering analysis for card grading."""

import logging
from dataclasses import dataclass, field
from typing import Optional

from app.services.vision.border import BorderMeasurement
from app.utils.validation import round_grade

logger = logging.getLogger(__name__)


# Score mapping: maps maximum off-center percentage to a grade.
# The percentage represents the larger side of the ratio.
# e.g., 50% = perfect centering (50/50) = grade 10
#        55% = slightly off (55/45) = grade 9.5
CENTERING_SCORE_MAP: list[tuple[float, float]] = [
    (50.0, 10.0),
    (55.0, 9.5),
    (58.0, 9.0),
    (60.0, 8.5),
    (62.0, 8.0),
    (65.0, 7.5),
    (68.0, 7.0),
    (70.0, 6.0),
    (75.0, 5.0),
    (80.0, 4.0),
    (85.0, 3.0),
    (90.0, 2.0),
    (95.0, 1.0),
]

# Centering grade caps: the maximum final grade allowed for a given
# off-center percentage (SOP Section 7).  Uses front centering as
# the primary limiter.
CENTERING_CAPS: list[tuple[float, float]] = [
    (55.0, 10.0),
    (60.0, 9.0),
    (65.0, 8.0),
    (70.0, 7.0),
    (75.0, 6.0),
    (80.0, 5.0),
    (85.0, 4.0),
    (90.0, 3.0),
]


def get_centering_cap(lr_pct: float, tb_pct: float) -> float:
    """Return the maximum grade allowed by centering.

    Uses the worse axis (larger off-center percentage) to determine
    the cap.  Returns 10.0 if centering is within tolerance.
    """
    off_lr = max(lr_pct, 100.0 - lr_pct)
    off_tb = max(tb_pct, 100.0 - tb_pct)
    worst = max(off_lr, off_tb)

    if worst <= CENTERING_CAPS[0][0]:
        return 10.0

    for i in range(len(CENTERING_CAPS) - 1):
        lower_pct, lower_cap = CENTERING_CAPS[i]
        upper_pct, upper_cap = CENTERING_CAPS[i + 1]
        if lower_pct <= worst <= upper_pct:
            return lower_cap  # step function — return cap at lower bracket

    return 1.0


@dataclass
class CenteringResult:
    """Result of centering analysis."""
    lr_ratio: str              # e.g., "52/48"
    tb_ratio: str              # e.g., "50/50"
    lr_percentage: float       # left side percentage (50 = perfect)
    tb_percentage: float       # top side percentage (50 = perfect)
    lr_score: float            # grade for left-right centering
    tb_score: float            # grade for top-bottom centering
    final_score: float         # minimum of lr and tb scores
    details: dict = field(default_factory=dict)


class CenteringAnalyzer:
    """Analyze card centering from border measurements.

    Takes border widths measured by the vision pipeline and computes
    centering ratios and a centering sub-grade.
    """

    def __init__(self):
        self._score_map = CENTERING_SCORE_MAP

    def analyze(self, borders: BorderMeasurement) -> CenteringResult:
        """Compute centering score from border measurements.

        Args:
            borders: BorderMeasurement from the vision pipeline containing
                     top, bottom, left, right pixel widths and ratios.

        Returns:
            CenteringResult with ratios, per-axis scores, and final score.
        """
        lr_pct = borders.lr_percentage
        tb_pct = borders.tb_percentage

        lr_score = self._percentage_to_score(lr_pct)
        tb_score = self._percentage_to_score(tb_pct)
        final_score = min(lr_score, tb_score)

        # Round to valid grade
        final_score = round_grade(final_score)

        logger.debug(
            "Centering analysis: LR=%s (%.1f), TB=%s (%.1f), "
            "lr_score=%.1f, tb_score=%.1f, final=%.1f",
            borders.lr_ratio, lr_pct, borders.tb_ratio, tb_pct,
            lr_score, tb_score, final_score,
        )

        return CenteringResult(
            lr_ratio=borders.lr_ratio,
            tb_ratio=borders.tb_ratio,
            lr_percentage=lr_pct,
            tb_percentage=tb_pct,
            lr_score=lr_score,
            tb_score=tb_score,
            final_score=final_score,
            details={
                "border_top": borders.top,
                "border_bottom": borders.bottom,
                "border_left": borders.left,
                "border_right": borders.right,
            },
        )

    def _percentage_to_score(self, percentage: float) -> float:
        """Convert an off-center percentage to a centering grade.

        The percentage represents one side of the ratio. Perfect centering
        is 50%. We use the larger of the two sides (i.e., max(pct, 100-pct))
        to determine how off-center the card is.

        Args:
            percentage: One side percentage (e.g., 52 means 52/48).

        Returns:
            Grade value from 1.0 to 10.0.
        """
        # Normalise to the larger side
        off_center = max(percentage, 100.0 - percentage)

        # Walk the score map; find the bracket
        if off_center <= self._score_map[0][0]:
            return self._score_map[0][1]

        for i in range(len(self._score_map) - 1):
            lower_pct, lower_grade = self._score_map[i]
            upper_pct, upper_grade = self._score_map[i + 1]

            if lower_pct <= off_center <= upper_pct:
                # Linear interpolation between brackets
                if upper_pct == lower_pct:
                    return lower_grade
                ratio = (off_center - lower_pct) / (upper_pct - lower_pct)
                interpolated = lower_grade - ratio * (lower_grade - upper_grade)
                return round(interpolated * 2) / 2  # snap to 0.5

        # Worse than the worst bracket
        return 1.0
