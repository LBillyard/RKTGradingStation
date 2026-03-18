"""Tesseract OCR fallback wrapper."""

import asyncio
import logging
import time
from typing import Optional

import numpy as np

from .paddle_ocr import OCROutput, OCRBox

logger = logging.getLogger(__name__)

TESSERACT_LANG_MAP = {
    "en": "eng",
    "ja": "jpn",
    "ko": "kor",
    "zh-cn": "chi_sim",
    "zh-tw": "chi_tra",
}


class TesseractWrapper:
    """Wrapper around pytesseract for fallback OCR."""

    async def recognize(self, image: np.ndarray, lang: str = "en") -> OCROutput:
        """Run Tesseract OCR on an image."""
        start = time.perf_counter()

        try:
            import pytesseract
            from PIL import Image
            import cv2

            tess_lang = TESSERACT_LANG_MAP.get(lang, "eng")

            # Convert BGR to RGB for PIL
            rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(rgb)

            # Run in thread to avoid blocking
            data = await asyncio.to_thread(
                pytesseract.image_to_data,
                pil_img,
                lang=tess_lang,
                output_type=pytesseract.Output.DICT,
            )

            boxes = []
            texts = []
            confidences = []

            for i in range(len(data['text'])):
                text = data['text'][i].strip()
                conf = int(data['conf'][i])
                if text and conf > 0:
                    x, y, w, h = data['left'][i], data['top'][i], data['width'][i], data['height'][i]
                    bbox = [[x, y], [x+w, y], [x+w, y+h], [x, y+h]]
                    boxes.append(OCRBox(text=text, confidence=conf/100.0, bbox=bbox))
                    texts.append(text)
                    confidences.append(conf / 100.0)

            avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
            processing_time = int((time.perf_counter() - start) * 1000)

            return OCROutput(
                raw_text=" ".join(texts),
                boxes=boxes,
                confidence=avg_conf,
                language=lang,
                engine="tesseract",
                processing_time_ms=processing_time,
            )

        except ImportError:
            logger.error("pytesseract not installed")
            raise
        except Exception as e:
            logger.error(f"Tesseract OCR failed: {e}")
            return OCROutput(
                raw_text="", boxes=[], confidence=0.0,
                language=lang, engine="tesseract",
                processing_time_ms=int((time.perf_counter() - start) * 1000),
            )
