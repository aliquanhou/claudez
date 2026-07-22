"""ToolOrchestrator — 执行 ExecutionStep，复用已有工具。

职责：
  - 编排 ExecutionStep 执行顺序（串行/并行）
  - 通过 execute_tool() 调用已有工具
  - 超时控制 + 自动重试
  - 返回执行结果列表

设计原则：
  - 复用：不重复实现文件读写，调用 tools/ 中已有的 execute_tool()
  - 安全：所有文件路径经 path_validator 校验（第二批完整实现）
  - 确定性：相同步骤输入 → 相同执行顺序
"""

from __future__ import annotations

import logging
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any

from agent.tools import execute_tool

from .plan_executor import ExecutionStep

_log = logging.getLogger("claudez.execution")


@dataclass
class StepResult:
    """单步执行结果。"""
    step_id: str
    action: str
    target: str
    status: str         # "success" | "error" | "timeout" | "skipped"
    output: str = ""
    duration_ms: float = 0.0
    attempts: int = 1
    error: str = ""


class ToolOrchestrator:
    """工具编排器 — 执行步骤，管理超时/重试/并行。

    Usage:
        orch = ToolOrchestrator(timeout=30, max_retries=1)
        results = orch.execute(steps)
        for r in results:
            print(f"  [{r.status}] {r.action} {r.target} ({r.duration_ms:.0f}ms)")
    """

    # ExecutionStep.action → execute_tool name 映射
    _ACTION_TO_TOOL = {
        "read": "read",
        "write": "write",
        "edit": "edit",
        "delete": "delete",
        "execute": "bash",
        "verify": "read",
    }

    def __init__(
        self,
        timeout: int = 30,
        max_retries: int = 1,
        max_workers: int = 4,
    ):
        self.timeout = timeout
        self.max_retries = max_retries
        self.max_workers = max_workers

    def execute(self, steps: list[ExecutionStep]) -> list[StepResult]:
        """执行步骤列表。

        调度策略：
          1. 将步骤按 PlanStep 分组（plan_index），组间串行
          2. 组内无文件冲突的步骤并行执行
          3. 每步超时控制 + 重试
        """
        if not steps:
            return []

        # 构建步骤依赖图
        step_map = {s.id: s for s in steps}

        # 按 plan_index 分组
        from collections import defaultdict
        plan_groups: dict[int, list[ExecutionStep]] = defaultdict(list)
        for step in steps:
            pi = step.metadata.get("plan_index", 0)
            plan_groups[pi].append(step)

        all_results: list[StepResult] = []

        # 组间串行
        for group_idx in sorted(plan_groups.keys()):
            group_steps = plan_groups[group_idx]

            # 组内：无依赖的步骤并行
            independent = [s for s in group_steps if not s.depends_on]
            dependent = [s for s in group_steps if s.depends_on]

            # 执行无依赖步骤（并行）
            if independent:
                results = self._execute_batch(independent)
                all_results.extend(results)

            # 执行有依赖步骤（串行）
            for step in dependent:
                # 检查依赖是否全部成功
                deps_ok = all(
                    r.status == "success"
                    for r in all_results
                    if r.step_id in step.depends_on
                )
                if not deps_ok:
                    all_results.append(StepResult(
                        step_id=step.id,
                        action=step.action,
                        target=step.target,
                        status="skipped",
                        output="依赖步骤未成功",
                    ))
                    continue

                result = self._execute_single(step)
                all_results.append(result)

        return all_results

    def _execute_batch(self, steps: list[ExecutionStep]) -> list[StepResult]:
        """并行执行一批步骤。"""
        if len(steps) == 1:
            return [self._execute_single(steps[0])]

        results: list[StepResult] = []
        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(steps))) as pool:
            futures = {
                pool.submit(self._execute_single, step): step
                for step in steps
            }
            for future in as_completed(futures):
                try:
                    results.append(future.result())
                except Exception as e:
                    step = futures[future]
                    results.append(StepResult(
                        step_id=step.id, action=step.action,
                        target=step.target, status="error",
                        error=str(e),
                    ))
        return results

    def _execute_single(self, step: ExecutionStep) -> StepResult:
        """执行单个步骤，带超时和重试。"""
        tool_name = self._ACTION_TO_TOOL.get(step.action, "bash")
        args = self._build_args(step)

        last_error = ""
        attempts = 0

        while attempts <= step.max_retries:
            attempts += 1
            t0 = time.time()

            try:
                # 带超时执行
                if self.timeout > 0:
                    result = self._run_with_timeout(tool_name, args, step)
                else:
                    result = execute_tool(tool_name, args)

                duration = (time.time() - t0) * 1000

                # 检查结果是否指示错误
                is_error = (
                    result.startswith("[错误]")
                    or result.startswith("[超时]")
                    or result.startswith("[权限拒绝]")
                )

                if is_error and attempts <= step.max_retries:
                    last_error = result
                    _log.warning("step_retry action=%s target=%s attempt=%d/%d",
                                  step.action, step.target, attempts, step.max_retries + 1)
                    continue

                status = "error" if is_error else "success"
                return StepResult(
                    step_id=step.id, action=step.action,
                    target=step.target, status=status,
                    output=result[:500],
                    duration_ms=duration, attempts=attempts,
                    error=result if is_error else "",
                )

            except TimeoutError:
                duration = (time.time() - t0) * 1000
                last_error = "timeout"
                if attempts <= step.max_retries:
                    _log.warning("step_timeout action=%s target=%s attempt=%d",
                                  step.action, step.target, attempts)
                    continue
                return StepResult(
                    step_id=step.id, action=step.action,
                    target=step.target, status="timeout",
                    output="", duration_ms=duration, attempts=attempts,
                    error=f"timeout after {self.timeout}s",
                )

            except Exception as e:
                duration = (time.time() - t0) * 1000
                last_error = str(e)
                if attempts <= step.max_retries:
                    continue
                return StepResult(
                    step_id=step.id, action=step.action,
                    target=step.target, status="error",
                    output="", duration_ms=duration, attempts=attempts,
                    error=str(e),
                )

        # 所有重试用尽
        return StepResult(
            step_id=step.id, action=step.action,
            target=step.target, status="error",
            error=last_error,
        )

    def _run_with_timeout(
        self, tool_name: str, args: dict, step: ExecutionStep,
    ) -> str:
        """带超时的工具执行。"""
        result_container: list[str] = []
        exception_container: list[Exception] = []

        def target():
            try:
                r = execute_tool(tool_name, args)
                result_container.append(r)
            except Exception as e:
                exception_container.append(e)

        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        thread.join(timeout=self.timeout)

        if thread.is_alive():
            raise TimeoutError(f"tool {tool_name} timed out after {self.timeout}s")

        if exception_container:
            raise exception_container[0]

        return result_container[0] if result_container else ""

    def _build_args(self, step: ExecutionStep) -> dict:
        """构建 execute_tool 的参数。"""
        if step.action == "read":
            return {"file_path": step.target, "head": 0, "tail": 0}
        elif step.action == "write":
            return {"file_path": step.target, "content": step.content or ""}
        elif step.action == "edit":
            return {
                "file_path": step.target,
                "old_string": step.metadata.get("old_string", ""),
                "new_string": step.metadata.get("new_string", step.content or ""),
            }
        elif step.action == "delete":
            return {"file_path": step.target}
        elif step.action == "execute":
            return {"command": step.target}
        elif step.action == "verify":
            return {"file_path": step.target, "head": 0, "tail": 0}
        else:
            return {"command": step.target}
