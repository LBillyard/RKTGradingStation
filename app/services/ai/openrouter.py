"""OpenRouter API client for AI-powered card analysis.

Uses the OpenAI-compatible chat completions API at https://openrouter.ai/api/v1
with vision model support for card image analysis.
"""

import base64
import io
import json
import logging
from dataclasses import dataclass
from typing import Optional

import httpx
import numpy as np
from PIL import Image

from app.config import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://openrouter.ai/api/v1"


@dataclass
class AIResponse:
    """Response from an AI model call."""
    content: str
    model: str
    token_usage: dict
    finish_reason: str

    def parse_json(self) -> Optional[dict]:
        """Try to parse the content as JSON."""
        text = self.content.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Failed to parse AI response as JSON: %s", text[:200])
            return None


def _encode_image(image, max_dim: int = 1024) -> str:
    """Convert a numpy BGR image or PIL Image to base64 JPEG string."""
    if isinstance(image, np.ndarray):
        # BGR numpy → PIL RGB
        from PIL import Image as PILImage
        if len(image.shape) == 3 and image.shape[2] == 3:
            rgb = image[:, :, ::-1]
        else:
            rgb = image
        pil_img = PILImage.fromarray(rgb)
    elif isinstance(image, Image.Image):
        pil_img = image
    else:
        raise TypeError(f"Unsupported image type: {type(image)}")

    # Resize if too large
    w, h = pil_img.size
    if max(w, h) > max_dim:
        scale = max_dim / max(w, h)
        pil_img = pil_img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

    buf = io.BytesIO()
    pil_img.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


async def chat(
    system_prompt: str,
    user_message: str,
    images: Optional[list] = None,
    temperature: float = 0.1,
    max_tokens: int = 2000,
) -> Optional[AIResponse]:
    """Send a chat completion request to OpenRouter.

    Args:
        system_prompt: System message for the model.
        user_message: User message text.
        images: Optional list of numpy/PIL images to include.
        temperature: Model temperature (lower = more deterministic).
        max_tokens: Maximum response tokens.

    Returns:
        AIResponse or None if the request fails.
    """
    if not settings.openrouter.enabled:
        return None

    api_key = settings.openrouter.api_key
    if not api_key:
        logger.warning("OpenRouter API key not configured")
        return None

    # Build user content
    content_parts = []
    if images:
        for img in images:
            try:
                b64 = _encode_image(img)
                content_parts.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                })
            except Exception as e:
                logger.warning("Failed to encode image: %s", e)
    content_parts.append({"type": "text", "text": user_message})

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": content_parts},
    ]

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://rktgrading.com",
        "X-Title": "RKT Grading Station",
    }

    payload = {
        "model": settings.openrouter.model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        choice = data["choices"][0]
        usage = data.get("usage", {})

        return AIResponse(
            content=choice["message"]["content"],
            model=data.get("model", settings.openrouter.model),
            token_usage={
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            },
            finish_reason=choice.get("finish_reason", "unknown"),
        )
    except httpx.HTTPStatusError as e:
        logger.error("OpenRouter API error %s: %s", e.response.status_code, e.response.text[:300])
        return None
    except Exception as e:
        logger.error("OpenRouter request failed: %s", e)
        return None
