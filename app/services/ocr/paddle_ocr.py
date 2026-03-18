"""PaddleOCR wrapper with language-specific model caching."""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# PaddleOCR language code mapping
PADDLE_LANG_MAP = {
    "en": "en",
    "ja": "japan",
    "ko": "korean",
    "zh-cn": "ch",
    "zh-tw": "chinese_cht",
}


@dataclass
class OCRBox:
    text: str
    confidence: float
    bbox: List[List[float]]  # [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]


@dataclass
class OCROutput:
    raw_text: str
    boxes: List[OCRBox]
    confidence: float
    language: str
    engine: str = "paddleocr"
    processing_time_ms: int = 0


class PaddleOCRWrapper:
    """Wrapper around PaddleOCR with lazy model loading and caching."""

    _instances: Dict[str, object] = {}

    def _get_instance(self, lang: str):
        paddle_lang = PADDLE_LANG_MAP.get(lang, "en")
        if paddle_lang not in self._instances:
            try:
                from paddleocr import PaddleOCR
                logger.info(f"Loading PaddleOCR model for language: {paddle_lang}")
                self._instances[paddle_lang] = PaddleOCR(
                    use_angle_cls=True,
                    lang=paddle_lang,
                    show_log=False,
                    use_gpu=False,
                )
                logger.info(f"PaddleOCR model loaded for: {paddle_lang}")
            except ImportError:
                logger.error("PaddleOCR not installed. Install with: pip install paddleocr paddlepaddle")
                raise
        return self._instances[paddle_lang]

    async def recognize(self, image: np.ndarray, lang: str = "en") -> OCROutput:
        """Run OCR on an image. Returns structured OCR output."""
        start = time.perf_counter()

        try:
            ocr = self._get_instance(lang)
            # Run in thread executor to avoid blocking async loop
            result = await asyncio.to_thread(ocr.ocr, image, cls=True)
        except Exception as e:
            logger.error(f"PaddleOCR recognition failed: {e}")
            return OCROutput(
                raw_text="", boxes=[], confidence=0.0,
                language=lang, engine="paddleocr",
                processing_time_ms=int((time.perf_counter() - start) * 1000),
            )

        boxes = []
        texts = []
        confidences = []

        if result and result[0]:
            for line in result[0]:
                bbox = line[0]
                text = line[1][0]
                conf = float(line[1][1])
                boxes.append(OCRBox(text=text, confidence=conf, bbox=bbox))
                texts.append(text)
                confidences.append(conf)

        avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
        processing_time = int((time.perf_counter() - start) * 1000)

        return OCROutput(
            raw_text="\n".join(texts),
            boxes=boxes,
            confidence=avg_conf,
            language=lang,
            engine="paddleocr",
            processing_time_ms=processing_time,
        )
