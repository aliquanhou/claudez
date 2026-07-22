"""core — ClaudeZ Agent 核心循环（升级版）。

参考 Claude Code 架构：
  - 结构性日志（structlog）
  - 上下文压缩策略
  - 工具调用统计
  - 流式推送
  - 错误分类与智能重试
"""

from __future__ import annotations

import json
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

from .prompt import DynamicPromptBuilder, PromptContext
from .providers import create_provider, LLMProvider, LLMResponse
from .session import Session, get_session, create_isolated_session
from .tools import get_registry, get_all_tools, execute_tool
from .tools.registry import set_stream_callback
from .tools.schema import ToolContext
from .memory import ShortTermMemory, SemanticMemory, get_semantic_memory
from .permissions import get_permission_manager, check_permission
from .debug_stream import DebugCollector

# ── 日志辅助（替代 structlog，零依赖） ──
import logging

_log = logging.getLogger("claudez.agent")
_ch = logging.StreamHandler()
_ch.setFormatter(logging.Formatter(
    "[%(levelname)s] %(name)s: %(message)s"
))
if not _log.handlers:
    _log.addHandler(_ch)
    _log.setLevel(logging.INFO)


# Cognition 层（v0.3.4）— 可选加载，失败不影响核心功能
try:
    from .cognition import (
        TaskManager, TaskPhase, ContextCompiler,
        IntentResonator, IntentSignal, BehavioralSnapshot,
        WorkspaceScanner,
    )
    _HAS_COGNITION = True
except ImportError as _e:
    _HAS_COGNITION = False
    _log.warning("cognition layer not available: %s", _e)

# Execution 层（v0.4.0）— 可选加载
try:
    from .execution import (
        PlanExecutor, ToolOrchestrator, PathValidator, FeedbackLoop,
    )
    from .cognition.execution_verifier import ExecutionVerifier as _EXEC_VERIFIER
    _HAS_EXECUTION = True
except ImportError as _ee:
    _HAS_EXECUTION = False
    _log.warning("execution layer not available: %s", _ee)


# ── 默认配置 ──

DEFAULT_CONFIG = {
    "provider": "deepseek",
    "model": "deepseek-chat",
    "max_tokens": 8192,
    "temperature": 0.0,
    "timeout": 3600,
    "tool_timeout": 60.0,
    "max_context_messages": 50,
    "workflow_mode": "agent",
    "enable_memory": True,
    "memory_search_top_k": 5,
    "max_tool_calls_per_turn": 25,
    "max_consecutive_errors": 5,
    "enable_adaptations": True,
    "max_retries": 3,
    "retry_base_delay_ms": 1000,
    "disable_thinking": True,       # DeepSeek: 关闭 thinking 模式
    "enable_caching": False,        # 上下文缓存
    "context_compress_at": 0.85,    # 上下文窗口 85% 满时触发压缩
    "permission_mode": "auto",      # auto | ask | deny
}


# ── 回调类型 ──

ToolCallback = Callable[[str, dict, str, float], None]
"""工具执行完成后回调 (name, args, result, duration_ms)"""
ToolStartCallback = Callable[[str, dict], None]
"""工具开始执行前回调 (name, args) — 用于 UI 实时展示"""
ToolOutputCallback = Callable[[str, str], None]
"""工具实时输出回调 (tool_name, output_line) — bash stdout/stderr 逐行"""
MessageCallback = Callable[[str, str], None]
StreamCallback = Callable[[str], None]
ErrorCallback = Callable[[str, Exception], None]
ThinkingCallback = Callable[[str], None]
ContentBlockCallback = Callable[[str, dict], None]
"""内容块回调 (block_type, block_data) — 实时收到每个完成的块"""


# ── Agent 核心 ──

