"""Event protocol types for ForgeX EventBus."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class EventKind(Enum):
    """Event type taxonomy for the ForgeX event system."""
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    USER_MESSAGE = "user_message"
    ASSISTANT_THOUGHT = "assistant_thought"
    ASSISTANT_TEXT = "assistant_text"
    TOOL_STARTED = "tool_started"
    TOOL_COMPLETED = "tool_completed"
    TOOL_OUTPUT = "tool_output"
    TOOL_ERROR = "tool_error"
    PIPELINE_PHASE = "pipeline_phase"
    RETRY_COUNT = "retry_count"
    NUDGE_INJECTED = "nudge_injected"
    CONTEXT_COMPRESSED = "context_compressed"
    MEMORY_STORED = "memory_stored"
    ERROR = "error"
    STATUS = "status"
    DONE = "done"


@dataclass
class ForgeXEvent:
    """Base event type — all events carry type, timestamp, trace_id, and optional task_id."""
    kind: EventKind
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    trace_id: str = ""  # v2.0: 全局链路追踪 ID
    task_id: str = ""

    def serialize(self) -> str:
        """Serialize to JSON string for SSE transmission."""
        data = {
            "type": self.kind.value,
            "data": self.payload,
            "ts": round(self.timestamp, 3),
        }
        if self.trace_id:
            data["trace_id"] = self.trace_id
        if self.task_id:
            data["task_id"] = self.task_id
        return json.dumps(data, ensure_ascii=False)


@dataclass
class ToolEvent(ForgeXEvent):
    """Tool start/completion event."""
    tool_name: str = ""
    tool_args: dict = field(default_factory=dict)
    duration_ms: float = 0.0
    success: bool = True

    def __post_init__(self):
        if self.kind == EventKind.TOOL_STARTED:
            self.payload = {"name": self.tool_name, "args": self.tool_args}
        elif self.kind == EventKind.TOOL_COMPLETED:
            self.payload = {
                "name": self.tool_name,
                "duration_ms": self.duration_ms,
                "success": self.success,
            }


@dataclass
class TokenEvent(ForgeXEvent):
    """Streaming token event."""
    token: str = ""

    def __post_init__(self):
        self.payload = {"token": self.token}


@dataclass
class ThoughtEvent(ForgeXEvent):
    """Agent thought/thinking event."""
    text: str = ""

    def __post_init__(self):
        self.kind = EventKind.ASSISTANT_THOUGHT
        self.payload = {"text": self.text}


@dataclass
class StatusEvent(ForgeXEvent):
    """Status update event."""
    status: str = ""

    def __post_init__(self):
        self.kind = EventKind.STATUS
        self.payload = {"status": self.status}


@dataclass
class DoneEvent(ForgeXEvent):
    """Session done event."""
    final_text: str = ""

    def __post_init__(self):
        self.kind = EventKind.DONE
        self.payload = {"text": self.final_text}


@dataclass
class ErrorEvent(ForgeXEvent):
    """Error event."""
    error_text: str = ""

    def __post_init__(self):
        self.kind = EventKind.ERROR
        self.payload = {"text": self.error_text}
