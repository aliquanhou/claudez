"""Nudge Engine — 确定性规则驱动的行为优化提示生成。

设计：
  - 0 LLM 依赖，纯规则引擎
  - 检测重复错误、token 冲击、工具循环、长时间运行
  - 生成优先级权重，每次只注入 Top-2
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

_log = logging.getLogger("claudez.self_evol")


@dataclass
class Nudge:
    """一条行为优化提示。"""
    key: str                          # 唯一标识（去重用）
    message: str                      # 注入到系统提示的文本
    priority: int                     # 0-10，越高越优先
    category: str                     # "error" | "token" | "loop" | "time"
    created_at: float = field(default_factory=time.time)
    expires_at: float = 0.0           # 过期时间戳（0 = 不自动过期）

    def is_expired(self) -> bool:
        return self.expires_at > 0 and time.time() > self.expires_at

    def to_prompt_block(self) -> str:
        return f"[NUDGE] {self.message}"


class NudgeEngine:
    """Nudge 引擎 — 每次分析一轮状态，产出优先级最高的 Nudge。

    检测规则：
      1. 连续相同工具错误 → nudge 建议检查工具参数/环境
      2. token 用量 > 70% → nudge 建议总结或完成
      3. 5 轮内无文件修改 → nudge 提示是否偏离目标
      4. 执行时间 > 5 分钟 → nudge 建议分步或拆分
      5. 同一工具调用超过 10 次 → nudge 考虑批量处理
    """

    # 阈值配置
    SAME_TOOL_ERROR_THRESHOLD = 3
    TOKEN_USAGE_HIGH_RATIO = 0.70
    IDLE_FILE_ROUNDS = 5
    LONG_RUN_SECONDS = 300
    TOOL_CALL_REPEAT_THRESHOLD = 10

    def __init__(self):
        self._active_nudges: dict[str, Nudge] = {}
        self._tool_error_counter: dict[str, int] = {}
        self._tool_call_counter: dict[str, int] = {}
        self._rounds_without_file_change = 0

    def analyze(
        self,
        stats: dict[str, Any],
        tool_errors: list[str],
        tool_calls: list[str],
        file_changes_count: int,
        elapsed_seconds: float,
    ) -> list[Nudge]:
        """分析当前状态，返回本轮应注入的 Nudge 列表。

        Args:
            stats: Agent.stats 字典
            tool_errors: 本轮出现的工具错误列表
            tool_calls: 本轮调用的工具名称列表
            file_changes_count: 本轮文件修改数
            elapsed_seconds: 当前会话已运行秒数

        Returns:
            按优先级排序的 Nudge 列表（最多 2 条）
        """
        new_nudges: list[Nudge] = []

        # ── 规则 1: 连续相同工具错误 ──
        for name in tool_errors:
            self._tool_error_counter[name] = self._tool_error_counter.get(name, 0) + 1
        for name, count in self._tool_error_counter.items():
            if count >= self.SAME_TOOL_ERROR_THRESHOLD:
                new_nudges.append(Nudge(
                    key=f"tool_error_{name}",
                    message=f"工具 {name} 连续失败 {count} 次。建议检查参数格式、目标路径或环境依赖。",
                    priority=9,
                    category="error",
                    expires_at=time.time() + 120,
                ))

        # ── 规则 2: 工具调用重复 ──
        for name in tool_calls:
            self._tool_call_counter[name] = self._tool_call_counter.get(name, 0) + 1
        for name, count in self._tool_call_counter.items():
            if count >= self.TOOL_CALL_REPEAT_THRESHOLD:
                new_nudges.append(Nudge(
                    key=f"tool_repeat_{name}",
                    message=f"{name} 已调用 {count} 次。如果读取同一个文件多次，请保存结果到变量。",
                    priority=6,
                    category="loop",
                ))

        # ── 规则 3: token 用量过高 ──
        total_tokens = stats.get("total_tokens", 0)
        max_tokens = stats.get("max_context_tokens", 32000) or 32000
        if max_tokens > 0 and total_tokens / max_tokens >= self.TOKEN_USAGE_HIGH_RATIO:
            new_nudges.append(Nudge(
                key="token_high",
                message=f"上下文使用率 {total_tokens}/{max_tokens} ({total_tokens/max_tokens:.0%})。"
                        f"建议在完成当前任务后请求新对话以释放上下文空间。",
                priority=7,
                category="token",
            ))

        # ── 规则 4: 长时间运行 ──
        if elapsed_seconds > self.LONG_RUN_SECONDS:
            new_nudges.append(Nudge(
                key="long_run",
                message=f"会话已运行 {elapsed_seconds/60:.0f} 分钟。复杂任务建议拆分为子步骤。",
                priority=5,
                category="time",
            ))

        # ── 规则 5: 多轮无文件修改 ──
        if file_changes_count > 0:
            self._rounds_without_file_change = 0
        else:
            self._rounds_without_file_change += 1
        if self._rounds_without_file_change >= self.IDLE_FILE_ROUNDS:
            new_nudges.append(Nudge(
                key="idle_no_file_change",
                message=f"已连续 {self._rounds_without_file_change} 轮无文件修改。确认当前方向是否正确。",
                priority=5,
                category="loop",
                expires_at=time.time() + 180,
            ))

        # ── 合并：更新活跃 Nudge，移除过期的 ──
        self._active_nudges = {
            k: v for k, v in self._active_nudges.items() if not v.is_expired()
        }
        for n in new_nudges:
            self._active_nudges[n.key] = n

        # ── 返回 Top-2 ──
        sorted_nudges = sorted(
            self._active_nudges.values(),
            key=lambda x: x.priority,
            reverse=True,
        )
        _log.debug("nudge_analysis active=%d top=%s",
                    len(sorted_nudges),
                    [n.key for n in sorted_nudges[:2]])
        return sorted_nudges[:2]

    def get_nudge_prompt_block(self, top_nudges: list[Nudge]) -> str:
        """将 Nudge 列表编译为系统提示词注入块。"""
        if not top_nudges:
            return ""
        lines = ["## 优化建议（Nudge）"]
        for n in top_nudges:
            lines.append(f"- {n.message}")
        return "\n".join(lines)

    def reset(self) -> None:
        """重置所有计数器（新会话时调用）。"""
        self._active_nudges.clear()
        self._tool_error_counter.clear()
        self._tool_call_counter.clear()
        self._rounds_without_file_change = 0
