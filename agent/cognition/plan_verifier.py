"""Plan Verifier — 验证方案是否靠谱：完整性、依赖冲突、复杂度评估。

确定性输出：相同输入 → 相同输出。
0 LLM 依赖。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Optional
from enum import Enum


class Verdict(Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


@dataclass
class PlanStep:
    """方案中的一个步骤。"""
    action: str                    # "edit", "create", "delete", "execute"
    file: str                      # 目标文件
    description: str               # 步骤描述
    dependencies: list[str] = field(default_factory=list)  # 依赖的步骤id


@dataclass
class Plan:
    """一个候选方案。"""
    id: str
    description: str
    steps: list[PlanStep]
    target_files: list[str] = field(default_factory=list)
    estimated_effort: int = 0      # 分钟


@dataclass
class VerificationReport:
    """方案验证报告。"""
    verdict: Verdict               # PASS / WARN / FAIL
    score: int                     # 0-100
    issues: list[str] = field(default_factory=list)      # 致命问题
    warnings: list[str] = field(default_factory=list)    # 潜在风险
    suggestions: list[str] = field(default_factory=list) # 改进建议
    metrics: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> str:
        """人类可读摘要。"""
        status_icon = {"pass": "PASS", "warn": "WARN", "fail": "FAIL"}
        status = status_icon.get(self.verdict.value, "?")
        parts = [
            f"[{status}] Score: {self.score}/100",
            f"         Issues: {len(self.issues)}",
            f"         Warnings: {len(self.warnings)}",
            f"         Suggestions: {len(self.suggestions)}",
        ]
        for label, items in [("Issues", self.issues),
                              ("Warnings", self.warnings),
                              ("Suggestions", self.suggestions)]:
            if items:
                parts.append(f"  {label}:")
                for item in items[:5]:
                    parts.append(f"    - {item}")
                if len(items) > 5:
                    parts.append(f"    ... and {len(items) - 5} more")
        return "\n".join(parts)


class PlanVerifier:
    """方案验证器 — 确定性规则引擎。

    验证维度：
      1. 完整性（步骤为空 → FAIL）
      2. 文件存在性（目标文件不在工作区 → 警告）
      3. 依赖冲突（两个步骤修改同一文件 → 警告）
      4. 复杂度（步骤 > 10 → 扣分）
      5. 范围完整性（无文件修改 → 警告）
      6. 工作量评估（估计 > 60min → 扣分）
    """

    # ── 分数常量 ──
    BASE_SCORE = 100
    PENALTY_STEPS_OVER_10 = 10
    PENALTY_EFFORT_OVER_60 = 5
    WARN_STEP_THRESHOLD = 10
    WARN_EFFORT_THRESHOLD = 60  # 分钟

    def __init__(self) -> None:
        self._known_files: set[str] | None = None

    # ── 公共接口 ──

    def set_known_files(self, files: list[str]) -> None:
        """注入工作区文件列表（来自 WorkspaceScanner）。"""
        self._known_files = set(files)

    def verify(self, plan: Plan) -> VerificationReport:
        """验证单个方案，返回验证报告。"""
        issues: list[str] = []
        warnings: list[str] = []
        suggestions: list[str] = []
        metrics: dict[str, Any] = {}
        score = self.BASE_SCORE

        # 1. 步骤为空检查（致命）
        if not plan.steps:
            issues.append("方案没有任何步骤")
            return VerificationReport(
                verdict=Verdict.FAIL,
                score=0,
                issues=issues,
                warnings=warnings,
                suggestions=["请至少定义一个操作步骤"],
                metrics={"step_count": 0},
            )

        step_count = len(plan.steps)
        metrics["step_count"] = step_count

        # 2. 依赖冲突检测：两个步骤修改同一文件
        file_action_map: dict[str, list[int]] = {}
        for i, step in enumerate(plan.steps):
            if step.file:
                file_action_map.setdefault(step.file, []).append(i)

        for file_path, step_indices in file_action_map.items():
            if len(step_indices) > 1:
                conflict = step_indices
                warnings.append(
                    f"文件 {file_path} 被多个步骤修改（步骤 {[i + 1 for i in conflict]}），"
                    "可能导致冲突"
                )

        metrics["file_conflicts"] = sum(
            1 for idx_list in file_action_map.values() if len(idx_list) > 1
        )

        # 3. 目标文件存在性检查（如果注入了已知文件列表）
        if self._known_files is not None and plan.target_files:
            missing = [f for f in plan.target_files if f not in self._known_files]
            if missing:
                for f in missing:
                    warnings.append(f"目标文件 {f} 不在当前工作区中")
                metrics["missing_files"] = len(missing)

        # 4. 步骤数 > 10 → 降分
        if step_count > self.WARN_STEP_THRESHOLD:
            score -= self.PENALTY_STEPS_OVER_10
            warnings.append(
                f"方案包含 {step_count} 个步骤，超过 {self.WARN_STEP_THRESHOLD} 个阈值，"
                "建议拆分为多个子方案"
            )

        # 5. 无文件修改警告：方案有步骤但未指定任何文件
        steps_with_files = sum(1 for s in plan.steps if s.file)
        if steps_with_files == 0:
            suggestions.append("方案中的步骤未指定目标文件，考虑添加 file 字段")
            metrics["steps_without_file"] = step_count

        # 6. 估计时间 > 60 分钟 → 降分
        if plan.estimated_effort > self.WARN_EFFORT_THRESHOLD:
            score -= self.PENALTY_EFFORT_OVER_60
            suggestions.append(
                f"估计耗时 {plan.estimated_effort} 分钟，建议拆分为多个独立方案"
            )
        metrics["estimated_effort"] = plan.estimated_effort
        metrics["target_file_count"] = len(plan.target_files)

        # 7. 重复依赖检测
        for i, step in enumerate(plan.steps):
            seen = set()
            for dep in step.dependencies:
                if dep in seen:
                    warnings.append(f"步骤 {i + 1} 包含重复依赖 {dep}")
                seen.add(dep)

        # 8. 额外建议
        if not plan.target_files:
            suggestions.append("考虑添加 target_files 以明确修改范围")

        if len(plan.target_files) > 20:
            warnings.append(
                f"方案涉及 {len(plan.target_files)} 个文件，建议缩小修改范围"
            )

        # ── 确定最终 verdict ──
        final_verdict = Verdict.PASS
        if issues:
            final_verdict = Verdict.FAIL
        elif warnings:
            final_verdict = Verdict.WARN

        # 确保 score 在 0-100 范围内
        score = max(0, min(100, score))

        return VerificationReport(
            verdict=final_verdict,
            score=score,
            issues=issues,
            warnings=warnings,
            suggestions=suggestions,
            metrics=metrics,
        )

    def compare(self, plans: list[Plan]) -> list[tuple[Plan, VerificationReport]]:
        """验证多个方案，返回按 score 降序排序的结果。"""
        results = [(p, self.verify(p)) for p in plans]
        results.sort(key=lambda x: x[1].score, reverse=True)
        return results
