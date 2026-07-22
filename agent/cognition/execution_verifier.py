"""Execution Verifier — 验证执行结果是否符合方案预期。

6 阶段验证：
  1. 文件变更检测 — 对比 before/after 快照
  2. 步骤匹配     — 方案中的步骤是否被执行
  3. 目标文件覆盖  — target_files 是否被修改
  4. 错误检测     — 执行日志中是否有错误
  5. 偏差分析     — 变更是否超出方案范围
  6. 综合评分     — 生成 verdict 和 score
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
from enum import Enum


class Verdict(Enum):
    PASS = "pass"
    PARTIAL = "partial"
    FAIL = "fail"


@dataclass
class FileChange:
    """单个文件的变更记录"""
    file: str
    action: str                    # "created", "modified", "deleted", "unchanged"
    lines_added: int = 0
    lines_removed: int = 0


@dataclass
class ExecutionReport:
    """执行验证报告"""
    verdict: Verdict               # PASS / PARTIAL / FAIL
    success: bool                  # True 如果完全成功
    changes: list[FileChange] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    deviation_score: float = 0.0   # 0.0 = 完全符合方案, 1.0 = 完全偏离
    matched_steps: int = 0         # 方案中成功执行的步骤数
    total_steps: int = 0           # 方案中总步骤数

    def summary(self) -> str:
        """人类可读摘要。"""
        status_icon = {"pass": "PASS", "partial": "PARTIAL", "fail": "FAIL"}
        status = status_icon.get(self.verdict.value, "?")
        parts = [
            f"[{status}] success={self.success}",
            f"         Steps: {self.matched_steps}/{self.total_steps}",
            f"         Deviation: {self.deviation_score:.2f}",
            f"         Errors: {len(self.errors)}",
            f"         Warnings: {len(self.warnings)}",
        ]
        if self.changes:
            parts.append(f"  Changes ({len(self.changes)}):")
            for c in self.changes[:5]:
                parts.append(f"    {c.action:>8}  {c.file}")
            if len(self.changes) > 5:
                parts.append(f"    ... and {len(self.changes) - 5} more")
        if self.errors:
            parts.append("  Errors:")
            for e in self.errors[:5]:
                parts.append(f"    - {e}")
        return "\n".join(parts)


@dataclass
class Plan:
    """方案（简化版，与 plan_verifier 保持一致）"""
    id: str
    description: str
    steps: list[dict]              # 每个 step 含 action, file, description
    target_files: list[str] = field(default_factory=list)


@dataclass
class WorkspaceSnapshot:
    """工作区快照（简化版）"""
    root_path: str
    files: list[str] = field(default_factory=list)
    file_count: int = 0


# ── 执行日志错误关键词 ──

_ERROR_KEYWORDS = ["error", "fail", "exception", "traceback", "fatal",
                   "timeout", "permission denied", "not found",
                   "syntaxerror", "importerror", "值错误", "异常", "失败"]


class ExecutionVerifier:
    """执行结果验证器 — 6 阶段验证，确定性输出。"""

    # ── 偏差权重 ──
    DEVIATION_PARTIAL_THRESHOLD = 0.3

    def verify(
        self,
        plan: Plan,
        before_snapshot: WorkspaceSnapshot,
        after_snapshot: WorkspaceSnapshot,
        execution_log: Optional[list[str]] = None,
    ) -> ExecutionReport:
        """验证执行结果是否符合方案预期。

        6 阶段验证：
          1. 文件变更检测
          2. 步骤匹配
          3. 目标文件覆盖
          4. 错误检测
          5. 偏差分析
          6. 综合评分
        """
        # ── 阶段 1: 文件变更检测 ──
        changes = self._detect_changes(
            before_snapshot, after_snapshot, plan, execution_log,
        )

        # ── 阶段 2: 步骤匹配 ──
        matched, total = self._match_steps(plan, changes)
        matched_steps = matched
        total_steps = total

        # ── 阶段 3: 目标文件覆盖 ──
        warnings: list[str] = []
        changed_files = {c.file for c in changes}
        target_set = set(plan.target_files)
        for target_file in plan.target_files:
            if target_file not in changed_files:
                warnings.append(f"目标文件 {target_file} 未被修改")

        # ── 阶段 4: 错误检测 ──
        errors: list[str] = []
        if execution_log:
            for line in execution_log:
                lower_line = line.lower()
                for kw in _ERROR_KEYWORDS:
                    if kw in lower_line:
                        errors.append(line)
                        break

        # ── 阶段 5: 偏差分析 ──
        deviation_score = self._compute_deviation(changes, target_set)
        for change in changes:
            if change.file not in target_set:
                warnings.append(
                    f"文件 {change.file} 不在方案目标文件中，可能属于超出范围的修改"
                )

        # ── 阶段 6: 综合评分 ──
        verdict, success = self._compute_verdict(
            errors, matched_steps, total_steps, deviation_score,
        )

        return ExecutionReport(
            verdict=verdict,
            success=success,
            changes=changes,
            errors=errors,
            warnings=warnings,
            deviation_score=deviation_score,
            matched_steps=matched_steps,
            total_steps=total_steps,
        )

    # ── 阶段 1: 文件变更检测 ──

    def _detect_changes(
        self,
        before: WorkspaceSnapshot,
        after: WorkspaceSnapshot,
        plan: Plan,
        execution_log: Optional[list[str]],
    ) -> list[FileChange]:
        """对比 before/after 快照，生成变更列表。"""
        before_set = set(before.files)
        after_set = set(after.files)

        target_set = set(plan.target_files)
        changes: list[FileChange] = []
        seen: set[str] = set()

        # 新增文件
        for f in sorted(after_set - before_set):
            changes.append(FileChange(file=f, action="created"))
            seen.add(f)

        # 删除文件
        for f in sorted(before_set - after_set):
            changes.append(FileChange(file=f, action="deleted"))
            seen.add(f)

        # 交集文件：如果 execution_log 被提供（说明执行确实发生过），
        # 则 target_files 中的文件视为 "modified"
        has_execution_evidence = execution_log is not None
        for f in sorted(before_set & after_set):
            if has_execution_evidence and f in target_set:
                changes.append(FileChange(file=f, action="modified"))
            else:
                changes.append(FileChange(file=f, action="unchanged"))

        return changes

    # ── 阶段 2: 步骤匹配 ──

    def _match_steps(
        self, plan: Plan, changes: list[FileChange],
    ) -> tuple[int, int]:
        """匹配方案步骤与文件变更。"""
        total = len(plan.steps)
        if total == 0:
            return 0, 0

        # 构建非 "unchanged" 变更的文件集合
        effective_changes = {
            c.file for c in changes if c.action != "unchanged"
        }

        matched = 0
        for step in plan.steps:
            step_file = step.get("file", "")
            if not step_file:
                continue
            if step_file in effective_changes:
                matched += 1

        return matched, total

    # ── 阶段 5: 偏差计算 ──

    def _compute_deviation(
        self, changes: list[FileChange], target_files: set[str],
    ) -> float:
        """计算偏差分数：超出 target_files 的变更比例。"""
        effective = [c for c in changes if c.action != "unchanged"]
        if not effective:
            return 0.0
        unexpected = sum(1 for c in effective if c.file not in target_files)
        return unexpected / len(effective)

    # ── 阶段 6: 综合评分 ──

    def _compute_verdict(
        self,
        errors: list[str],
        matched_steps: int,
        total_steps: int,
        deviation_score: float,
    ) -> tuple[Verdict, bool]:
        """根据各阶段结果生成最终 verdict。"""
        # FAIL: 有错误 或 无步骤匹配
        if errors or matched_steps == 0:
            return Verdict.FAIL, False

        # PARTIAL: 部分步骤未匹配 或 偏差过大
        if matched_steps < total_steps or deviation_score > self.DEVIATION_PARTIAL_THRESHOLD:
            return Verdict.PARTIAL, False

        # PASS: 全部通过
        return Verdict.PASS, True
