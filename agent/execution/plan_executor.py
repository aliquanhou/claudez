"""PlanExecutor — 把方案拆解为原子执行步骤。

职责：
  - 将 PlanVerifier 验证通过的 Plan 拆解为 List[ExecutionStep]
  - 每个 PlanStep(action, file, description) 拆为 1+N 个 ExecutionStep
  - 检测文件冲突，标记可并行步骤

设计原则：
  - 单一职责：每个 ExecutionStep 只做一件事
  - 1:N 映射：PlanStep(action="edit") → [read, edit, verify]
  - 冲突检测：两个步骤改同一文件 → 串行
  - 无冲突的步骤标记为可并行

依赖：
  - agent.cognition.plan_verifier.Plan
"""

from __future__ import annotations

import uuid
import time
from dataclasses import dataclass, field
from typing import Any

from agent.cognition.plan_verifier import Plan, PlanStep


# ── 步骤动作常量 ──

ACTION_READ = "read"
ACTION_WRITE = "write"
ACTION_EDIT = "edit"
ACTION_DELETE = "delete"
ACTION_EXECUTE = "execute"
ACTION_VERIFY = "verify"


@dataclass
class ExecutionStep:
    """原子执行步骤。"""
    id: str
    action: str          # "read" | "write" | "edit" | "delete" | "execute" | "verify"
    target: str          # 文件路径或命令
    content: str | None = None
    depends_on: list[str] = field(default_factory=list)
    parallel_group: int = 0        # 0 = 串行, >0 = 同组可并行
    metadata: dict[str, Any] = field(default_factory=dict)
    max_retries: int = 1

    @property
    def is_readonly(self) -> bool:
        return self.action in (ACTION_READ, ACTION_VERIFY)


class PlanExecutor:
    """PlanExecutor — 方案拆解器。

    Usage:
        executor = PlanExecutor(workspace_root="/path/to/project")
        steps = executor.decompose(plan)
        for step in steps:
            print(f"  {step.action:>8}  {step.target}")
    """

    # PlanStep.action → ExecutionStep 模板
    _ACTION_TEMPLATES = {
        "edit": [
            (ACTION_READ, "读取当前文件内容"),
            (ACTION_EDIT, "应用修改"),
            (ACTION_VERIFY, "验证文件内容正确"),
        ],
        "create": [
            (ACTION_WRITE, "写入新文件"),
            (ACTION_VERIFY, "验证文件已创建"),
        ],
        "delete": [
            (ACTION_DELETE, "删除文件"),
        ],
        "execute": [
            (ACTION_EXECUTE, "执行命令"),
        ],
    }

    def __init__(self, workspace_root: str = "."):
        self.workspace_root = workspace_root

    def decompose(self, plan: Plan) -> list[ExecutionStep]:
        """将 Plan 拆解为 ExecutionStep 列表。

        策略：
          1. 每个 PlanStep 按模板展开为 1+ 个 ExecutionStep
          2. 检测文件重叠：同一文件被多个步骤修改 → 串行
          3. 无重叠的不同文件步骤 → 可并行
        """
        if not plan.steps:
            return []

        all_steps: list[ExecutionStep] = []
        file_touch_map: dict[str, list[int]] = {}  # file → step indices

        for plan_idx, plan_step in enumerate(plan.steps):
            step_ids: list[str] = []
            templates = self._ACTION_TEMPLATES.get(
                plan_step.action, self._ACTION_TEMPLATES["edit"],
            )

            for action, desc in templates:
                step_id = str(uuid.uuid4())
                depends_on = list(step_ids)  # 链式依赖：前一步完成后再下一步
                if action == ACTION_EXECUTE:
                    target = plan_step.description or plan_step.file
                else:
                    target = plan_step.file

                es = ExecutionStep(
                    id=step_id,
                    action=action,
                    target=target,
                    depends_on=depends_on,
                    metadata={
                        "plan_index": plan_idx,
                        "plan_action": plan_step.action,
                        "plan_description": plan_step.description,
                        "description": desc,
                    },
                )
                all_steps.append(es)
                step_ids.append(step_id)

            # 记录此 PlanStep 接触的所有文件
            target_file = plan_step.file
            if target_file:
                if target_file not in file_touch_map:
                    file_touch_map[target_file] = []
                file_touch_map[target_file].append(plan_idx)

        # ── 冲突检测：不同 PlanStep 修改同一文件 → 串行化 ──
        # 找所有有冲突的 PlanStep 对
        conflict_groups: list[set[int]] = []
        for file_path, indices in file_touch_map.items():
            if len(indices) >= 2:
                # 这些 PlanStep 有冲突，需要串行
                for i in range(1, len(indices)):
                    self._add_dependency(all_steps, indices[i], indices[i - 1])

        # ── 标记可并行组（无依赖关系的步骤） ──
        self._assign_parallel_groups(all_steps)

        return all_steps

    def _add_dependency(
        self, all_steps: list[ExecutionStep], later_idx: int, earlier_idx: int,
    ) -> None:
        """让 later PlanStep 依赖 earlier PlanStep 的最后一步。"""
        # 找到 earlier 的最后一步
        earlier_last = None
        later_first = None
        for i, s in enumerate(all_steps):
            if s.metadata.get("plan_index") == earlier_idx:
                earlier_last = i
            if s.metadata.get("plan_index") == later_idx and later_first is None:
                later_first = i

        if earlier_last is not None and later_first is not None:
            earlier_last_id = all_steps[earlier_last].id
            if earlier_last_id not in all_steps[later_first].depends_on:
                all_steps[later_first].depends_on.append(earlier_last_id)

    def _assign_parallel_groups(self, all_steps: list[ExecutionStep]) -> None:
        """为无依赖的步骤分配并行组。"""
        step_map = {s.id: s for s in all_steps}
        group_id = 0
        for step in all_steps:
            # 检查所有依赖是否已分配并行组
            all_dep_done = all(
                step_map.get(dep) is not None
                for dep in step.depends_on
            )
            if not step.depends_on:
                # 无依赖 → 同组并行
                if group_id == 0:
                    group_id = 1
                step.parallel_group = group_id
            elif all_dep_done:
                # 依赖已存在 → 新组串行（在依赖完成后执行）
                group_id += 1
                step.parallel_group = group_id
                # 同一 PlanStep 的其他步也同组
                plan_idx = step.metadata.get("plan_index")
                for s in all_steps:
                    if s.metadata.get("plan_index") == plan_idx:
                        s.parallel_group = group_id
            else:
                step.parallel_group = 0  # 串行

    def summarize(self, steps: list[ExecutionStep]) -> str:
        """生成人类可读的步骤摘要。"""
        if not steps:
            return "No steps to execute."

        lines = [f"Execution Plan ({len(steps)} steps):"]
        for i, step in enumerate(steps):
            prefix = "  PAR" if step.parallel_group > 0 else "  SEQ"
            deps = f" → after {len(step.depends_on)}" if step.depends_on else ""
            desc = step.metadata.get("description", "")
            lines.append(
                f"{prefix} {i + 1}. [{step.action}] {step.target}{deps}"
                f"  # {desc}"
            )
        return "\n".join(lines)
