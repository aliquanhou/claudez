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

ToolCallback = Callable[[str, dict, str], None]
MessageCallback = Callable[[str, str], None]
StreamCallback = Callable[[str], None]
ErrorCallback = Callable[[str, Exception], None]
ThinkingCallback = Callable[[str], None]


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
        """工具执行完成后回调 (name, args, result)"""
        self.on_tool_start: Callable[[str, dict], None] | None = None
        """工具开始执行前回调 (name, args) — 用于 UI 实时展示"""
        self.on_tool_output: Callable[[str, str], None] | None = None
        """工具实时输出回调 (tool_name, output_line) — bash stdout/stderr 逐行"""
        self.on_message: MessageCallback | None = None
        self.on_stream: StreamCallback | None = None
        self.on_error: ErrorCallback | None = None
        self.on_thinking: ThinkingCallback | None = None
        self.on_content_block: Callable[[str, dict], None] | None = None
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

        _log.info("agent_init  model=%s provider=%s permission=%s",
                  self.config["model"], self.config["provider"], pm.mode.value)

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

            system_prompt = self._build_prompt()
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
                    allowed, reason = check_permission(name)
                    if not allowed:
                        tool_tasks.append((name, args, cid, f"[权限拒绝] {reason}"))
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

                # ── 并发工具执行 ──
                #   is_concurrency_safe=True 的工具并行执行
                #   非并发安全工具串行执行（bash/write/edit 等需隔离操作）
                from concurrent.futures import ThreadPoolExecutor, as_completed
                from .tools import get_registry

                def _is_safe(name: str) -> bool:
                    tool = get_registry().get(name)
                    return tool.is_concurrency_safe if tool else False

                results: list[tuple[str, dict, str, str]] = []
                serial_tasks = []
                parallel_tasks = []

                for n, a, cid, pre in tool_tasks:
                    if pre is not None:
                        results.append((n, a, cid, pre))
                    elif _is_safe(n):
                        parallel_tasks.append((n, a, cid))
                    else:
                        serial_tasks.append((n, a, cid))

                # 并行执行并发安全工具
                if parallel_tasks:
                    with ThreadPoolExecutor(max_workers=min(8, len(parallel_tasks))) as pool:
                        fut_map = {}
                        for n, a, cid in parallel_tasks:
                            fut = pool.submit(_exec, n, a, cid)
                            fut_map[fut] = (n, a, cid)
                        for fut in as_completed(fut_map):
                            n, a, cid = fut_map[fut]
                            _t0 = time.time()
                            try:
                                r = fut.result()
                            except Exception as e:
                                r = f"[错误] {e}"
                            self.debug.log_tool_call(n, a, r, (time.time()-_t0)*1000, not r.startswith("[错误]"))
                            results.append((n, a, cid, r))

                # 串行执行非并发安全工具
                for n, a, cid in serial_tasks:
                    _t0 = time.time()
                    r = _exec(n, a, cid)
                    self.debug.log_tool_call(n, a, r, (time.time()-_t0)*1000, not r.startswith("[错误]"))
                    results.append((n, a, cid, r))

                # 按原始顺序排序（保证 session 消息序列正确）
                order = {(n, a, cid): i for i, (n, a, cid) in enumerate(
                    [(x[0], x[1], x[2]) for x in tool_tasks]
                )}
                results.sort(key=lambda x: order.get((x[0], x[1], x[2]), 999))

                # ★ 写入 session：必须成对出现 assistant(tc=[...]) + tool(...) + tool(...)
                #   生成的消息序列由 LLM 返回的同一组 tool_calls 保证完整性
                asst_tc = [{
                    "id": cid, "type": "function",
                    "function": {"name": n, "arguments": json.dumps(a, ensure_ascii=False)},
                } for n, a, cid, r in results]

                self.session.messages.append({
                    "role": "assistant", "content": response.content if response.content else None,
                    "tool_calls": asst_tc, "timestamp": time.time(),
                })
                for n, a, cid, r in results:
                    self.session.messages.append({
                        "role": "tool", "tool_call_id": cid, "content": str(r), "timestamp": time.time(),
                    })

                # 回调 + 错误追踪
                for n, a, cid, r in results:
                    if self.on_tool_call:
                        self.on_tool_call(n, a, r)
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

                if not self._running:
                    break
                continue

            # 无工具调用——最终回复
            if response.content:
                self.session.add_message("assistant", response.content)
                if self.on_message:
                    self.on_message("assistant", response.content)
            final_response = response.content
            break

        self.stats["total_duration_ms"] = (time.time() - self._start_time) * 1000
        self._running = False
        _log.info("agent_complete duration=%.0fms llm=%d tools=%d tokens=%d",
                  self.stats["total_duration_ms"], self.stats["llm_calls"],
                  self.stats["tool_calls"], self.stats["total_tokens"])
        return final_response if final_response else "[无响应]"

    # ── 上下文压缩 ──

    def _should_compress(self, messages: list[dict]) -> bool:
        """检查是否触发上下文压缩。"""
        if self.config.get("max_context_messages", 50) <= 0:
            return False
        ratio = len(messages) / self.config["max_context_messages"]
        return ratio >= self.config.get("context_compress_at", 0.85)

    def _compress_context(self, messages: list[dict]) -> list[dict]:
        """压缩上下文：按工具调用轮次分组，只保留首尾。

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

        # 保留第 0 条（第一个 user 消息 = 原始任务目标）
        keep = [messages[0]]

        # 将第 1 条之后的消息按 assistant(tool_calls) 分割为"轮次"
        rounds: list[list[dict]] = []
        current: list[dict] = []
        for m in messages[1:]:
            if m.get("tool_calls") and m.get("role") == "assistant":
                if current:
                    # 前面的 tool 响应归入上一轮
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
        context = PromptContext(
            user_id=self.session.id,
            tools=get_all_tools(),
            workflow_mode=self.config["workflow_mode"],
            constraints=self._build_constraints(),
            memories=self._search_memories(),
            project_info=self._get_project_info(),
            session_state=self.session.get_state() if self.config["enable_adaptations"] else None,
        )
        return self.prompt_builder.build(context)

    def _build_constraints(self) -> dict:
        return {
            "max_tool_calls": self.config["max_tool_calls_per_turn"],
            "tool_timeout": self.config["tool_timeout"],
        }

    def _search_memories(self) -> list[dict]:
        if not self.semantic_memory:
            return []
        recent = self.session.get_recent_messages(3)
        queries = [m["content"] for m in recent if m.get("content") and m["role"] == "user"]
        if not queries:
            return []
        return self.semantic_memory.search(queries[-1], n_results=self.config["memory_search_top_k"])

    def _get_project_info(self) -> dict | None:
        return None

    def set_project_info(self, info: dict):
        self._project_info = info

    def store_memory(self, content: str, mem_type: str = "conversation"):
        if self.semantic_memory:
            self.semantic_memory.store(content, {"type": mem_type})

    def _on_error(self, context: str, error: Exception):
        if self.on_error:
            self.on_error(context, error)

    def get_stats(self) -> dict:
        """获取运行统计。"""
        return {**self.stats}
