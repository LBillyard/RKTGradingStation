"""Simple publish-subscribe event bus for inter-service communication."""

import logging
import threading
from collections import defaultdict
from typing import Any, Callable

logger = logging.getLogger(__name__)


class Events:
    """Event type constants."""
    SCAN_STARTED = "scan.started"
    SCAN_COMPLETED = "scan.completed"
    SCAN_FAILED = "scan.failed"
    IMAGE_PROCESSED = "image.processed"
    OCR_COMPLETED = "ocr.completed"
    OCR_FAILED = "ocr.failed"
    CARD_IDENTIFIED = "card.identified"
    CARD_ID_FAILED = "card.id_failed"
    GRADE_CALCULATED = "grade.calculated"
    GRADE_APPROVED = "grade.approved"
    GRADE_OVERRIDDEN = "grade.overridden"
    AUTH_COMPLETED = "auth.completed"
    AUTH_FLAGGED = "auth.flagged"
    SETTINGS_CHANGED = "settings.changed"
    PRINT_STARTED = "print.started"
    PRINT_COMPLETED = "print.completed"
    PRINT_FAILED = "print.failed"
    NFC_PROGRAMMED = "nfc.programmed"
    NFC_FAILED = "nfc.failed"
    SLAB_ASSEMBLY_STARTED = "slab.assembly_started"
    SLAB_ASSEMBLY_COMPLETED = "slab.assembly_completed"


class EventBus:
    """Simple in-process event bus."""

    def __init__(self):
        self._handlers: dict[str, list[Callable]] = defaultdict(list)
        self._lock = threading.Lock()

    def subscribe(self, event_type: str, handler: Callable) -> None:
        """Register a handler for an event type."""
        with self._lock:
            self._handlers[event_type].append(handler)
        logger.debug(f"Subscribed {handler.__name__} to {event_type}")

    def unsubscribe(self, event_type: str, handler: Callable) -> None:
        """Remove a handler for an event type."""
        with self._lock:
            if handler in self._handlers[event_type]:
                self._handlers[event_type].remove(handler)

    def publish(self, event_type: str, data: Any = None) -> None:
        """Publish an event to all registered handlers."""
        with self._lock:
            handlers = list(self._handlers.get(event_type, []))
        for handler in handlers:
            try:
                handler(data)
            except Exception as e:
                logger.error(f"Event handler {handler.__name__} failed for {event_type}: {e}")


# Singleton event bus
event_bus = EventBus()
