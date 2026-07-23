"""Background Reviewer — 后台会话审查 Agent。

设计（Hermes 风格）：
  - 每 N 轮触发一次后台审查
  - 审查方向：是否偏离目标、是否有无关的文件修改、是否在绕圈子
  - 审查结果作为结构化"审查注释"注入系统提示
  - 审查是轻量的子 Agent 调用（max_tokens=500）
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

_log = logging.getLogger("claudez.self_evol")


@dataclass
class ReviewNote:
    """一条审查注释。"""
    message: str
    severity: str            # "info" | "warn" | "critical"
    category: str            # "goal" | "scope" | "quality" | "loop"
    timestamp: float = field(default_factory=time.time)

    def to_prompt_block(self) -> str:
        return f"[审查-{self.severity.upper()}] {self.message}"


class BackgroundReviewer:
    """后台会话审查器。

    用法:
        reviewer = BackgroundReviewer(review_interval=10)
        note = reviewer.check(round_num, goal, modified_files)
        if note:
            prompt += note.to_prompt_block()
    """

    def __init__(self, review_interval: int = 10):
        self.review_interval = review_interval
        self._last_review_round = 0

    def check(
        self,
        round_num: int,
        goal: str = "",
        modified_files: list[str] | None = None,
        tool_error_count: int = 0,
        session_messages_count: int = 0,
    ) -> ReviewNote | None:
        """检测是否需要触发审查。

        Returns:
            如果达到审查间隔，返回 ReviewNote；否则返回 None。
        """
        if round_num - self._last_review_round < self.review_interval:
            return None

        self._last_review_round = round_num
        note = self._analyze(goal, modified_files, tool_error_count, session_messages_count)
        _log.info("reviewer_triggered round=%d note=%s",
                  round_num, note.message[:80] if note else "none")
        return note

    def _analyze(
        self,
        goal: str,
        modified_files: list[str] | None,
        tool_error_count: int,
        session_messages_count: int,
    ) -> ReviewNote:
        """确定性分析当前会话状态，生成审查注释。"""
        modified_files = modified_files or []
        findings: list[str] = []

        # 1. 文件范围检查
        if len(modified_files) > 5:
            findings.append(
                f"已修改 {len(modified_files)} 个文件，确认是否都在目标范围内。"
            )

        # 2. 错误率检查
        if tool_error_count > 3:
            findings.append(
                f"出现 {tool_error_count} 次工具错误，建议检查环境或参数。"
            )

        # 3. 会话轮次检查
        if session_messages_count > 100:
            findings.append(
                "对话已超过 100 条消息，建议考虑是否完成了当前目标。"
            )

        # 4. 目标聚焦检查
        if goal:
            relevant_files = sum(
                1 for f in modified_files if any(
                    kw in f.lower() for kw in goal.lower().split()
                )
            )
            total = len(modified_files)
            if total > 0 and relevant_files < total * 0.3:
                findings.append(
                    f"只有 {relevant_files}/{total} 的修改文件与目标关键词相关。"
                    "请确认没有偏离原始目标。"
                )

        if not findings:
            return ReviewNote(
                message="审查通过，会话状态良好，方向正确。",
                severity="info",
                category="quality",
            )

        message = "审查发现: " + " ".join(findings)
        severity = "critical" if tool_error_count > 5 else "warn"
        return ReviewNote(
            message=message,
            severity=severity,
            category="goal",
        )
