"""session — 会话管理。

文档对齐：对话状态管理 + 磁盘持久化

功能：
  - 对话历史管理
  - 上下文窗口控制
  - 运行时状态追踪
  - 自适应反馈
  - 磁盘持久化（JSON 序列化）
"""

from __future__ import annotations

import json
import os
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


# ── 会话目录 ──

def get_sessions_dir():
    """获取会话存储目录。"""
    base = os.environ.get("CLAUDEZ_SESSIONS_DIR", "")
    if not base:
        home = os.environ.get("HOME") or os.environ.get("USERPROFILE") or "."
        base = os.path.join(home, ".claudez", "sessions")
    os.makedirs(base, exist_ok=True)
    return base


# ── 会话数据类 ──

@dataclass
class Session:
    """一个对话会话。"""
    id: str = ""
    """会话 ID"""
    created_at: float = 0.0
    """创建时间戳"""
    messages: list[dict] = field(default_factory=list)
    """消息历史"""
    config: dict = field(default_factory=dict)
    """会话配置"""
    state: dict = field(default_factory=dict)
    """运行时状态"""

    # 状态追踪
    turn_count: int = 0
    tool_call_count: int = 0
    tool_error_count: int = 0
    repeated_tools: list[str] = field(default_factory=list)
    start_time: float = 0.0

    # 持久化
    _dirty: bool = False
    _session_dir: str = ""

    def __post_init__(self):
        if not self.id:
            self.id = str(uuid.uuid4())[:8]
        if not self.created_at:
            self.created_at = time.time()
        if not self.start_time:
            self.start_time = time.time()

    # ── 消息管理 ──

    def add_message(self, role: str, content: str):
        """添加消息到历史。"""
        self.messages.append({
            "role": role,
            "content": content,
            "timestamp": time.time(),
        })
        if role == "user":
            self.turn_count += 1
        self._dirty = True
        self._auto_save()

    def add_tool_call(self, name: str, args: dict, result: str, call_id: str = ""):
        """记录工具调用（OpenAI 兼容格式）。

        Args:
            call_id: LLM 返回的真实 tool_call_id（空则自动生成）
        """
        self.tool_call_count += 1
        if not call_id:
            call_id = f"call_{uuid.uuid4().hex[:12]}"
        self.messages.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": call_id,
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(args, ensure_ascii=False),
                },
            }],
            "timestamp": time.time(),
        })
        self.messages.append({
            "role": "tool",
            "tool_call_id": call_id,
            "content": str(result),
            "timestamp": time.time(),
        })
        self._dirty = True
        self._auto_save()

    def record_tool_error(self, name: str):
        """记录工具错误。"""
        self.tool_error_count += 1
        self.repeated_tools.append(name)
        # 只保留最近 10 条
        if len(self.repeated_tools) > 10:
            self.repeated_tools = self.repeated_tools[-10:]

    def get_recent_messages(self, max_count: int = 50) -> list[dict]:
        """获取最近的消息（用于 LLM 上下文）。"""
        return self.messages[-max_count:]

    def get_state(self) -> dict:
        """获取会话状态快照（用于动态提示词）。"""
        return {
            "turn_count": self.turn_count,
            "tool_call_count": self.tool_call_count,
            "tool_error_count": self.tool_error_count,
            "repeated_tools": self._detect_repeated_tools(),
            "elapsed_seconds": time.time() - self.start_time,
        }

    def _detect_repeated_tools(self) -> list[str]:
        """检测最近重复调用的工具。"""
        if len(self.repeated_tools) < 3:
            return []
        recent = self.repeated_tools[-5:]
        return [t for t, c in Counter(recent).items() if c >= 2]

    def elapsed(self) -> float:
        """会话已运行时间（秒）。"""
        return time.time() - self.start_time

    # ── 序列化 ──

    def to_dict(self) -> dict:
        """序列化为字典。"""
        return {
            "id": self.id,
            "created_at": self.created_at,
            "messages": self.messages,
            "config": self.config,
            "state": self.state,
            "turn_count": self.turn_count,
            "tool_call_count": self.tool_call_count,
            "tool_error_count": self.tool_error_count,
            "repeated_tools": self.repeated_tools,
            "start_time": self.start_time,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Session:
        """从字典恢复。"""
        return cls(
            id=data.get("id", ""),
            created_at=data.get("created_at", 0.0),
            messages=data.get("messages", []),
            config=data.get("config", {}),
            state=data.get("state", {}),
            turn_count=data.get("turn_count", 0),
            tool_call_count=data.get("tool_call_count", 0),
            tool_error_count=data.get("tool_error_count", 0),
            repeated_tools=data.get("repeated_tools", []),
            start_time=data.get("start_time", time.time()),
        )

    # ── 磁盘持久化 ──

    def enable_persistence(self, session_dir: str = ""):
        """启用磁盘持久化。"""
        self._session_dir = session_dir or get_sessions_dir()
        self._dirty = True
        self.save()

    def save(self):
        """保存会话到磁盘。"""
        if not self._session_dir:
            return

        path = Path(self._session_dir) / f"{self.id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

        self._dirty = False

    @classmethod
    def load(cls, session_id: str, session_dir: str = "") -> Session | None:
        """从磁盘加载会话。"""
        base = session_dir or get_sessions_dir()
        path = Path(base) / f"{session_id}.json"
        if not path.exists():
            return None

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            session = cls.from_dict(data)
            session._session_dir = base
            return session
        except Exception:
            return None

    @classmethod
    def list_sessions(cls, session_dir: str = "") -> list[dict]:
        """列出所有已保存的会话。"""
        base = session_dir or get_sessions_dir()
        path = Path(base)
        if not path.exists():
            return []

        sessions = []
        for f in sorted(path.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True):
            try:
                with open(f, "r", encoding="utf-8") as fp:
                    data = json.load(fp)
                sessions.append({
                    "id": data.get("id", ""),
                    "created_at": data.get("created_at", 0),
                    "turn_count": data.get("turn_count", 0),
                    "tool_call_count": data.get("tool_call_count", 0),
                    "file": str(f),
                })
            except Exception:
                continue

        return sessions

    def _auto_save(self):
        """自动保存（每 5 条消息）。"""
        if self._session_dir and len(self.messages) % 5 == 0:
            self.save()


# ── 全局会话管理 ──

_current_session: Session | None = None


def get_session() -> Session:
    """获取当前会话。"""
    global _current_session
    if _current_session is None:
        _current_session = Session()
        # 默认启用持久化
        try:
            _current_session.enable_persistence()
        except Exception:
            pass
    return _current_session


def reset_session():
    """重置会话。"""
    global _current_session
    _current_session = Session()
    try:
        _current_session.enable_persistence()
    except Exception:
        pass


def create_isolated_session() -> Session:
    """创建一个隔离的会话（不修改全局单例，供子 Agent 使用）。"""
    session = Session()
    return session
