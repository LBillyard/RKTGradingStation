"""OCR engine orchestrator: PaddleOCR primary, Tesseract fallback."""

import asyncio
import logging
from typing import Optional

import numpy as np

from .paddle_ocr import PaddleOCRWrapper, OCROutput
from .tesseract_ocr import TesseractWrapper
from .language import detect_language
from .parser import CardFieldParser, ParsedCardFields

logger = logging.getLogger(__name__)


class OCREngine:
    """Orchestrates OCR processing with primary and fallback engines."""

    def __init__(self):
        self._paddle = PaddleOCRWrapper()
        self._tesseract = TesseractWrapper()
        self._parser = CardFieldParser()

    async def recognize(self, image: np.ndarray, language_hint: str = None) -> OCROutput:
        """Run OCR on a card image. Uses PaddleOCR primary, Tesseract as fallback.

        Args:
            image: BGR numpy array of the card image
            language_hint: Optional language code hint (en, ja, ko, zh-cn, zh-tw)

        Returns:
            OCROutput with raw text, bounding boxes, and confidence
        """
        lang = language_hint or "en"

        # Step 1: Try PaddleOCR
        try:
            result = await self._paddle.recognize(image, lang)
            if result.confidence >= 0.5 and result.raw_text.strip():
                # Detect language from result if no hint was given
                if not language_hint:
                    detected = detect_language(result.raw_text)
                    if detected != lang:
                        logger.info(f"Language detected as {detected}, re-running OCR")
                        result = await self._paddle.recognize(image, detected)
                        result.language = detected
                logger.info(f"PaddleOCR success: {len(result.boxes)} text regions, confidence={result.confidence:.2f}")
                return result
            else:
                logger.info(f"PaddleOCR low confidence ({result.confidence:.2f}), trying Tesseract")
        except Exception as e:
            logger.warning(f"PaddleOCR failed: {e}, falling back to Tesseract")

        # Step 2: Fallback to Tesseract
        try:
            result = await self._tesseract.recognize(image, lang)
            if not language_hint:
                detected = detect_language(result.raw_text)
                result.language = detected
            logger.info(f"Tesseract result: {len(result.boxes)} text regions, confidence={result.confidence:.2f}")
            return result
        except Exception as e:
            logger.error(f"Both OCR engines failed: {e}")
            return OCROutput(
                raw_text="", boxes=[], confidence=0.0,
                language=lang, engine="none",
            )

    def parse_fields(self, ocr_result: OCROutput) -> ParsedCardFields:
        """Parse structured card fields from OCR output."""
        return self._parser.parse(ocr_result.raw_text, ocr_result.boxes)

    async def parse_fields_with_ai(self, ocr_result: OCROutput, card_image=None) -> ParsedCardFields:
        """Parse fields using AI enhancement, falling back to regex parser.

        Args:
            ocr_result: OCR output with raw text.
            card_image: Optional numpy/PIL image of the card.

        Returns:
            ParsedCardFields from AI or regex parser.
        """
        from app.services.ai.ocr_enhancer import enhance_ocr

        # Try AI enhancement first
        try:
            ai_fields = await enhance_ocr(ocr_result.raw_text, card_image)
            if ai_fields:
                # Merge AI fields with regex fields (AI takes priority where available)
                regex_fields = self._parser.parse(ocr_result.raw_text, ocr_result.boxes)
                return ParsedCardFields(
                    card_name=ai_fields.card_name or regex_fields.card_name,
                    hp=ai_fields.hp or regex_fields.hp,
                    collector_number=ai_fields.collector_number or regex_fields.collector_number,
                    rarity=ai_fields.rarity or regex_fields.rarity,
                    artist=ai_fields.artist or regex_fields.artist,
                    stage=ai_fields.stage or regex_fields.stage,
                    language=ai_fields.language,
                )
        except Exception as e:
            logger.warning("AI OCR enhancement failed, using regex parser: %s", e)

        return self._parser.parse(ocr_result.raw_text, ocr_result.boxes)