class Agent:
    """ClaudeZ Agent 核心（升级版）。

    升级点：
      - 结构性日志记录每一步
      - 上下文窗口满时自动压缩
      - 工具调用统计
      - 流式文本推送
    """

    def __init__(self, config: dict | None = None, session: Session | None = None):
        self.config = {**DEFAULT_CONFIG, **(config or {})}
        self.session = session if session else get_session()
        self.short_memory = ShortTermMemory()
        self.semantic_memory = get_semantic_memory() if self.config["enable_memory"] else None
        self.prompt_builder = DynamicPromptBuilder()

        # LLM 提供商（带 DeepSeek 适配）
        self.provider = create_provider(self.config)
        self._setup_provider_callbacks()

        # 统计
        self.stats = {
            "llm_calls": 0,
            "tool_calls": 0,
            "tool_errors": 0,
            "context_compressions": 0,
            "total_tokens": 0,
            "start_time": 0.0,
            "total_duration_ms": 0.0,
        }

        # 回调
        self.on_tool_call: ToolCallback | None = None
        """工具执行完成后回调 (name, args, result, duration_ms)"""
        self.on_tool_start: ToolStartCallback | None = None
        """工具开始执行前回调 (name, args) — 用于 UI 实时展示"""
        self.on_tool_output: ToolOutputCallback | None = None
        """工具实时输出回调 (tool_name, output_line) — bash stdout/stderr 逐行"""
        self.on_message: MessageCallback | None = None
        self.on_stream: StreamCallback | None = None
        self.on_error: ErrorCallback | None = None
        self.on_thinking: ThinkingCallback | None = None
        self.on_content_block: ContentBlockCallback | None = None
        """内容块回调 (block_type, block_data) — 实时收到每个完成的块"""

        # 运行时状态
        self._running = False
        self._tool_round = 0
        self._consecutive_errors = 0
        self._call_history: list[tuple[str, str]] = []
        self._start_time = 0.0

        # 初始化权限管理器
        pm = get_permission_manager()
        pm.set_mode(self.config.get("permission_mode", "auto"))

        # 调试日志
        self.debug = DebugCollector(
            session_id=self.session.id,
            model=self.config["model"],
            version="2.1",
        )

        # Cognition v0.3.4 — 可选认知层
        if _HAS_COGNITION:
            self.task_manager = TaskManager()
            self.intent_resonator = IntentResonator(window_size=20)
            try:
                self.workspace_scanner = WorkspaceScanner(".")
                _log.info("cognition_init workspace=%s files=%d",
                          self.workspace_scanner.info.root_path,
                          self.workspace_scanner.info.file_count)
            except Exception:
                self.workspace_scanner = None
                _log.warning("cognition_init workspace scanner failed")
            self.context_compiler = ContextCompiler(max_workspace_files=10)
            self._cog_task_id = None
            _log.info("cognition_init complete")
        else:
            self.task_manager = None
            self.intent_resonator = None
            self.workspace_scanner = None
            self.context_compiler = None

        # Execution 层（v0.4.0）— 执行层初始化
        if _HAS_EXECUTION:
            self.path_validator = PathValidator(".")
            self.plan_executor = PlanExecutor(".")
            self.tool_orchestrator = ToolOrchestrator(timeout=30, max_retries=1)
            ev = _EXEC_VERIFIER()
            self.feedback_loop = FeedbackLoop(
                self.task_manager if _HAS_COGNITION else None,
                ev,
            )
            _log.info("execution_init complete")
        else:
            self.path_validator = None
            self.plan_executor = None
            self.tool_orchestrator = None
            self.feedback_loop = None

        _log.info("agent_init  model=%s provider=%s permission=%s cognition=%s execution=%s",
                  self.config["model"], self.config["provider"], pm.mode.value,
                  _HAS_COGNITION, _HAS_EXECUTION)

    def _setup_provider_callbacks(self):
        def stream_handler(chunk: str):
            if self.on_stream:
                self.on_stream(chunk)
        self.provider.on_stream = stream_handler

        def content_block_handler(block_type: str, block_data: dict):
            """Content block 到达时实时处理。"""
            if block_type == "tool_use":
                # 工具块完成 → 立即通知（UI 侧收到 tool_use_start）
                name = block_data.get("name", "")
                args = block_data.get("input", {})
                if self.on_content_block:
                    self.on_content_block(block_type, block_data)
            elif block_type == "text":
                if self.on_content_block:
                    self.on_content_block(block_type, block_data)
        self.provider.on_content_block = content_block_handler

    def set_workflow_mode(self, mode: str):
        if mode in ("chat", "research", "coding", "debug", "agent"):
            self.config["workflow_mode"] = mode
            _log.info("mode_switch mode=%s", mode)

    def stop(self):
        self._running = False

    def run(self, user_message: str) -> str:
        self._running = True
        self._tool_round = 0
        self._consecutive_errors = 0
        self._call_history = []

        # Cognition v0.3.4: 复用或创建任务 + 自动阶段推进
        if self.task_manager is not None:
            current = self.task_manager.get_current_task()
            if current is None:
                task = self.task_manager.create_task(user_message[:500])
                self._cog_task_id = task.task_id
                _log.info("cognition task created id=%s phase=%s",
                          task.task_id, task.current_phase.value)
            else:
                self._cog_task_id = current.task_id
            # 每轮递增 turn_count
            t = self.task_manager.get_current_task()
            if t:
                t.turn_count += 1

        # Cognition: 根据意图自动推进阶段
        if self.task_manager is not None and self.intent_resonator is not None:
            intent = self.intent_resonator.get_intent()
            if intent and self._cog_task_id:
                phase_map = {
                    "implementing": "executing",
                    "debugging": "analysis",
                    "refactoring": "planning",
                    "exploring": "analysis",
                    "reviewing": "verifying",
                }
                target = phase_map.get(intent.primary_intent.value)
                if target:
                    t = self.task_manager.get_current_task()
                    if t and t.current_phase.value == "intent_clarify":
                        from .cognition import TaskPhase
                        try:
                            new_phase = TaskPhase(target)
                            self.task_manager.transition_phase(self._cog_task_id, new_phase)
                            _log.info("cognition auto_transition %s -> %s (intent=%s)",
                                      t.current_phase.value, target, intent.primary_intent.value)
                        except Exception:
                            pass
        self._start_time = time.time()
        self.stats["start_time"] = self._start_time

        # 追加用户消息，不清除旧会话（保留上下文）
        self.session.add_message("user", user_message)
        _log.info("agent_run len=%d mode=%s", len(user_message), self.config["workflow_mode"])
        self.debug.log_decision(thought="开始处理用户请求", action="run",
                                phase="start", confidence=1.0)
        final_response = ""

        while self._running:
            elapsed = time.time() - self._start_time
            if elapsed > self.config["timeout"]:
                final_response = f"[超时] 运行超过 {self.config['timeout']} 秒"
                break

            # 从 session 取消息，触顶压缩
            messages = self.session.get_recent_messages(self.config["max_context_messages"])
            if self._should_compress(messages):
                messages = self._compress_context(messages)
            # 确保 messages 不为空
            if not messages:
                messages = [{"role": "user", "content": user_message, "timestamp": time.time()}]

            system_prompt = self._build_prompt()

            # Cognition v0.3.4: 每轮日志
            if self.intent_resonator is not None:
                intent = self.intent_resonator.get_intent()
                if intent:
                    _log.info("cognition intent=%s conf=%.2f urgency=%.2f",
                              intent.primary_intent.value, intent.confidence, intent.urgency)

            tools = get_all_tools()

            if self.on_thinking:
                self.on_thinking("思考中...")
            self.stats["llm_calls"] += 1
            _api_start = time.time()
            response = self.provider.chat_with_retry(
                system_prompt=system_prompt, messages=messages, tools=tools,
            )
            _api_dur = (time.time() - _api_start) * 1000
            inp = response.usage.get("input_tokens", 0) if response.usage else 0
            out = response.usage.get("output_tokens", 0) if response.usage else 0
            self.stats["total_tokens"] += inp + out
            self.debug.log_api_call(self.config["model"], response.stop_reason,
                inp, out, _api_dur,
                len(response.tool_calls) if response.tool_calls else 0,
                response.content[:100] if response.stop_reason == "error" else "")

            if response.stop_reason == "error":
                self._on_error("LLM 调用失败", Exception(response.content))
                final_response = response.content
                break

            # Cognition v0.3.4: 记录工具调用决策
            if self.task_manager is not None and self._cog_task_id:
                if response.tool_calls:
                    tool_names = [tc["name"] for tc in response.tool_calls]
                    self.task_manager.add_decision(
                        self._cog_task_id,
                        description=f"调用工具: {', '.join(tool_names)}",
                        rationale=response.content[:200] if response.content else "",
                    )

            if response.tool_calls:
                self._tool_round += 1
                if self._tool_round > self.config["max_tool_calls_per_turn"]:
                    final_response = f"[达到最大工具调用次数 {self.config['max_tool_calls_per_turn']}]"
                    break

                # 收集工具任务
                tool_tasks: list[tuple[str, dict, str, str | None]] = []
                for tc in response.tool_calls:
                    name = tc["name"]
                    args = tc.get("args", {})
                    cid = tc.get("id", "")
                    self._call_history.append((name, json.dumps(args, sort_keys=True)))
                    self.stats["tool_calls"] += 1
                    # v0.4.0: PathValidator
                    if _HAS_EXECUTION:
                        safe, reason = self._validate_tool_path(name, args)
                        if not safe:
                            tool_tasks.append((name, args, cid,
                                "[权限拒绝] 路径安全校验失败: " + reason))
                            if self.on_tool_start:
                                self.on_tool_start(name, args)
                            continue
                    allowed, reason = check_permission(name)
                    if not allowed:
                        tool_tasks.append((name, args, cid, "[权限拒绝] " + reason))
                        continue
                    if self.on_tool_start:
                        self.on_tool_start(name, args)
                    tool_tasks.append((name, args, cid, None))

                def _exec(n, a, cid):
                    def _sl(line: str):
                        if self.on_tool_output:
                            self.on_tool_output(n, line)
                    set_stream_callback(_sl)
                    try:
                        return execute_tool(n, a, self.config["tool_timeout"])
                    finally:
                        set_stream_callback(None)

                results: list[tuple[str, dict, str, str, float]] = []
                for n, a, cid, pre in tool_tasks:
                    if pre is not None:
                        results.append((n, a, cid, pre, 0.0))
                        continue
                    _t0 = time.time()
                    r = _exec(n, a, cid)
                    dur = (time.time() - _t0) * 1000
                    self.debug.log_tool_call(n, a, r, dur, not r.startswith("[错误]"))
                    results.append((n, a, cid, r, dur))

                # ★ 写入 session：必须成对出现 assistant(tc=[...]) + tool(...) + tool(...)
                #   生成的消息序列由 LLM 返回的同一组 tool_calls 保证完整性
                asst_tc = [{
                    "id": cid, "type": "function",
                    "function": {"name": n, "arguments": json.dumps(a, ensure_ascii=False)},
                } for n, a, cid, r, d in results]

                self.session.messages.append({
                    "role": "assistant", "content": response.content if response.content else None,
                    "tool_calls": asst_tc, "timestamp": time.time(),
                })
                for n, a, cid, r, d in results:
                    self.session.messages.append({
                        "role": "tool", "tool_call_id": cid, "content": str(r), "timestamp": time.time(),
                    })

                # 回调 + 错误追踪
                for n, a, cid, r, d in results:
                    if self.on_tool_call:
                        self.on_tool_call(n, a, r, d)
                    if r.startswith("[错误]") or r.startswith("[超时]") or r.startswith("[权限拒绝]"):
                        self.session.record_tool_error(n)
                        self._consecutive_errors += 1
                        self.stats["tool_errors"] += 1
                        if self._consecutive_errors >= self.config["max_consecutive_errors"]:
                            final_response = f"[连续错误]"
                            self._running = False
                            break
                    else:
                        self._consecutive_errors = 0

                # v0.4.0: FeedbackLoop
                if _HAS_EXECUTION and self.feedback_loop is not None:
                    try:
                        self._run_feedback_loop(results)
                    except Exception as fb_err:
                        _log.debug("feedback_loop error: %s", fb_err)

                if not self._running:
                    break
                continue

            # 无工具调用——最终回复
            if response.content:
                self.session.add_message("assistant", response.content)
                if self.on_message:
                    self.on_message("assistant", response.content)
                # ★ 短期记忆：记录本轮对话
                self.short_memory.add_note(f"用户: {user_message[:200]}", "conversation")
                self.short_memory.add_note(f"助手: {response.content[:200]}", "conversation")
            final_response = response.content
            break

        # ★ 语义记忆持久化：将本次对话存入长期记忆（带元数据）
        if self.semantic_memory:
            self.store_memory(f"用户: {user_message[:500]}", mem_type="user_query")
            if final_response and not final_response.startswith("["):
                self.store_memory(f"助手: {final_response[:500]}", mem_type="assistant_response")

        self.stats["total_duration_ms"] = (time.time() - self._start_time) * 1000
        self._running = False

        # Cognition v0.3.4: 任务结束日志
        if self.task_manager is not None:
            summary = self.task_manager.get_summary()
            _log.info("cognition complete summary=%s", summary.replace(chr(10), " | "))

        _log.info("agent_complete duration=%.0fms llm=%d tools=%d tokens=%d",
                  self.stats["total_duration_ms"], self.stats["llm_calls"],
                  self.stats["tool_calls"], self.stats["total_tokens"])
        return final_response if final_response else "[无响应]"

    # ── 上下文压缩 ──

    def _should_compress(self, messages: list[dict]) -> bool:
        """检查是否触发上下文压缩。

        策略：当消息数超过 max_context_messages 的 70% 时触发压缩。
        使用绝对阈值而非比例，因为 get_recent_messages 已截断。
        """
        threshold = self.config.get("max_context_messages", 50)
        if threshold <= 0:
            return False
        # 当消息数达到阈值的 70% 时触发压缩
        compress_at = int(threshold * self.config.get("context_compress_at", 0.85))
        return len(messages) >= compress_at

    def _compress_context(self, messages: list[dict]) -> list[dict]:
        """压缩上下文：按工具调用轮次分组，保留首尾。

        策略（参考 Claude Code 上下文管理）：
          - 保留第一条 user 消息（用户原始目标）
          - 将后续消息按 assistant(tool_calls) 分组为"工具轮次"
          - 保留最近的 N 个完整轮次
          - 丢弃中间的旧轮次
        """
        self.stats["context_compressions"] += 1
        _log.info("context_compress before=%d compress_count=%d",
                  len(messages), self.stats["context_compressions"])

        if len(messages) < 10:
            return messages

        # 找到第一条 user 消息作为锚点
        first_user_idx = -1
        for i, m in enumerate(messages):
            if m.get("role") == "user":
                first_user_idx = i
                break

        if first_user_idx < 0:
            # 没有 user 消息，直接返回全部
            return messages

        keep = [messages[first_user_idx]]

        # 将锚点之后的消息按 assistant(tool_calls) 分割为"轮次"
        rounds: list[list[dict]] = []
        current: list[dict] = []
        for m in messages[first_user_idx + 1:]:
            if m.get("tool_calls") and m.get("role") == "assistant":
                if current:
                    rounds.append(current)
                current = [m]
            else:
                current.append(m)
        if current:
            rounds.append(current)

        # 保留最近的 70% 轮次（至少 1 个）
        if len(rounds) > 1:
            keep_count = max(1, int(len(rounds) * 0.7))
            keep_rounds = rounds[-keep_count:]
        else:
            keep_rounds = rounds

        for r in keep_rounds:
            keep.extend(r)

        _log.info("context_compressed before=%d after=%d (kept %d/%d rounds)",
                  len(messages), len(keep), len(keep_rounds), len(rounds))
        return keep

    # ── 提示词构建 ──

    def _build_prompt(self) -> str:
        # 构建短期记忆上下文
        short_memories = {
            "facts": dict(self.short_memory.facts),
            "notes": self.short_memory.get_notes(limit=3),
            "tasks": list(self.short_memory.task_stack),
        }

        # Cognition v0.3.4: 编译认知上下文 (bridge)
        custom_sections = []
        if self.context_compiler is not None and self.task_manager is not None:
            intent_vector = None
            if self.intent_resonator is not None:
                intent_vector = self.intent_resonator.get_intent()
            workspace_info = None
            if self.workspace_scanner is not None:
                try:
                    workspace_info = self.workspace_scanner.get_info()
                    _log.debug("cognition workspace info: %s files=%d",
                               workspace_info.root_path, workspace_info.file_count)
                except Exception as e:
                    _log.warning("cognition workspace scan failed: %s", e)
            compiled = self.context_compiler.compile(
                self.task_manager,
                intent_vector=intent_vector,
                workspace_info=workspace_info,
            )
            prompt_text = compiled.to_prompt()
            if prompt_text:
                custom_sections.append(("认知上下文", prompt_text))
                _log.debug("cognition context compiled len=%d", len(prompt_text))

        context = PromptContext(
            user_id=self.session.id,
            tools=get_all_tools(),
            workflow_mode=self.config["workflow_mode"],
            constraints=self._build_constraints(),
            memories=self._search_memories(),
            short_memories=short_memories,
            project_info=self._get_project_info(),
            session_state=self.session.get_state() if self.config["enable_adaptations"] else None,
            custom_sections=custom_sections,
        )
        return self.prompt_builder.build(context)

    def _build_constraints(self) -> dict:
        return {
            "max_tool_calls": self.config["max_tool_calls_per_turn"],
            "tool_timeout": self.config["tool_timeout"],
        }

    # -- Execution layer helpers (v0.4.0) --

    def _validate_tool_path(self, tool_name: str, args: dict) -> tuple[bool, str]:
        if self.path_validator is None:
            return True, ""
        if tool_name in ("write", "edit", "delete", "read"):
            fp = args.get("file_path", "")
            if fp:
                return self.path_validator.validate(fp)
        return True, ""

    def _run_feedback_loop(self, tool_results: list) -> None:
        if self.feedback_loop is None or self.task_manager is None:
            return
        if not _HAS_COGNITION:
            return
        after_info = None
        if self.workspace_scanner is not None:
            try:
                after_info = self.workspace_scanner.get_info()
            except Exception:
                pass
        from .cognition.plan_verifier import Plan as PVPlan, PlanStep
        task = self.task_manager.get_current_task()
        if not task:
            return
        plan = PVPlan(
            id="exec-" + str(self._tool_round),
            description=task.user_goal[:100],
            steps=[PlanStep(action="execute", file="", description=task.user_goal[:100])],
            target_files=[],
            estimated_effort=0,
        )
        logs = [r[3] for r in tool_results if r[3]]
        from .cognition.execution_verifier import WorkspaceSnapshot as EVSnap
        before_ws = EVSnap(root_path=".")
        after_ws = EVSnap(
            root_path=".",
            files=after_info.files if after_info else [],
            file_count=after_info.file_count if after_info else 0,
        )
        self.feedback_loop.process(plan, before_ws, after_ws, logs)

    def _search_memories(self) -> list[dict]:
        if not self.semantic_memory:
            return []
        recent = self.session.get_recent_messages(5)
        queries = [m["content"] for m in recent if m.get("content") and m["role"] == "user"]
        if not queries:
            return []
        # 合并多条用户消息作为查询，提高召回率
        combined_query = " ".join(queries[-3:])
        return self.semantic_memory.search(combined_query, n_results=self.config["memory_search_top_k"])

    def _get_project_info(self) -> dict | None:
        return None

    def set_project_info(self, info: dict):
        self._project_info = info

    def store_memory(self, content: str, mem_type: str = "conversation"):
        if self.semantic_memory:
            self.semantic_memory.store(content, {"type": mem_type, "source": "agent"})

    def _on_error(self, context: str, error: Exception):
        if self.on_error:
            self.on_error(context, error)

    def get_stats(self) -> dict:
        """获取运行统计。"""
        return {**self.stats}
