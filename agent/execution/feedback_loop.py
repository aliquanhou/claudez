"""FeedbackLoop — 执行结果反馈闭环。

职责：
  1. 调用 ExecutionVerifier 验证执行结果
  2. 将结果记录到 TaskContext（决策历史）
  3. 根据 Verdict 自动推进或回退阶段
  4. 返回人类可读的反馈信息

闭环流程：
  PASS    → phase = DONE
  PARTIAL → phase = ANALYSIS（修整方案后重试）
  FAIL    → phase = PLANNING（重新规划）
"""

from __future__ import annotations

import logging
from typing import Any

from agent.cognition.task_context import TaskManager, TaskPhase
from agent.cognition.execution_verifier import (
    ExecutionVerifier, Verdict, Plan, ExecutionReport, WorkspaceSnapshot,
)
from agent.cognition.plan_verifier import Plan as PVPlan

_log = logging.getLogger("claudez.execution")


class FeedbackLoop:
    """执行结果反馈闭环。

    Usage:
        loop = FeedbackLoop(task_manager, execution_verifier)
        feedback = loop.process(plan, before_info, after_info, logs)
        print(feedback["message"])
    """

    def __init__(
        self,
        task_manager: TaskManager | None = None,
        execution_verifier: ExecutionVerifier | None = None,
    ) -> None:
        self.task_manager = task_manager
        self.execution_verifier = execution_verifier or ExecutionVerifier()

    def process(
        self,
        plan: PVPlan,
        before_snapshot: WorkspaceSnapshot | None = None,
        after_snapshot: WorkspaceSnapshot | None = None,
        logs: list[str] | None = None,
    ) -> dict[str, Any]:
        """处理执行结果并反馈到 TaskContext。

        Args:
            plan: 原始方案（plan_verifier.Plan 类型）
            before_snapshot: 执行前的工作区快照（可选）
            after_snapshot: 执行后的工作区快照（可选）
            logs: 执行日志列表（可选）

        Returns:
            dict with keys:
                verdict: str — "PASS" | "PARTIAL" | "FAIL"
                score: int — 0-100
                message: str — 人类可读的总结
                next_phase: str — 下一个阶段名
                report: ExecutionReport — 完整验证报告
        """
        # 1. 将 plan_verifier.Plan 转换为 execution_verifier.Plan
        ev_plan = Plan(
            id=plan.id,
            description=plan.description,
            steps=[{"action": s.action, "file": s.file, "description": s.description}
                   for s in plan.steps],
            target_files=plan.target_files,
        )

        # 2. 执行验证
        report = self.execution_verifier.verify(
            ev_plan,
            before_snapshot or WorkspaceSnapshot(root_path="."),
            after_snapshot or WorkspaceSnapshot(root_path="."),
            logs,
        )

        # 3. 记录到 TaskContext（如果可用）
        if self.task_manager is not None:
            task = self.task_manager.get_current_task()
            if task:
                self.task_manager.add_decision(
                    task.task_id,
                    description=f"执行结果: {report.verdict.value.upper()}",
                    rationale=(
                        f"Score: {report.deviation_score:.2f}, "
                        f"Changes: {len(report.changes)}, "
                        f"Errors: {len(report.errors)}"
                    ),
                )

        # 4. 根据 Verdict 推进/回退阶段
        verdict, next_phase, message = self._determine_outcome(report)

        if self.task_manager is not None:
            task = self.task_manager.get_current_task()
            if task:
                try:
                    self.task_manager.transition_phase(task.task_id, TaskPhase(next_phase))
                    _log.info("feedback phase_transition phase=%s verdict=%s",
                              next_phase, verdict)
                except Exception as e:
                    _log.warning("feedback phase_transition failed: %s", e)

        return {
            "verdict": verdict,
            "score": report.deviation_score,
            "message": message,
            "next_phase": next_phase,
            "report": report,
        }

    def _determine_outcome(
        self, report: ExecutionReport,
    ) -> tuple[str, str, str]:
        """根据验证报告确定 verdict 和下一阶段。"""
        if report.verdict == Verdict.FAIL:
            msg = "执行失败"
            if report.errors:
                msg += f": {report.errors[0][:200]}"
            else:
                msg += "：无步骤成功执行"
            return "FAIL", "planning", msg

        if report.verdict == Verdict.PARTIAL:
            msg = "部分成功"
            inconsistencies = [
                w for w in report.warnings
                if "未被修改" in w or "超出范围" in w
            ]
            if inconsistencies:
                msg += f"（{inconsistencies[0][:100]}）"
            elif report.matched_steps < report.total_steps:
                msg += f"（{report.matched_steps}/{report.total_steps} 步骤匹配）"
            return "PARTIAL", "analysis", msg

        # PASS
        modified = len([c for c in report.changes if c.action != "unchanged"])
        return (
            "PASS", "done",
            f"执行成功！修改了 {modified} 个文件，"
            f"{report.matched_steps}/{report.total_steps} 步骤匹配",
        )
