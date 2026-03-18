"""AI-powered card identification disambiguation.

When PokeWallet returns uncertain results (confidence < 0.65 or top two
candidates are close), uses an LLM to pick the best match from the
candidate list.
"""

import logging
from typing import Optional

from app.config import settings
from app.services.ai import openrouter

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a Pokemon TCG card identification expert. Given OCR-extracted fields from a card and a list of candidate matches from a card database, determine which candidate is the best match.

Return ONLY valid JSON:
{
  "best_index": <integer index of the best match from the candidates list, 0-based>,
  "confidence": <float 0.0-1.0 of your confidence>,
  "reasoning": "brief explanation"
}

If NONE of the candidates match, return:
{
  "best_index": null,
  "confidence": 0.0,
  "reasoning": "explanation of why none match"
}"""


async def disambiguate(
    ocr_fields: dict,
    candidates: list[dict],
) -> Optional[dict]:
    """Use AI to pick the best card match from candidates.

    Args:
        ocr_fields: Dict with card_name, set_name, collector_number, etc.
        candidates: List of candidate dicts with name, set, number, etc.

    Returns:
        Dict with best_index, confidence, reasoning or None.
    """
    if not settings.openrouter.enabled:
        return None

    if not candidates:
        return None

    # Build candidate list text
    cand_text = "\n".join(
        f"  [{i}] {c.get('name', '?')} - Set: {c.get('set_name', '?')} - "
        f"#{c.get('collector_number', '?')} - Score: {c.get('confidence', '?')}"
        for i, c in enumerate(candidates)
    )

    user_msg = (
        f"OCR-extracted fields:\n"
        f"  Card Name: {ocr_fields.get('card_name', 'unknown')}\n"
        f"  Set: {ocr_fields.get('set_name', 'unknown')}\n"
        f"  Collector #: {ocr_fields.get('collector_number', 'unknown')}\n"
        f"  HP: {ocr_fields.get('hp', 'unknown')}\n"
        f"  Rarity: {ocr_fields.get('rarity', 'unknown')}\n"
        f"\nCandidate matches:\n{cand_text}\n"
        f"\nWhich candidate is the best match?"
    )

    response = await openrouter.chat(
        system_prompt=SYSTEM_PROMPT,
        user_message=user_msg,
        temperature=0.1,
        max_tokens=300,
    )

    if not response:
        return None

    data = response.parse_json()
    if not data:
        return None

    logger.info(
        "AI card matcher: index=%s confidence=%.2f reason=%s",
        data.get("best_index"), data.get("confidence", 0), data.get("reasoning", "")[:80],
    )

    return data
