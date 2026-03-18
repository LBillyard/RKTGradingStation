"""Language detection from card images and OCR text."""

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# Unicode ranges for CJK detection
CJK_RANGES = [
    (0x4E00, 0x9FFF),   # CJK Unified Ideographs
    (0x3400, 0x4DBF),   # CJK Extension A
    (0x20000, 0x2A6DF), # CJK Extension B
    (0xF900, 0xFAFF),   # CJK Compatibility Ideographs
]

HIRAGANA_RANGE = (0x3040, 0x309F)
KATAKANA_RANGE = (0x30A0, 0x30FF)
HANGUL_RANGE = (0xAC00, 0xD7AF)
HANGUL_JAMO = (0x1100, 0x11FF)


def detect_language(text: str) -> str:
    """Detect language from OCR text based on character analysis.

    Returns language code: en, ja, ko, zh-cn, zh-tw
    """
    if not text:
        return "en"

    chars = list(text.replace(" ", "").replace("\n", ""))
    if not chars:
        return "en"

    total = len(chars)
    jp_count = 0
    kr_count = 0
    cjk_count = 0
    latin_count = 0

    for ch in chars:
        cp = ord(ch)

        if HIRAGANA_RANGE[0] <= cp <= HIRAGANA_RANGE[1] or KATAKANA_RANGE[0] <= cp <= KATAKANA_RANGE[1]:
            jp_count += 1
        elif HANGUL_RANGE[0] <= cp <= HANGUL_RANGE[1] or HANGUL_JAMO[0] <= cp <= HANGUL_JAMO[1]:
            kr_count += 1
        elif any(start <= cp <= end for start, end in CJK_RANGES):
            cjk_count += 1
        elif cp < 128:
            latin_count += 1

    # Decision logic
    if jp_count > 0:
        return "ja"
    if kr_count > 0:
        return "ko"
    if cjk_count > total * 0.1:
        # Chinese but which variant? Default to simplified
        return "zh-cn"

    return "en"


def detect_language_from_image(image) -> str:
    """Detect likely language from visual features of the card.

    This is a placeholder for future visual language detection.
    Currently returns 'en' as default.
    """
    # TODO: Add visual feature analysis (e.g., character density, font style)
    return "en"
