"""Webhook notification service."""

import asyncio
import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


async def send_webhook(event_type: str, payload: dict) -> bool:
    """Send a webhook notification if enabled and event type is subscribed."""
    if not settings.webhook.enabled or not settings.webhook.url:
        return False
    if event_type not in settings.webhook.events:
        return False

    body = json.dumps({
        "event": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": payload,
    }, default=str)

    headers = {"Content-Type": "application/json"}
    if settings.webhook.secret:
        sig = hmac.new(settings.webhook.secret.encode(), body.encode(), hashlib.sha256).hexdigest()
        headers["X-RKT-Signature"] = sig

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(settings.webhook.url, content=body, headers=headers)
            logger.info("Webhook sent: %s -> %d", event_type, resp.status_code)
            return resp.status_code < 400
    except Exception as e:
        logger.warning("Webhook failed for %s: %s", event_type, e)
        return False


def fire_webhook_background(event_type: str, payload: dict) -> None:
    """Fire webhook in background (non-blocking)."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(send_webhook(event_type, payload))
        else:
            loop.run_until_complete(send_webhook(event_type, payload))
    except RuntimeError:
        pass  # No event loop available
