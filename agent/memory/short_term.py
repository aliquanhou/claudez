"""memory/short_term — 短期记忆（会话内）。

存储当前会话的关键信息，如用户偏好、任务状态等。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ShortTermMemory:
    """短期记忆——当前会话的关键信息。"""
    facts: dict[str, str] = field(default_factory=dict)
    """关键事实 key→value"""
    tags: list[str] = field(default_factory=list)
    """当前会话标签"""
    task_stack: list[str] = field(default_factory=list)
    """任务栈"""
    notes: list[dict] = field(default_factory=list)
    """笔记列表"""

    def remember(self, key: str, value: str):
        """记住一个事实。"""
        self.facts[key] = value

    def recall(self, key: str, default: str = "") -> str:
        """回忆一个事实。"""
        return self.facts.get(key, default)

    def add_note(self, content: str, category: str = "general"):
        """添加笔记。"""
        self.notes.append({
            "content": content,
            "category": category,
            "timestamp": time.time(),
        })

    def get_notes(self, category: str = "", limit: int = 5) -> list[dict]:
        """获取笔记。"""
        if category:
            filtered = [n for n in self.notes if n["category"] == category]
        else:
            filtered = self.notes
        return filtered[-limit:]

    def push_task(self, task: str):
        """压入任务。"""
        self.task_stack.append(task)

    def pop_task(self) -> str:
        """弹出任务。"""
        return self.task_stack.pop() if self.task_stack else ""

    def clear(self):
        """清空短期记忆。"""
        self.facts.clear()
        self.tags.clear()
        self.task_stack.clear()
        self.notes.clear()
