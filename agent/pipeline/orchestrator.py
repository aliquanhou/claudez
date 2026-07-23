"""PipelineOrchestrator — 多 Agent 异质流水线编排器。

Planner → Executor → Verifier 三阶段：
  1. Planner 角色: 分析需求，输出方案（只读 + 搜索）
  2. Executor 角色: 按方案执行（写 + 命令，无搜索）
  3. Verifier 角色: 验证结果（只读 + git，无写）

自动修复：Verifier 判定 FAIL → 带反馈回退到 Planner（最多 3 次）
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

from agent.roles import AgentRole, filter_tools_by_role, get_role_system_prompt_suffix
from agent.session import create_isolated_session
from agent.core import Agent

from .types import PipelineTask, PipelinePhase, PipelineResult
from .checkpoint import save_checkpoint, load_checkpoint

_log = logging.getLogger("claudez.pipeline")


class PipelineOrchestrator:
    """多 Agent 流水线编排器。

    Usage:
        orch = PipelineOrchestrator(parent_agent)
        result = orch.run("Write a fibonacci function in Python")
        print(result.message)
    """

    # 方案提取关键词：表示方案开始的标志
    PLAN_MARKERS = ["方案如下", "计划如下", "plan:", "steps:", "步骤:", "1."]

    def __init__(
        self,
        config: dict | None = None,
        checkpoint_dir: str = "",
    ):
        self.config = config or {}
        self.checkpoint_dir = checkpoint_dir or ""
        self._task: PipelineTask | None = None

    def run(self, goal: str) -> PipelineResult:
        """执行完整的流水线流程。

        Args:
            goal: 用户目标

        Returns:
            PipelineResult: 流水线执行结果
        """
        task_id = str(uuid.uuid4())[:8]
        self._task = PipelineTask(
            id=task_id,
            goal=goal,
            max_retries=self.config.get("pipeline_max_retries", 3),
        )
        _log.info("pipeline_start id=%s goal=%s", task_id, goal[:100])

        phases_completed = []
        t0 = time.time()

        while not self._task.is_done:
            phase = self._task.phase
            _log.info("pipeline_phase id=%s phase=%s retry=%d/%d",
                      task_id, phase.value, self._task.retry_count, self._task.max_retries)

            try:
                if phase == PipelinePhase.PLANNING:
                    self._run_planner()
                    phases_completed.append(PipelinePhase.PLANNING)
                    self._task.phase = PipelinePhase.EXECUTING

                elif phase == PipelinePhase.EXECUTING:
                    self._run_executor()
                    phases_completed.append(PipelinePhase.EXECUTING)
                    self._task.phase = PipelinePhase.VERIFYING

                elif phase == PipelinePhase.VERIFYING:
                    self._run_verifier()
                    phases_completed.append(PipelinePhase.VERIFYING)

                    if self._task.verdict == "PASS":
                        self._task.phase = PipelinePhase.COMPLETED
                        _log.info("pipeline_pass id=%s", task_id)
                    elif self._task.retry_count < self._task.max_retries:
                        self._task.retry_count += 1
                        self._task.phase = PipelinePhase.PLANNING
                        _log.info("pipeline_retry id=%s attempt=%d/%d",
                                  task_id, self._task.retry_count, self._task.max_retries)
                    else:
                        self._task.phase = PipelinePhase.FAILED
                        _log.info("pipeline_fail id=%s max_retries=%d",
                                  task_id, self._task.max_retries)

            except Exception as e:
                _log.error("pipeline_error id=%s phase=%s error=%s",
                           task_id, phase.value, e)
                self._task.error = str(e)
                self._task.phase = PipelinePhase.FAILED

            # 保存检查点
            if self.checkpoint_dir:
                cp_path = f"{self.checkpoint_dir}/pipeline_{task_id}.json"
                save_checkpoint(self._task, cp_path)

        self._task.completed_at = time.time()
        duration = (self._task.completed_at - t0) * 1000

        success = self._task.succeeded
        message = (
            f"Pipeline {task_id} {'SUCCESS' if success else 'FAILED'}: "
            f"{'PASS' if self._task.verdict == 'PASS' else self._task.verdict} "
            f"in {len(phases_completed)} phases, {self._task.retry_count} retries"
        )
        _log.info("pipeline_end id=%s success=%s duration=%.0fms",
                  task_id, success, duration)

        return PipelineResult(
            success=success,
            task=self._task,
            phases_completed=phases_completed,
            total_duration_ms=duration,
            message=message,
        )

    def _create_sub_agent(self, role: AgentRole) -> Agent:
        """创建指定角色的子 Agent（隔离会话）。"""
        agent = Agent(config=self.config, session=create_isolated_session())
        agent.set_role(role)
        return agent

    def _run_planner(self) -> None:
        """阶段 1: Planner — 制定方案。"""
        prompt = (
            f"请分析以下需求并制定详细的执行方案。\n\n"
            f"需求: {self._task.goal}\n\n"
            f"请输出一个结构化的方案，包含：\n"
            f"1. 具体步骤（每个步骤做什么）\n"
            f"2. 目标文件列表\n"
            f"3. 每个步骤需要的工具\n"
            f"4. 预估工作量\n\n"
            f"如果上一步验证失败，以下是反馈，请修正方案：\n"
            f"{self._task.verification_report}\n" if self._task.verification_report else ""
        )

        agent = self._create_sub_agent(AgentRole.PLANNER)
        _log.info("pipeline_planner_start id=%s", self._task.id)

        try:
            result = agent.run(prompt)
            self._task.plan_text = result
            _log.info("pipeline_planner_done id=%s len=%d",
                      self._task.id, len(result))
        except Exception as e:
            self._task.plan_text = f"[Planner 错误] {e}"
            _log.error("pipeline_planner_error id=%s %s", self._task.id, e)
            raise

    def _run_executor(self) -> None:
        """阶段 2: Executor — 执行方案。"""
        prompt = (
            f"请根据以下方案执行。\n\n"
            f"## 方案\n{self._task.plan_text}\n\n"
            f"## 原始需求\n{self._task.goal}\n\n"
            f"严格按照方案的每一步执行。"
        )

        agent = self._create_sub_agent(AgentRole.EXECUTOR)
        _log.info("pipeline_executor_start id=%s", self._task.id)

        try:
            result = agent.run(prompt)
            self._task.execution_result = result
            _log.info("pipeline_executor_done id=%s len=%d",
                      self._task.id, len(result))
        except Exception as e:
            self._task.execution_result = f"[Executor 错误] {e}"
            _log.error("pipeline_executor_error id=%s %s", self._task.id, e)
            raise

    def _run_verifier(self) -> None:
        """阶段 3: Verifier — 验证结果。"""
        prompt = (
            f"请验证以下执行结果是否符合方案预期。\n\n"
            f"## 原始需求\n{self._task.goal}\n\n"
            f"## 方案\n{self._task.plan_text}\n\n"
            f"## 执行结果\n{self._task.execution_result}\n\n"
            f"请给出验证结论（PASS / PARTIAL / FAIL），并说明原因。"
        )

        agent = self._create_sub_agent(AgentRole.VERIFIER)
        _log.info("pipeline_verifier_start id=%s", self._task.id)

        try:
            result = agent.run(prompt)
            self._task.verification_report = result
            self._task.verdict = self._extract_verdict(result)
            _log.info("pipeline_verifier_done id=%s verdict=%s",
                      self._task.id, self._task.verdict)
        except Exception as e:
            self._task.verification_report = f"[Verifier 错误] {e}"
            self._task.verdict = "FAIL"
            _log.error("pipeline_verifier_error id=%s %s", self._task.id, e)

    @staticmethod
    def _extract_verdict(report: str) -> str:
        """从验证报告提取 Verdict。

        按优先级匹配：
          1. 明确的 "VERDICT: X" / "[X]" 关键字
          2. 正向/负向信号分析
          3. 默认为 "PARTIAL"
        """
        upper = report.upper()
        if "VERDICT: PASS" in upper or "[PASS]" in upper:
            return "PASS"
        if "VERDICT: FAIL" in upper or "[FAIL]" in upper:
            return "FAIL"
        if "VERDICT: PARTIAL" in upper or "[PARTIAL]" in upper:
            return "PARTIAL"
        fail_signals = ["失败", "不通过", "错误", "问题", "bug", "incorrect", "failed", "wrong", "error"]
        pass_signals = ["正确", "通过", "成功", "pass", "correct", "success", "all good", "没问题"]
        lower = upper.lower()
        has_fail = any(s in lower for s in fail_signals)
        has_pass = any(s in lower for s in pass_signals)
        if has_fail and not has_pass:
            return "FAIL"
        if has_pass and not has_fail:
            return "PASS"
        return "PARTIAL"

    def get_task(self) -> PipelineTask | None:
        """获取当前流水线任务。"""
        return self._task
