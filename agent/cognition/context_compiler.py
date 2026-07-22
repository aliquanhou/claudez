"""Context Compiler — 把铁三角数据编译成结构化 Prompt，桥接 LLM。

编译 4 个块：
  1. Intent Block      — 用户意图（来自 IntentResonator）
  2. Task Block        — 任务状态（来自 TaskManager）
  3. Workspace Block   — 工作区快照（来自 WorkspaceScanner）
  4. Plan Block        — 方案验证结果（来自 PlanVerifier，可选）

确定性输出：相同输入 → 相同输出。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from .task_context import TaskManager, TaskPhase
from .intent_resonator import IntentVector, IntentSignal
from .workspace_scanner import WorkspaceInfo
from .plan_verifier import VerificationReport, Verdict


@dataclass
class CompiledContext:
    """编译后的上下文，可直接注入 Prompt。"""

    intent_block: str       # 意图描述
    task_block: str         # 任务状态
    workspace_block: str    # 工作区快照
    plan_block: str         # 方案验证结果（如果有）

    # 元数据
    turn_count: int
    phase: str
    compiled_at: float

    def to_prompt(self) -> str:
        """合并所有块，生成最终的 Prompt 字符串。"""
        blocks = []
        if self.intent_block:
            blocks.append(f"[USER INTENT]\n{self.intent_block}")
        if self.task_block:
            blocks.append(f"[TASK CONTEXT]\n{self.task_block}")
        if self.workspace_block:
            blocks.append(f"[WORKSPACE]\n{self.workspace_block}")
        if self.plan_block:
            blocks.append(f"[PLAN VERIFICATION]\n{self.plan_block}")
        return "\n\n".join(blocks)


class ContextCompiler:
    """上下文编译器 — 把铁三角数据编译成结构化 Prompt。

    桥接 cognition/ 模块和现有的 DynamicPromptBuilder。
    所有输入都可能为 None，内部优雅降级。
    """

    def __init__(self, max_workspace_files: int = 20):
        """
        Args:
            max_workspace_files: workspace 块中最多显示的文件数
        """
        self.max_workspace_files = max_workspace_files

    def compile(
        self,
        task_manager: TaskManager,
        intent_vector: IntentVector | None = None,
        workspace_info: WorkspaceInfo | None = None,
        verification_report: VerificationReport | None = None,
    ) -> CompiledContext:
        """编译所有数据为结构化上下文。

        Args:
            task_manager: 任务管理器（包含当前任务）
            intent_vector: 意图向量（可能为 None）
            workspace_info: 工作区信息（可能为 None）
            verification_report: 方案验证报告（可选）

        Returns:
            CompiledContext: 可注入 Prompt 的编译结果
        """
        intent_block = self._compile_intent_block(intent_vector)
        task_block = self._compile_task_block(task_manager)
        workspace_block = self._compile_workspace_block(workspace_info)
        plan_block = self._compile_plan_block(verification_report)

        # 提取元数据
        current_task = task_manager.get_current_task()
        turn_count = current_task.turn_count if current_task else 0
        phase = current_task.current_phase.value if current_task else "none"

        return CompiledContext(
            intent_block=intent_block,
            task_block=task_block,
            workspace_block=workspace_block,
            plan_block=plan_block,
            turn_count=turn_count,
            phase=phase,
            compiled_at=time.time(),
        )

    # ── 内部编译方法 ──

    def _compile_intent_block(self, intent: IntentVector | None) -> str:
        """编译意图块。"""
        if intent is None:
            return ""

        lines = [
            f"Current Intent: {intent.primary_intent.value.upper()} "
            f"(confidence: {intent.confidence:.2f})",
            f"Urgency: {intent.urgency:.2f}",
            f"Narrative: {intent.narrative}",
        ]

        # 建议关注方向
        focus = {
            IntentSignal.EXPLORING: "帮助用户快速定位目标代码区域",
            IntentSignal.DEBUGGING: "聚焦问题根因分析，提供修复建议",
            IntentSignal.REFACTORING: "关注重构安全性和代码一致性",
            IntentSignal.IMPLEMENTING: "实时提供代码补全和 API 建议",
            IntentSignal.REVIEWING: "标注潜在问题并给出改进建议",
            IntentSignal.STUCK: "主动询问是否需要帮助，提供解决思路",
            IntentSignal.CONFIDENT: "保持当前节奏，无需干预",
        }.get(intent.primary_intent, "根据用户操作上下文响应")
        lines.extend(["", f"Suggested Focus: {focus}"])

        if intent.secondary_intents:
            secondaries = ", ".join(
                f"{s.value}({c:.0%})" for s, c in intent.secondary_intents
            )
            lines.extend(["", f"Secondary Intents: {secondaries}"])

        return "\n".join(lines)

    def _compile_task_block(self, task_manager: TaskManager) -> str:
        """编译任务块。"""
        task = task_manager.get_current_task()
        if task is None:
            return "当前无活跃任务。"

        lines = [
            f"Task ID: {task.task_id}",
            f"Goal: {task.user_goal}",
            f"Current Phase: {task.current_phase.value}",
        ]

        # 步骤进度估算
        completed_phases = len([p for p in task.phases if p.completed_at is not None])
        total_phases = len(task.phases) if task.phases else 1
        lines.append(f"Progress: {completed_phases}/{total_phases} 阶段已完成")

        # 最近决策
        if task.decisions:
            lines.append("Recent Decisions:")
            for d in task.decisions[-5:]:
                ago = self._format_ago(time.time() - d.timestamp) if d.timestamp else ""
                desc = d.description[:80]
                lines.append(f"  - {desc} ({ago})")

        # 已修改文件
        if task.modified_files:
            lines.append("Modified Files:")
            for f in task.modified_files[-5:]:
                lines.append(f"  - {f}")

        return "\n".join(lines)

    def _compile_workspace_block(self, info: WorkspaceInfo | None) -> str:
        """编译工作区块（限制文件数量）。"""
        if info is None:
            return "工作区未扫描。"

        lines = [
            f"Project: {info.root_path}",
            f"Type: {info.project_type or 'unknown'}",
        ]

        if info.languages:
            lines.append(f"Languages: {', '.join(info.languages[:4])}")

        if info.key_files:
            lines.append("Key Files:")
            for f in info.key_files[:self.max_workspace_files]:
                lines.append(f"  - {f}")

        # 仅在有足够文件时显示总计
        lines.append(f"File Count: {info.file_count} files scanned")

        return "\n".join(lines)

    def _compile_plan_block(self, report: VerificationReport | None) -> str:
        """编译方案验证块。"""
        if report is None:
            return ""

        lines = [
            f"Verdict: {report.verdict.value.upper()} (score: {report.score})",
        ]

        # 如果有 metrics，尝试提取 plan_id 和 steps
        metrics = getattr(report, "metrics", {})
        if "step_count" in metrics:
            lines.append(f"Steps: {metrics['step_count']}")
        if "target_file_count" in metrics:
            lines.append(f"Target Files: {metrics['target_file_count']}")

        if report.warnings:
            lines.append("Warnings:")
            for w in report.warnings[:3]:
                lines.append(f"  - {w}")
            if len(report.warnings) > 3:
                lines.append(f"  ... and {len(report.warnings) - 3} more")

        if report.issues:
            lines.append("Issues:")
            for i in report.issues[:3]:
                lines.append(f"  - {i}")

        if report.suggestions:
            lines.append("Suggestions:")
            for s in report.suggestions[:3]:
                lines.append(f"  - {s}")

        return "\n".join(lines)

    # ── 辅助 ──

    def _format_ago(self, seconds: float) -> str:
        """格式化时间差为人类可读字符串。"""
        if seconds < 60:
            return "刚刚"
        if seconds < 3600:
            return f"{int(seconds / 60)}m ago"
        return f"{int(seconds / 3600)}h ago"
