"""Card field parser: extract structured fields from raw OCR text."""

import logging
import re
from dataclasses import dataclass
from typing import Optional, List

logger = logging.getLogger(__name__)


@dataclass
class ParsedCardFields:
    card_name: Optional[str] = None
    hp: Optional[str] = None
    collector_number: Optional[str] = None
    set_total: Optional[str] = None
    rarity: Optional[str] = None
    artist: Optional[str] = None
    energy_type: Optional[str] = None
    stage: Optional[str] = None
    evolves_from: Optional[str] = None
    attacks: List[str] = None
    weakness: Optional[str] = None
    resistance: Optional[str] = None
    retreat_cost: Optional[int] = None
    language: Optional[str] = None

    def __post_init__(self):
        if self.attacks is None:
            self.attacks = []


class CardFieldParser:
    """Extract structured card fields from raw OCR text."""

    # Known Pokemon rarities
    RARITIES = {"Common", "Uncommon", "Rare", "Holo Rare", "Ultra Rare", "Secret Rare",
                "Rare Holo", "Rare Holo EX", "Rare Holo GX", "Rare Holo V", "Rare VMAX",
                "Promo", "Amazing Rare", "Illustration Rare", "Special Art Rare"}

    # Energy types
    ENERGY_TYPES = {"Fire", "Water", "Grass", "Lightning", "Psychic", "Fighting",
                    "Darkness", "Metal", "Fairy", "Dragon", "Colorless", "Normal"}

    # Stages
    STAGES = {"Basic", "Stage 1", "Stage 2", "MEGA", "BREAK", "VMAX", "VSTAR", "ex", "EX", "GX", "V"}

    def parse(self, raw_text: str, boxes=None) -> ParsedCardFields:
        """Parse raw OCR text into structured card fields."""
        fields = ParsedCardFields()

        if not raw_text:
            return fields

        lines = raw_text.strip().split("\n")
        full_text = raw_text

        fields.card_name = self._extract_name(lines)
        fields.hp = self._extract_hp(full_text)
        fields.collector_number, fields.set_total = self._extract_collector_number(full_text)
        fields.rarity = self._extract_rarity(full_text)
        fields.artist = self._extract_artist(full_text)
        fields.stage = self._extract_stage(full_text)

        return fields

    def _extract_name(self, lines: List[str]) -> Optional[str]:
        """Extract card name - typically the first significant line."""
        for line in lines[:3]:  # Check first 3 lines
            clean = line.strip()
            # Skip very short lines, lines that are just numbers, or HP lines
            if len(clean) < 2:
                continue
            if re.match(r'^\d+$', clean):
                continue
            if re.match(r'^\d+\s*HP$', clean, re.IGNORECASE):
                continue
            if clean.lower() in ('basic', 'stage 1', 'stage 2'):
                continue
            # Remove trailing HP notation
            name = re.sub(r'\s*\d+\s*HP\s*$', '', clean, flags=re.IGNORECASE).strip()
            if name:
                return name
        return None

    def _extract_hp(self, text: str) -> Optional[str]:
        """Extract HP value."""
        match = re.search(r'(\d{2,3})\s*HP', text, re.IGNORECASE)
        if match:
            return match.group(1)
        return None

    def _extract_collector_number(self, text: str):
        """Extract collector number like '4/102' or '001/165'."""
        match = re.search(r'(\d{1,3})\s*/\s*(\d{1,3})', text)
        if match:
            return match.group(1), match.group(2)
        # Also try standalone numbers near bottom of card
        match = re.search(r'#?(\d{1,3})(?:\s|$)', text)
        if match:
            return match.group(1), None
        return None, None

    def _extract_rarity(self, text: str) -> Optional[str]:
        """Extract rarity indicator."""
        text_lower = text.lower()
        for rarity in self.RARITIES:
            if rarity.lower() in text_lower:
                return rarity
        return None

    def _extract_artist(self, text: str) -> Optional[str]:
        """Extract artist name."""
        match = re.search(r'(?:Illus\.?|Illustration[:\s])\s*(.+?)(?:\n|$)', text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return None

    def _extract_stage(self, text: str) -> Optional[str]:
        """Extract card stage."""
        for stage in self.STAGES:
            if stage.lower() in text.lower():
                return stage
        if re.search(r'\bbasic\b', text, re.IGNORECASE):
            return "Basic"
        return None
