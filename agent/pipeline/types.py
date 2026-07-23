"""Pipeline types — 流水线数据类。"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PipelinePhase(Enum):
    """流水线阶段枚举。"""
    PLANNING = "planning"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class PipelineTask:
    """单个流水线任务。"""
    id: str
    goal: str                        # 用户原始目标
    phase: PipelinePhase = PipelinePhase.PLANNING
    plan_text: str = ""              # Planner 输出的方案文本
    execution_result: str = ""       # Executor 输出
    verification_report: str = ""    # Verifier 输出
    verdict: str = ""                # PASS / PARTIAL / FAIL
    retry_count: int = 0             # 已重试次数
    max_retries: int = 3             # 最大重试次数
    created_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_done(self) -> bool:
        return self.phase in (PipelinePhase.COMPLETED, PipelinePhase.FAILED)

    @property
    def succeeded(self) -> bool:
        return self.phase == PipelinePhase.COMPLETED and self.verdict == "PASS"

    def brief(self) -> str:
        """简短状态摘要。"""
        return (
            f"[{self.phase.value.upper()}] "
            f"goal={self.goal[:60]} "
            f"verdict={self.verdict or '?'} "
            f"retry={self.retry_count}/{self.max_retries}"
        )


@dataclass
class PipelineResult:
    """流水线执行结果。"""
    success: bool
    task: PipelineTask
    phases_completed: list[PipelinePhase] = field(default_factory=list)
    total_duration_ms: float = 0.0
    message: str = ""
