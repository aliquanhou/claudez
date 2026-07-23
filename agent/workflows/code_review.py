"""Code Review Workflow — 基于 git diff 的结构化代码审查。

工作流:
  1. 读取 git diff (或指定文件路径)
  2. 用 Verifier 角色的 Agent 逐文件审查
  3. 生成结构化审查报告 (file → line → severity → comment)
  4. 输出 Markdown 报告

依赖:
  - agent/roles: Verifier 角色（只读权限）
  - agent/pipeline: PipelineTask 状态追踪
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

_log = logging.getLogger("claudez.workflows")


@dataclass
class ReviewComment:
    """单条审查评论。"""
    file: str
    line: int
    severity: str        # "critical" | "warning" | "info"
    category: str        # "correctness" | "security" | "style" | "performance" | "suggestion"
    message: str
    suggestion: str = ""

    def to_markdown(self) -> str:
        icon = {"critical": "🔴", "warning": "🟡", "info": "🔵"}
        return (
            f"{icon.get(self.severity, '•')} **{self.file}:{self.line}** "
            f"[{self.severity}/{self.category}]\n"
            f"  {self.message}\n"
            f"  _{self.suggestion}_" if self.suggestion else ""
        )


@dataclass
class ReviewReport:
    """完整审查报告。"""
    target: str                    # git diff ref 或文件路径
    comments: list[ReviewComment] = field(default_factory=list)
    files_reviewed: list[str] = field(default_factory=list)
    summary: str = ""
    created_at: float = field(default_factory=time.time)
    duration_ms: float = 0.0

    @property
    def critical_count(self) -> int:
        return sum(1 for c in self.comments if c.severity == "critical")

    @property
    def warning_count(self) -> int:
        return sum(1 for c in self.comments if c.severity == "warning")

    def to_markdown(self) -> str:
        lines = [
            f"# Code Review Report: {self.target}",
            f"",
            f"**Summary**: {self.summary}",
            f"**Files reviewed**: {len(self.files_reviewed)}",
            f"**Comments**: {len(self.comments)} "
            f"(🔴{self.critical_count} 🟡{self.warning_count} 🔵{len(self.comments)-self.critical_count-self.warning_count})",
            f"**Duration**: {self.duration_ms:.0f}ms",
            f"",
            f"---",
        ]
        for comment in self.comments:
            lines.append(comment.to_markdown())
            lines.append("")
        return "\n".join(lines)


class CodeReviewWorkflow:
    """代码审查工作流。

    Usage:
        reviewer = CodeReviewWorkflow()
        report = reviewer.review(target="HEAD~1")   # git diff
        report = reviewer.review(target="src/main.py")  # 单文件
        print(report.to_markdown())
    """

    def __init__(self, config: dict | None = None):
        self.config = config or {}

    def review(self, target: str = "HEAD") -> ReviewReport:
        """执行代码审查。

        Args:
            target: git diff 引用 (如 "HEAD", "HEAD~1") 或文件路径

        Returns:
            ReviewReport: 结构化审查报告
        """
        t0 = time.time()
        report = ReviewReport(target=target)

        # 1. 收集变更文件
        if os.path.isdir(".git") or os.path.exists(".git"):
            files = self._get_git_diff_files(target)
        else:
            files = [target] if os.path.exists(target) else []

        if not files:
            report.summary = "No changes to review."
            report.duration_ms = (time.time() - t0) * 1000
            return report

        report.files_reviewed = files

        # 2. 逐文件审查
        for filepath in files:
            if not os.path.exists(filepath):
                continue
            try:
                with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                comments = self._analyze_file(filepath, content)
                report.comments.extend(comments)
            except Exception as e:
                _log.warning("review_skip file=%s error=%s", filepath, e)

        # 3. 生成摘要
        if report.critical_count > 0:
            report.summary = (
                f"发现 {report.critical_count} 个严重问题和 "
                f"{report.warning_count} 个警告，建议修复后再合并。"
            )
        elif report.warning_count > 0:
            report.summary = (
                f"发现 {report.warning_count} 个警告，建议审查后合并。"
            )
        else:
            report.summary = f"审查通过，{len(report.comments)} 条改进建议。"

        report.duration_ms = (time.time() - t0) * 1000
        _log.info("review_complete files=%d comments=%d critical=%d duration=%.0fms",
                  len(files), len(report.comments), report.critical_count, report.duration_ms)
        return report

    def _get_git_diff_files(self, ref: str) -> list[str]:
        """获取 git diff 变更文件列表。"""
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", ref],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                raw = result.stdout.strip()
                return [f.strip() for f in raw.split("\n") if f.strip()]
        except Exception as e:
            _log.warning("git_diff_error ref=%s %s", ref, e)
        return []

    def _analyze_file(self, filepath: str, content: str) -> list[ReviewComment]:
        """分析单个文件，返回审查评论列表。

        使用确定性规则（0-LLM）进行初步扫描：
          - 硬编码敏感信息
          - TODO/FIXME 标记
          - 过长行
          - 空 except
          - print debug 语句
        """
        comments: list[ReviewComment] = []
        lines = content.split("\n")

        ext = os.path.splitext(filepath)[1].lower()

        for i, line in enumerate(lines, 1):
            stripped = line.strip()

            # 硬编码密钥/密码
            if any(kw in stripped.lower() for kw in ["password=", "api_key=", "secret=", "token="]):
                if "example" not in stripped.lower():
                    comments.append(ReviewComment(
                        file=filepath, line=i, severity="critical",
                        category="security",
                        message="可能包含硬编码凭证。",
                        suggestion="使用环境变量或密钥管理服务。",
                    ))

            # TODO / FIXME
            if stripped.startswith("#") or stripped.startswith("//") or stripped.startswith("/*"):
                if "todo" in stripped.lower():
                    comments.append(ReviewComment(
                        file=filepath, line=i, severity="info",
                        category="suggestion",
                        message="遗留 TODO 标记。",
                        suggestion="评估是否需要立即处理。",
                    ))
                if "fixme" in stripped.lower():
                    comments.append(ReviewComment(
                        file=filepath, line=i, severity="warning",
                        category="correctness",
                        message="遗留 FIXME 标记，可能包含已知问题。",
                        suggestion="审查并修复后再提交。",
                    ))

            # 空 except
            if "except:" in stripped or "except Exception:" in stripped:
                # 检查下一行是否只是 pass
                if i < len(lines) and lines[i].strip() == "pass":
                    comments.append(ReviewComment(
                        file=filepath, line=i, severity="warning",
                        category="correctness",
                        message="空的 except 块会静默吞掉所有异常。",
                        suggestion="至少记录异常日志。",
                    ))

            # 超长行 (Python/JS)
            if ext in (".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rs"):
                if len(stripped) > 120:
                    comments.append(ReviewComment(
                        file=filepath, line=i, severity="info",
                        category="style",
                        message=f"行过长 ({len(stripped)} 字符)。",
                        suggestion="考虑换行以提升可读性。",
                    ))

            # print debug
            if ext in (".py", ".js", ".ts") and stripped.startswith("print("):
                comments.append(ReviewComment(
                    file=filepath, line=i, severity="info",
                    category="suggestion",
                    message="调试用 print 语句。",
                    suggestion="考虑替换为日志框架。",
                ))

        return comments
