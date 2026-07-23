"""EventBus — async pub/sub for ForgeX event system.

Design:
  - Single EventBus instance per agent session (singleton via `get_event_bus()`)
  - Each SSE subscriber gets an independent asyncio.Queue
  - Publishers are non-blocking (put_nowait) — slow consumers drop events
  - Typed events via ForgeXEvent / EventKind hierarchy
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

from .protocol import ForgeXEvent, EventKind, ErrorEvent

_log = logging.getLogger("claudez.events")

# ── Module-level singleton ──

event_bus: EventBus | None = None
_lock = threading.Lock()


def get_event_bus() -> EventBus:
    """Get or create the global EventBus singleton."""
    global event_bus
    if event_bus is None:
        with _lock:
            if event_bus is None:
                event_bus = EventBus()
    return event_bus


def create_isolated_event_bus() -> EventBus:
    """Create a new isolated EventBus (for multi-tenant usage)."""
    return EventBus()


# ── EventBus ──

class EventBus:
    """Async pub/sub event bus.

    Subscribers register via subscribe() and receive events via async iterator.
    """

    def __init__(self, max_queue_size: int = 500):
        self._subscribers: list[asyncio.Queue] = []
        self._lock = threading.Lock()
        self._max_queue_size = max_queue_size
        self._closed = False

    def publish(self, event: ForgeXEvent) -> None:
        """Publish an event to all subscribers (non-blocking)."""
        if self._closed:
            return
        with self._lock:
            dead: list[asyncio.Queue] = []
            for q in self._subscribers:
                try:
                    q.put_nowait(event)
                except asyncio.QueueFull:
                    # Slow consumer — drop oldest event
                    try:
                        q.get_nowait()
                        q.put_nowait(event)
                    except (asyncio.QueueEmpty, asyncio.QueueFull):
                        pass
                except (RuntimeError, ValueError):
                    # Queue is closed or in bad state
                    dead.append(q)
            for q in dead:
                self._subscribers.remove(q)

    def subscribe(self) -> asyncio.Queue:
        """Register a new subscriber queue."""
        q: asyncio.Queue = asyncio.Queue(maxsize=self._max_queue_size)
        with self._lock:
            self._subscribers.append(q)
        _log.debug("event_bus subscriber added (total=%d)", len(self._subscribers))
        return q

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        """Remove a subscriber queue."""
        with self._lock:
            if queue in self._subscribers:
                self._subscribers.remove(queue)
                _log.debug("event_bus subscriber removed (total=%d)", len(self._subscribers))

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)

    def close(self) -> None:
        """Close the bus — no more events accepted."""
        self._closed = True
        with self._lock:
            self._subscribers.clear()

    def publish_tool_start(self, name: str, args: dict, task_id: str = "", trace_id: str = "") -> None:
        """Convenience: publish a tool started event."""
        from .protocol import ToolEvent, EventKind as EK
        self.publish(ToolEvent(
            kind=EK.TOOL_STARTED,
            tool_name=name,
            tool_args=args,
            task_id=task_id,
            trace_id=trace_id,
        ))

    def publish_tool_complete(
        self, name: str, duration_ms: float, success: bool,
        task_id: str = "", trace_id: str = "",
    ) -> None:
        """Convenience: publish a tool completed event."""
        from .protocol import ToolEvent
        self.publish(ToolEvent(
            kind=EventKind.TOOL_COMPLETED,
            tool_name=name,
            duration_ms=duration_ms,
            success=success,
            task_id=task_id,
            trace_id=trace_id,
        ))

    def publish_error(self, text: str, task_id: str = "", trace_id: str = "") -> None:
        """Convenience: publish an error event."""
        from .protocol import EventKind as EK
        self.publish(ErrorEvent(
            kind=EK.ERROR, error_text=text, task_id=task_id, trace_id=trace_id,
        ))
