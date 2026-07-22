"""
cognition/ - ForgeX 认知层

铁三角架构：
- TaskContext: 显式状态（我们在做什么）
- IntentResonator: 隐式意图（你真正想干什么）
- PlanVerifier: 方案验证（是否靠谱）
- ExecutionVerifier: 执行验证（结果是否符合预期）
- ContextCompiler: 编译为结构化 Prompt
- WorkspaceScanner: 工作区扫描

命名说明：
- plan_verifier.Plan: 方案评估用（外部接口）
- execution_verifier.Plan: 内部用（不对外导出）
- 外部使用统一从 plan_verifier 导入 Plan 和 Verdict
"""

from .task_context import (
    TaskPhase, Decision, Phase, WorkspaceSnapshot,
    TaskContext, IntentData, TaskManager,
)

from .workspace_scanner import WorkspaceScanner, WorkspaceInfo

from .intent_resonator import (
    IntentResonator, IntentSignal, BehavioralSnapshot, IntentVector,
)

from .plan_verifier import (
    PlanVerifier, Plan, PlanStep, VerificationReport, Verdict,
)

from .execution_verifier import (
    ExecutionVerifier, ExecutionReport, FileChange,
)

from .context_compiler import ContextCompiler, CompiledContext

__all__ = [
    # TaskContext
    "TaskPhase", "Decision", "Phase", "WorkspaceSnapshot",
    "TaskContext", "IntentData", "TaskManager",

    # WorkspaceScanner
    "WorkspaceScanner", "WorkspaceInfo",

    # IntentResonator
    "IntentResonator", "IntentSignal", "BehavioralSnapshot", "IntentVector",

    # PlanVerifier (对外接口)
    "PlanVerifier", "Plan", "PlanStep", "VerificationReport", "Verdict",

    # ExecutionVerifier
    "ExecutionVerifier", "ExecutionReport", "FileChange",

    # ContextCompiler
    "ContextCompiler", "CompiledContext",
]
