"""workflow — 工作流序列化与恢复执行。

核心能力：
  1. WorkflowState — 工作流状态数据类（可 JSON 序列化）
  2. WorkflowSerializer — 序列化/反序列化工作流
  3. WorkflowResumer — 从检查点恢复执行
  4. 自动检查点 — 每 N 步自动保存
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any


# ── 工作流状态 ──

@dataclass
class WorkflowStep:
    """工作流中的一步。"""
    index: int
    description: str
    status: str = "pending"  # pending | running | completed | failed | skipped
    result: str = ""
    error: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    started_at: float = 0.0
    completed_at: float = 0.0


@dataclass
class WorkflowState:
    """完整的工作流状态（可 JSON 序列化）。"""
    id: str = ""
    title: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0
    status: str = "running"  # running | paused | completed | failed
    steps: list[WorkflowStep] = field(default_factory=list)
    current_step: int = 0
    session_id: str = ""
    config: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)

    # 检查点
    checkpoint_interval: int = 5  # 每 N 步保存一次
    checkpoint_dir: str = ".workflow_checkpoints"

    def __post_init__(self):
        if not self.id:
            self.id = str(uuid.uuid4())[:12]
        if not self.created_at:
            self.created_at = time.time()
        if not self.updated_at:
            self.updated_at = time.time()

    def to_dict(self) -> dict:
        """序列化为字典。"""
        return {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "status": self.status,
            "steps": [
                {
                    "index": s.index,
                    "description": s.description,
                    "status": s.status,
                    "result": s.result,
                    "error": s.error,
                    "tool_calls": s.tool_calls,
                    "started_at": s.started_at,
                    "completed_at": s.completed_at,
                }
                for s in self.steps
            ],
            "current_step": self.current_step,
            "session_id": self.session_id,
            "config": self.config,
            "metadata": self.metadata,
            "checkpoint_interval": self.checkpoint_interval,
            "checkpoint_dir": self.checkpoint_dir,
        }

    @classmethod
    def from_dict(cls, data: dict) -> WorkflowState:
        """从字典反序列化。"""
        steps = []
        for s in data.get("steps", []):
            steps.append(WorkflowStep(**s))

        return cls(
            id=data.get("id", ""),
            title=data.get("title", ""),
            created_at=data.get("created_at", 0.0),
            updated_at=data.get("updated_at", 0.0),
            status=data.get("status", "running"),
            steps=steps,
            current_step=data.get("current_step", 0),
            session_id=data.get("session_id", ""),
            config=data.get("config", {}),
            metadata=data.get("metadata", {}),
            checkpoint_interval=data.get("checkpoint_interval", 5),
            checkpoint_dir=data.get("checkpoint_dir", ".workflow_checkpoints"),
        )

    def save_checkpoint(self):
        """保存检查点到磁盘。"""
        checkpoint_dir = Path(self.checkpoint_dir)
        checkpoint_dir.mkdir(parents=True, exist_ok=True)

        filename = f"workflow_{self.id}_step_{self.current_step}.json"
        filepath = checkpoint_dir / filename

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

        # 清理旧检查点（只保留最近 5 个）
        self._cleanup_old_checkpoints()

    def _cleanup_old_checkpoints(self, keep: int = 5):
        """清理旧检查点。"""
        checkpoint_dir = Path(self.checkpoint_dir)
        if not checkpoint_dir.exists():
            return

        pattern = f"workflow_{self.id}_step_*.json"
        files = sorted(checkpoint_dir.glob(pattern), key=lambda f: f.stat().st_mtime)

        for f in files[:-keep]:
            f.unlink()

    def get_summary(self) -> str:
        """获取工作流摘要。"""
        total = len(self.steps)
        completed = sum(1 for s in self.steps if s.status == "completed")
        failed = sum(1 for s in self.steps if s.status == "failed")
        running = sum(1 for s in self.steps if s.status == "running")

        lines = [
            f"工作流: {self.title or '(未命名)'}",
            f"状态: {self.status}",
            f"进度: {completed}/{total} 完成 ({failed} 失败, {running} 运行中)",
            f"当前步骤: {self.current_step}",
            f"创建时间: {datetime.fromtimestamp(self.created_at).isoformat()}",
        ]

        if self.steps:
            lines.append("")
            lines.append("步骤列表:")
            for s in self.steps:
                icon = {"pending": "○", "running": "▶", "completed": "✓", "failed": "✗", "skipped": "−"}
                lines.append(f"  {icon.get(s.status, '?')} [{s.index}] {s.description}")

        return "\n".join(lines)


# ── 工作流序列化器 ──

class WorkflowSerializer:
    """工作流序列化/反序列化。"""

    @staticmethod
    def save(state: WorkflowState, filepath: str | Path) -> str:
        """保存工作流到文件。"""
        filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(state.to_dict(), f, ensure_ascii=False, indent=2)

        return str(filepath)

    @staticmethod
    def load(filepath: str | Path) -> WorkflowState:
        """从文件加载工作流。"""
        filepath = Path(filepath)
        if not filepath.exists():
            raise FileNotFoundError(f"工作流文件不存在: {filepath}")

        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        return WorkflowState.from_dict(data)

    @staticmethod
    def list_workflows(workflow_dir: str | Path = ".workflows") -> list[dict]:
        """列出所有工作流。"""
        workflow_dir = Path(workflow_dir)
        if not workflow_dir.exists():
            return []

        workflows = []
        for f in sorted(workflow_dir.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True):
            try:
                with open(f, "r", encoding="utf-8") as fp:
                    data = json.load(fp)
                workflows.append({
                    "id": data.get("id", ""),
                    "title": data.get("title", ""),
                    "status": data.get("status", ""),
                    "steps": len(data.get("steps", [])),
                    "current_step": data.get("current_step", 0),
                    "updated_at": data.get("updated_at", 0),
                    "file": str(f),
                })
            except Exception:
                continue

        return workflows


# ── 工作流恢复执行器 ──

class WorkflowResumer:
    """从检查点恢复工作流执行。"""

    def __init__(self, state: WorkflowState):
        self.state = state

    def get_next_step(self) -> WorkflowStep | None:
        """获取下一个待执行的步骤。"""
        for step in self.state.steps:
            if step.status == "pending":
                return step
        return None

    def get_failed_steps(self) -> list[WorkflowStep]:
        """获取所有失败的步骤。"""
        return [s for s in self.state.steps if s.status == "failed"]

    def get_remaining_steps(self) -> list[WorkflowStep]:
        """获取所有未完成的步骤。"""
        return [s for s in self.state.steps if s.status in ("pending", "failed")]

    def mark_step_running(self, index: int):
        """标记步骤为运行中。"""
        for step in self.state.steps:
            if step.index == index:
                step.status = "running"
                step.started_at = time.time()
                break
        self.state.current_step = index
        self.state.updated_at = time.time()

    def mark_step_completed(self, index: int, result: str = ""):
        """标记步骤为已完成。"""
        for step in self.state.steps:
            if step.index == index:
                step.status = "completed"
                step.result = result
                step.completed_at = time.time()
                break
        self.state.updated_at = time.time()

    def mark_step_failed(self, index: int, error: str = ""):
        """标记步骤为失败。"""
        for step in self.state.steps:
            if step.index == index:
                step.status = "failed"
                step.error = error
                step.completed_at = time.time()
                break
        self.state.updated_at = time.time()

    def mark_step_skipped(self, index: int):
        """标记步骤为跳过。"""
        for step in self.state.steps:
            if step.index == index:
                step.status = "skipped"
                step.completed_at = time.time()
                break
        self.state.updated_at = time.time()

    def is_complete(self) -> bool:
        """检查工作流是否完成。"""
        return all(s.status in ("completed", "skipped") for s in self.state.steps)

    def get_progress(self) -> dict:
        """获取进度信息。"""
        total = len(self.state.steps)
        completed = sum(1 for s in self.state.steps if s.status == "completed")
        failed = sum(1 for s in self.state.steps if s.status == "failed")
        running = sum(1 for s in self.state.steps if s.status == "running")

        return {
            "total": total,
            "completed": completed,
            "failed": failed,
            "running": running,
            "pending": total - completed - failed - running,
            "percent": (completed / total * 100) if total > 0 else 0,
            "status": self.state.status,
        }


# ── 工作流工具 ──

# 全局工作流存储
_active_workflows: dict[str, WorkflowState] = {}


def create_workflow(title: str, steps: list[str],
                    config: dict | None = None) -> WorkflowState:
    """创建工作流。"""
    state = WorkflowState(
        title=title,
        steps=[
            WorkflowStep(index=i, description=desc)
            for i, desc in enumerate(steps)
        ],
        config=config or {},
    )
    _active_workflows[state.id] = state
    return state


def get_workflow(workflow_id: str) -> WorkflowState | None:
    """获取工作流。"""
    return _active_workflows.get(workflow_id)


def list_workflows() -> list[dict]:
    """列出所有活跃工作流。"""
    return [
        {
            "id": w.id,
            "title": w.title,
            "status": w.status,
            "progress": f"{sum(1 for s in w.steps if s.status == 'completed')}/{len(w.steps)}",
        }
        for w in _active_workflows.values()
    ]
