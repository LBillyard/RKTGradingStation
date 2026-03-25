"""AI Vision Grader — uses Gemini 2.0 Flash to grade cards by actually looking at them.

Replaces/supplements the OpenCV algorithmic grading with vision-model-based
defect detection that understands what cards look like and can distinguish
real defects from printed artwork.
"""

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PIL import Image

logger = logging.getLogger(__name__)

BRAIN_PATH = Path("data/grading_brain.md")

# P8: Cache the system prompt to avoid rebuilding on every call
_cached_system_prompt: Optional[str] = None
_cached_brain_hash: Optional[str] = None


@dataclass
class VisionDefect:
    """A defect found by the AI vision grader."""
    category: str  # centering, corners, edges, surface
    defect_type: str  # whitening, scratch, dent, etc.
    severity: str  # minor, moderate, major, severe
    location: str  # top_left corner, left edge, center surface, etc.
    score_impact: float  # how much this defect reduces the sub-grade
    confidence: float  # 0.0-1.0
    description: str  # human-readable description


@dataclass
class VisionGradeResult:
    """Result from AI vision grading."""
    centering_score: float
    corners_score: float
    edges_score: float
    surface_score: float
    final_grade: float
    raw_score: float
    defects: list[VisionDefect] = field(default_factory=list)
    grade_explanation: str = ""
    confidence: float = 0.0
    model_used: str = ""
    token_usage: dict = field(default_factory=dict)
    # Keep OpenCV scores for comparison
    opencv_centering: Optional[float] = None
    opencv_corners: Optional[float] = None
    opencv_edges: Optional[float] = None
    opencv_surface: Optional[float] = None
    opencv_final: Optional[float] = None


def _load_grading_brain() -> str:
    """Load the grading standards document."""
    if BRAIN_PATH.exists():
        return BRAIN_PATH.read_text(encoding="utf-8")
    logger.warning("Grading brain not found at %s", BRAIN_PATH)
    return "Grade cards on a 1-10 scale. 10=Gem Mint, 9=Mint, 8=NM-Mint, 7=Near Mint, 6=EX-NM, 5=Excellent."


def _get_system_prompt() -> str:
    """Return the system prompt, rebuilding only when the brain file changes."""
    global _cached_system_prompt, _cached_brain_hash

    brain = _load_grading_brain()
    brain_hash = hashlib.md5(brain.encode()).hexdigest()

    if _cached_system_prompt is not None and brain_hash == _cached_brain_hash:
        return _cached_system_prompt

    _cached_brain_hash = brain_hash
    _cached_system_prompt = f"""You are an expert trading card grader for RKT Grading.
You evaluate card condition by examining scanned images.

Follow these grading standards precisely:

{brain}

Always respond with valid JSON matching the requested format."""

    logger.debug("Rebuilt AI grading system prompt (brain hash: %s)", brain_hash)
    return _cached_system_prompt


def _build_grading_prompt(card_info: Optional[dict] = None, has_back: bool = False) -> str:
    """Build the user prompt for vision grading."""
    card_context = ""
    if card_info:
        parts = []
        if card_info.get("card_name"):
            parts.append(f"Card: {card_info['card_name']}")
        if card_info.get("set_name"):
            parts.append(f"Set: {card_info['set_name']}")
        if card_info.get("language"):
            parts.append(f"Language: {card_info['language']}")
        if card_info.get("rarity"):
            parts.append(f"Rarity: {card_info['rarity']}")
        if parts:
            card_context = f"\n\nCard Information: {', '.join(parts)}"

    back_instruction = ""
    if has_back:
        back_instruction = """
The SECOND image is the BACK of the card. Evaluate both sides:
- Corners and edges: use the WORST score between front and back
- Surface: evaluate both sides separately, use the WORST score
- Centering: evaluate from the FRONT only"""

    return f"""Grade this trading card image. {card_context}

{back_instruction}

Examine the card carefully and provide:
1. Sub-grades for centering, corners, edges, and surface (each 1.0-10.0 in 0.5 increments)
2. A list of every defect you can see
3. A final overall grade (1.0-10.0 in 0.5 increments)
4. A brief explanation of the grade

IMPORTANT:
- Do NOT penalise printed card artwork, textures, holo patterns, or set logos as defects
- Only score PHYSICAL damage: whitening, scratches, dents, creases, chips, stains, print lines
- Be fair and accurate — grade exactly what you see, neither too harsh nor too lenient
- Consider the card era: vintage cards (pre-2003) are expected to have some wear
- This image is from a 600 DPI flatbed scanner — ignore scanner artifacts, dust, and holo refraction
- Only deduct points for defects you can specifically identify and describe
- CRITICAL: Look closely at ALL 4 corners for whitening, softening, or wear — corners are the most commonly missed defect
- CRITICAL: Examine the surface carefully for scratches, scuffs, or wear — surface damage is often subtle in scans
- A perfect 10 means ZERO visible defects — most cards have at least minor wear, so 10s should be rare
- Corner whitening on even 1 corner drops the corners score to 9.0 or below depending on severity
- Visible surface scratches or scuffs drop the surface score to 8.0-9.0 depending on severity

Respond in this exact JSON format:
{{
  "centering_score": <1.0-10.0>,
  "corners_score": <1.0-10.0>,
  "edges_score": <1.0-10.0>,
  "surface_score": <1.0-10.0>,
  "final_grade": <1.0-10.0>,
  "grade_explanation": "Explain what you see and why you chose each score...",
  "confidence": <0.0-1.0>,
  "defects": [
    {{
      "category": "corners|edges|surface|centering",
      "defect_type": "whitening|scratch|dent|crease|chip|print_line|stain|softening",
      "severity": "minor|moderate|severe",
      "location": "top_left corner|bottom_right edge|center surface|etc",
      "score_impact": -0.5,
      "confidence": 0.8,
      "description": "Describe the specific defect you see"
    }}
  ]
}}"""


