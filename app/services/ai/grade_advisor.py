"""AI grading advisor — second opinion on card grades.

After CV grading completes, sends the card image plus grade results to an LLM
for a second opinion. The AI review is ADVISORY ONLY and never auto-changes
the grade.
"""

import logging
from dataclasses import dataclass, asdict
from typing import Optional

from app.config import settings
from app.services.ai import openrouter

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert Pokemon TCG card grader. Given a card image and the automated grading results, provide a second opinion.

Evaluate:
1. Do you agree with the overall grade?
2. Are there any defects the automated system might have missed?
3. Are there any defects that seem over-penalised?
4. What would you suggest as adjustments?

Return ONLY valid JSON:
{
  "agrees_with_grade": true/false,
  "suggested_grade": <float or null if you agree>,
  "missed_defects": ["list of potential defects not caught"],
  "over_penalised": ["list of defects that seem over-penalised"],
  "overall_assessment": "1-2 sentence summary",
  "confidence": <float 0.0-1.0>
}"""


@dataclass
class AIGradeReview:
    """AI second opinion on a card grade."""
    agrees_with_grade: bool = True
    suggested_grade: Optional[float] = None
    missed_defects: list = None
    over_penalised: list = None
    overall_assessment: str = ""
    confidence: float = 0.0

    def __post_init__(self):
        if self.missed_defects is None:
            self.missed_defects = []
        if self.over_penalised is None:
            self.over_penalised = []

    def to_dict(self) -> dict:
        return asdict(self)


async def get_grade_review(
    card_image,
    grade_data: dict,
) -> Optional[AIGradeReview]:
    """Get AI second opinion on a card grade.

    Args:
        card_image: numpy/PIL image of the card.
        grade_data: Dict with final_grade, sub-grades, defects, etc.

    Returns:
        AIGradeReview or None if AI is disabled or fails.
    """
    if not settings.openrouter.enabled:
        return None

    # Build grade summary for the prompt
    defects_text = ""
    if grade_data.get("defects"):
        defect_list = [
            f"  - {d.get('defect_type', '?')} ({d.get('severity', '?')}) "
            f"impact: -{d.get('score_impact', '?')}"
            for d in grade_data["defects"]
            if not d.get("is_noise")
        ]
        defects_text = "\n".join(defect_list[:15])  # Limit to 15

    user_msg = (
        f"Automated grading results:\n"
        f"  Final Grade: {grade_data.get('final_grade', '?')}\n"
        f"  Centering: {grade_data.get('centering_score', '?')}\n"
        f"  Corners: {grade_data.get('corners_score', '?')}\n"
        f"  Edges: {grade_data.get('edges_score', '?')}\n"
        f"  Surface: {grade_data.get('surface_score', '?')}\n"
        f"  Centering L/R: {grade_data.get('centering_ratio_lr', '?')}\n"
        f"  Centering T/B: {grade_data.get('centering_ratio_tb', '?')}\n"
        f"  Defect count: {grade_data.get('defect_count', 0)}\n"
    )
    if defects_text:
        user_msg += f"\nDetected defects:\n{defects_text}\n"

    user_msg += "\nPlease review the card image and provide your assessment."

    response = await openrouter.chat(
        system_prompt=SYSTEM_PROMPT,
        user_message=user_msg,
        images=[card_image],
        temperature=0.2,
        max_tokens=600,
    )

    if not response:
        return None

    data = response.parse_json()
    if not data:
        return None

    review = AIGradeReview(
        agrees_with_grade=data.get("agrees_with_grade", True),
        suggested_grade=data.get("suggested_grade"),
        missed_defects=data.get("missed_defects", []),
        over_penalised=data.get("over_penalised", []),
        overall_assessment=data.get("overall_assessment", ""),
        confidence=data.get("confidence", 0.0),
    )

    logger.info(
        "AI grade review: agrees=%s suggested=%.1f confidence=%.2f",
        review.agrees_with_grade,
        review.suggested_grade or grade_data.get("final_grade", 0),
        review.confidence,
    )

    return review
