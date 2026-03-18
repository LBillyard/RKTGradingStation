"""AI-powered OCR enhancement for card text extraction.

After PaddleOCR/Tesseract runs, sends the raw text plus card image to an LLM
to clean up and extract structured fields.
"""

import logging
from dataclasses import dataclass, asdict
from typing import Optional

from app.config import settings
from app.services.ai import openrouter

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a Pokemon TCG card text expert. Given raw OCR text and/or an image of a Pokemon card, extract structured information.

IMPORTANT: Always return the ENGLISH name of the card, even if the card is in Japanese, Korean, Chinese, or another language. For example, if you see a Japanese card with "リザードンex", return "Charizard ex" as the card_name. Use the official English Pokemon TCG name.

Return ONLY valid JSON with these fields (use null for any field you cannot determine):
{
  "card_name": "string - the ENGLISH Pokemon or card name (translate if non-English card)",
  "hp": "string - HP value like '120'",
  "collector_number": "string - collector number like '25/185'",
  "rarity": "string - rarity symbol name: Common, Uncommon, Rare, Holo Rare, Ultra Rare, Secret Rare, RR, SR, SAR, etc.",
  "artist": "string - card artist name",
  "stage": "string - Basic, Stage 1, Stage 2, VSTAR, VMAX, ex, etc.",
  "energy_type": "string - Fire, Water, Grass, Lightning, Psychic, Fighting, Darkness, Metal, Dragon, Fairy, Colorless",
  "set_name": "string - the ENGLISH set name if known",
  "language": "string - detected card language: en, ja, ko, zh, etc."
}

Be precise. Only include information you are confident about from the OCR text or image."""


@dataclass
class ParsedCardFields:
    """Structured fields extracted by AI from OCR text."""
    card_name: Optional[str] = None
    hp: Optional[str] = None
    collector_number: Optional[str] = None
    rarity: Optional[str] = None
    artist: Optional[str] = None
    stage: Optional[str] = None
    energy_type: Optional[str] = None
    set_name: Optional[str] = None
    language: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


async def enhance_ocr(
    raw_text: str,
    card_image=None,
) -> Optional[ParsedCardFields]:
    """Use AI to extract structured fields from raw OCR text.

    Args:
        raw_text: Raw OCR text output.
        card_image: Optional numpy/PIL image of the card.

    Returns:
        ParsedCardFields or None if AI is disabled or fails.
    """
    if not settings.openrouter.enabled:
        return None

    user_msg = f"Here is the raw OCR text from a Pokemon card:\n\n{raw_text}\n\nExtract the structured card information as JSON."

    images = [card_image] if card_image is not None else None

    response = await openrouter.chat(
        system_prompt=SYSTEM_PROMPT,
        user_message=user_msg,
        images=images,
        temperature=0.1,
        max_tokens=500,
    )

    if not response:
        return None

    data = response.parse_json()
    if not data:
        return None

    logger.info("AI OCR enhancement extracted: %s", list(k for k, v in data.items() if v))

    return ParsedCardFields(
        card_name=data.get("card_name"),
        hp=data.get("hp"),
        collector_number=data.get("collector_number"),
        rarity=data.get("rarity"),
        artist=data.get("artist"),
        stage=data.get("stage"),
        energy_type=data.get("energy_type"),
        set_name=data.get("set_name"),
        language=data.get("language"),
    )