async def grade_card_with_vision(
    image_path: str,
    card_info: Optional[dict] = None,
    back_image_path: Optional[str] = None,
) -> Optional[VisionGradeResult]:
    """Grade a card using AI vision analysis.

    Args:
        image_path: Path to the front card image.
        card_info: Optional dict with card_name, set_name, language, rarity.
        back_image_path: Optional path to back card image.

    Returns:
        VisionGradeResult or None if AI is unavailable.
    """
    from app.services.ai.openrouter import chat

    # P8: Use cached system prompt (only rebuilds when brain file changes)
    system_prompt = _get_system_prompt()

    # Load images
    images = []
    try:
        front_img = Image.open(image_path).convert("RGB")
        images.append(front_img)
    except Exception as e:
        logger.error("Failed to load front image %s: %s", image_path, e)
        return None

    has_back = False
    if back_image_path and os.path.exists(back_image_path):
        try:
            back_img = Image.open(back_image_path).convert("RGB")
            images.append(back_img)
            has_back = True
        except Exception as e:
            logger.warning("Failed to load back image: %s", e)

    # Build prompt
    user_prompt = _build_grading_prompt(card_info, has_back)

    # Call AI
    logger.info("AI vision grading: %s", card_info.get("card_name", "unknown") if card_info else "unknown")
    response = await chat(
        system_prompt=system_prompt,
        user_message=user_prompt,
        images=images,
        temperature=0.1,
        max_tokens=3000,
    )

    if response is None:
        logger.warning("AI vision grading unavailable — OpenRouter returned None")
        return None

    # Parse response
    result = response.parse_json()
    if result is None:
        logger.error("AI vision grading returned non-JSON response: %s", response.content[:300])
        return None

    try:
        defects = []
        for d in result.get("defects", []):
            defects.append(VisionDefect(
                category=d.get("category", "surface"),
                defect_type=d.get("defect_type", "unknown"),
                severity=d.get("severity", "minor"),
                location=d.get("location", "unknown"),
                score_impact=float(d.get("score_impact", -0.5)),
                confidence=float(d.get("confidence", 0.5)),
                description=d.get("description", ""),
            ))

        # Snap to 0.5 increments
        def snap(v):
            return round(float(v) * 2) / 2

        grade_result = VisionGradeResult(
            centering_score=snap(result.get("centering_score", 5.0)),
            corners_score=snap(result.get("corners_score", 5.0)),
            edges_score=snap(result.get("edges_score", 5.0)),
            surface_score=snap(result.get("surface_score", 5.0)),
            final_grade=snap(result.get("final_grade", 5.0)),
            raw_score=float(result.get("final_grade", 5.0)),
            defects=defects,
            grade_explanation=result.get("grade_explanation", ""),
            confidence=float(result.get("confidence", 0.5)),
            model_used=response.model,
            token_usage=response.token_usage,
        )

        logger.info(
            "AI vision grade: %.1f (C:%.1f Co:%.1f E:%.1f S:%.1f) — %d defects, %.0f%% confidence",
            grade_result.final_grade, grade_result.centering_score,
            grade_result.corners_score, grade_result.edges_score,
            grade_result.surface_score, len(defects),
            grade_result.confidence * 100,
        )

        return grade_result

    except (KeyError, ValueError, TypeError) as e:
        logger.error("Failed to parse AI vision grade result: %s — raw: %s", e, str(result)[:300])
        return None
