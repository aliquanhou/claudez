"""Task Context — 跨轮次任务上下文，让 Agent 永远知道自己正在完成什么。

v0.3.4 基石模块，无外部依赖。
定义 6 个数据类 + TaskManager 管理器。
"""

from __future__ import annotations

import uuid
import time
from dataclasses import dataclass, field
from typing import Any
from enum import Enum


class TaskPhase(Enum):
    """任务阶段枚举。"""
    INTENT_CLARIFY = "intent_clarify"
    ANALYSIS = "analysis"
    PLANNING = "planning"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    DONE = "done"


@dataclass
class Decision:
    """一个已做出的决策。"""
    decision_id: str
    timestamp: float
    description: str
    rationale: str | None = None
    alternatives: list[str] = field(default_factory=list)


@dataclass
class Phase:
    """一个任务阶段的时间区间。"""
    phase: TaskPhase
    entered_at: float
    completed_at: float | None = None
    notes: list[str] = field(default_factory=list)


@dataclass
class WorkspaceSnapshot:
    """工作区快照。"""
    root_path: str
    files: list[str] = field(default_factory=list)
    file_count: int = 0
    project_type: str | None = None
    key_files: list[str] = field(default_factory=list)


@dataclass
class TaskContext:
    """任务上下文 — 跨轮次持续绑定。

    记录用户目标、当前阶段、决策历史、文件变更等。
    """
    task_id: str
    created_at: float
    user_goal: str
    current_phase: TaskPhase
    phases: list[Phase] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)
    modified_files: list[str] = field(default_factory=list)
    turn_count: int = 0
    workspace: WorkspaceSnapshot | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class IntentData:
    """从用户行为中解析出的意图数据。"""
    primary_intent: str | None = None
    confidence: float = 0.0
    narrative: str = ""
    urgency: float = 0.0


class TaskManager:
    """多任务管理器 — 维护多个任务并在它们之间切换焦点。"""

    def __init__(self) -> None:
        self.tasks: dict[str, TaskContext] = {}
        self.current_task_id: str | None = None

    def create_task(self, user_goal: str) -> TaskContext:
        """创建一个新任务并设为当前焦点。"""
        now = time.time()
        task = TaskContext(
            task_id=str(uuid.uuid4()),
            created_at=now,
            user_goal=user_goal,
            current_phase=TaskPhase.INTENT_CLARIFY,
            turn_count=0,
            phases=[Phase(phase=TaskPhase.INTENT_CLARIFY, entered_at=now)],
        )
        self.tasks[task.task_id] = task
        self.current_task_id = task.task_id
        return task

    def get_current_task(self) -> TaskContext | None:
        """获取当前焦点任务。"""
        if self.current_task_id and self.current_task_id in self.tasks:
            return self.tasks[self.current_task_id]
        return None

    def add_decision(
        self, task_id: str, description: str, rationale: str | None = None,
    ) -> None:
        """向指定任务追加一条决策。"""
        task = self.tasks.get(task_id)
        if task:
            task.decisions.append(Decision(
                decision_id=str(uuid.uuid4()),
                timestamp=time.time(),
                description=description,
                rationale=rationale,
            ))

    def transition_phase(self, task_id: str, new_phase: TaskPhase) -> None:
        """将任务切换到新阶段，自动关闭当前阶段。"""
        task = self.tasks.get(task_id)
        if not task:
            return
        # 关闭当前阶段
        if task.phases:
            task.phases[-1].completed_at = time.time()
        # 开启新阶段
        task.phases.append(Phase(
            phase=new_phase,
            entered_at=time.time(),
        ))
        task.current_phase = new_phase

    def get_summary(self) -> str:
        """获取当前任务的人类可读摘要。"""
        task = self.get_current_task()
        if not task:
            return "No active task."
        lines = [
            f"Task: {task.user_goal[:100]}",
            f"Phase: {task.current_phase.value}",
            f"Decisions: {len(task.decisions)}",
            f"Files modified: {len(task.modified_files)}",
            f"Turn count: {task.turn_count}",
        ]
        return "\n".join(lines)
