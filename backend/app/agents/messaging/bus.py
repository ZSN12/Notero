"""In-memory event bus for inter-agent communication.

The bus is intentionally lightweight and process-local. For multi-worker Celery
deployments, persistent cross-process events are better handled through the
database (Task/AgentWorkflow state changes), but this bus is sufficient for:
- synchronously reacting to events within the same worker process;
- broadcasting in-process signals to registered handlers.
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from typing import Callable, Optional

from app.agents.messaging.events import AgentEvent

logger = logging.getLogger(__name__)

EventHandler = Callable[[AgentEvent], None]


class EventBus:
    """Simple pub/sub event bus for agent events."""

    def __init__(self):
        self._subscribers: dict[str, list[EventHandler]] = defaultdict(list)
        self._lock = threading.Lock()

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """Register a handler for a specific event type."""
        with self._lock:
            if handler not in self._subscribers[event_type]:
                self._subscribers[event_type].append(handler)
                logger.debug("event_bus_subscribe event_type=%s handler=%s", event_type, handler.__name__)

    def unsubscribe(self, event_type: str, handler: EventHandler) -> None:
        """Remove a handler for a specific event type."""
        with self._lock:
            handlers = self._subscribers.get(event_type, [])
            if handler in handlers:
                handlers.remove(handler)

    def publish(self, event: AgentEvent) -> None:
        """Publish an event synchronously to all subscribers."""
        handlers: list[EventHandler] = []
        with self._lock:
            handlers.extend(self._subscribers.get(event.event_type, []))
            # Wildcard subscribers receive every event.
            handlers.extend(self._subscribers.get("*", []))

        if not handlers:
            logger.debug("event_bus_no_handlers event_type=%s", event.event_type)
            return

        logger.info(
            "event_bus_publish event_type=%s session_id=%s role=%s handlers=%s",
            event.event_type,
            event.session_id,
            event.role,
            len(handlers),
        )

        for handler in handlers:
            try:
                handler(event)
            except Exception:
                logger.exception(
                    "event_bus_handler_failed event_type=%s handler=%s",
                    event.event_type,
                    getattr(handler, "__name__", repr(handler)),
                )

    def clear(self) -> None:
        """Remove all subscribers. Intended for tests."""
        with self._lock:
            self._subscribers.clear()


# Process-global event bus instance.
_default_bus: Optional[EventBus] = None
_bus_lock = threading.Lock()


def get_event_bus() -> EventBus:
    """Return the process-global event bus, creating it if necessary."""
    global _default_bus
    if _default_bus is None:
        with _bus_lock:
            if _default_bus is None:
                _default_bus = EventBus()
    return _default_bus
