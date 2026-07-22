"""providers/base — LLM 提供商抽象层。

文档对齐：统一接口 + 指数退避重试 + 流式支持 + DeepSeek 特殊适配

设计：
  - LLMProvider 抽象基类
  - 支持 Anthropic Claude / OpenAI / DeepSeek
  - 统一调用接口
  - 自动重试（指数退避）
  - 流式响应支持（chunk 回调）
  - DeepSeek thinking 模式控制
  - 上下文缓存（prefix caching）
  - 错误分类与重试策略
"""

from __future__ import annotations

import json
import logging
import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


_log = logging.getLogger("claudez.provider")


# ── 常量 ──

DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BASE_DELAY = 1.0  # 秒
DEFAULT_RETRY_MAX_DELAY = 30.0  # 秒

# 流式停滞检测
STALL_PASSIVE_TIMEOUT = 30.0   # 30s 无任何事件 → 被动超时
STALL_ACTIVE_TIMEOUT = 90.0    # 90s 总超时 → 主动终止

# 可重试的 HTTP 状态码
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


# ── 错误分类 ──

class ErrorCategory(str, Enum):
    """LLM API 错误分类。"""
    TRANSIENT = "transient"           # 可重试（网络、限流、服务端）
    RATE_LIMIT = "rate_limit"         # 限流（需等待更久）
    AUTH = "auth"                     # 认证错误（不可重试）
    INVALID_REQUEST = "invalid_request"  # 请求格式错误（不可重试）
    CONTEXT_LENGTH = "context_length" # 上下文超长（需压缩后重试）
    UNKNOWN = "unknown"               # 未知


def classify_error(exception: Exception) -> ErrorCategory:
    """对 API 错误进行分类。"""
    err_str = str(exception).lower()

    # 上下文超长
    if any(x in err_str for x in [
        "context_length", "max_tokens", "too long", "too many tokens",
        "maximum context", "token_limit",
    ]):
        return ErrorCategory.CONTEXT_LENGTH

    # 认证错误
    if any(x in err_str for x in [
        "401", "402", "403", "unauthorized", "forbidden",
        "invalid_api_key", "authentication", "permission",
        "api key", "invalid key",
    ]):
        return ErrorCategory.AUTH

    # 请求格式错误
    if any(x in err_str for x in [
        "400", "422", "invalid_request", "invalid_parameter",
        "bad request", "validation", "parse error",
        "tool_call_id", "missing field",
    ]):
        return ErrorCategory.INVALID_REQUEST

    # 限流
    if any(x in err_str for x in [
        "429", "rate limit", "too many requests", "quota",
    ]):
        return ErrorCategory.RATE_LIMIT

    # 服务端/网络错误（可重试）
    if any(x in err_str for x in [
        "500", "502", "503", "504", "service",
        "timeout", "connection", "reset", "eof",
        "unavailable", "internal server", "bad gateway",
        "temporary", "overloaded",
    ]):
        return ErrorCategory.TRANSIENT

    return ErrorCategory.UNKNOWN


def should_retry(exception: Exception) -> bool:
    """判断异常是否可重试。"""
    cat = classify_error(exception)
    return cat in (ErrorCategory.TRANSIENT, ErrorCategory.RATE_LIMIT)


def exponential_backoff(attempt: int, base_delay: float = DEFAULT_RETRY_BASE_DELAY,
                        max_delay: float = DEFAULT_RETRY_MAX_DELAY) -> float:
    """计算指数退避延迟（带抖动）。"""
    delay = min(base_delay * (2 ** attempt), max_delay)
    jitter = random.uniform(0, delay * 0.1)
    return delay + jitter


# ── 响应类型 ──

@dataclass
class LLMResponse:
    """LLM 调用的统一响应。"""
    content: str = ""
    """文本回复内容"""
    tool_calls: list[dict] | None = None
    """工具调用列表，每项为 {"name": str, "args": dict}"""
    stop_reason: str = "end_turn"
    """停止原因：end_turn | tool_use | max_tokens | error"""
    usage: dict | None = None
    """Token 使用统计"""
    model: str = ""
    """实际使用的模型"""
    raw: Any = None
    """原始响应"""
    cached: bool = False
    """是否命中缓存"""


# ── 抽象基类 ──

class LLMProvider(ABC):
    """LLM 提供商抽象基类。"""

    def __init__(self, config: dict):
        self.config = config
        self.api_key = config.get("api_key", "")
        self.model = config.get("model", "")
        self.max_tokens = config.get("max_tokens", 4096)
        self.temperature = config.get("temperature", 0.0)
        self.max_retries = config.get("max_retries", DEFAULT_MAX_RETRIES)
        self.retry_base_delay = config.get("retry_base_delay_ms", DEFAULT_RETRY_BASE_DELAY * 1000) / 1000

        # DeepSeek 特殊配置
        self.disable_thinking = config.get("disable_thinking", True)
        self.enable_caching = config.get("enable_caching", False)
        self.cache_prefix: list[str] = []

        # API 调用超时（秒），防止请求挂起
        self.api_timeout = config.get("api_timeout", 30.0)

        # 流式回调
        self.on_stream: Callable[[str], None] | None = None

        # 内容块回调（Claude Code 逐块 yield 模式）
        #   on_content_block("text", {"content": "..."})
        #   on_content_block("tool_use", {"name": "...", "input": {...}})
        #   on_content_block("thinking", {"content": "..."})
        self.on_content_block: Callable[[str, dict], None] | None = None

    @abstractmethod
    def chat(self, system_prompt: str, messages: list[dict],
             tools: list[dict] | None = None) -> LLMResponse:
        ...

    def chat_with_retry(self, system_prompt: str, messages: list[dict],
                        tools: list[dict] | None = None) -> LLMResponse:
        """带智能重试的对话请求。"""
        last_error = None
        last_category = ErrorCategory.UNKNOWN

        for attempt in range(self.max_retries + 1):
            try:
                return self.chat(system_prompt, messages, tools)
            except Exception as e:
                last_error = e
                last_category = classify_error(e)

                # 上下文超长 → 尝试压缩后重试
                if last_category == ErrorCategory.CONTEXT_LENGTH:
                    compressed = self._compress_messages(messages)
                    if compressed != messages:
                        try:
                            return self.chat(system_prompt, compressed, tools)
                        except Exception:
                            pass

                if attempt < self.max_retries and should_retry(e):
                    delay = exponential_backoff(attempt, self.retry_base_delay)
                    if last_category == ErrorCategory.RATE_LIMIT:
                        delay *= 2  # 限流加倍等待
                    time.sleep(delay)
                    continue

                return LLMResponse(
                    content=f"[API 错误] 重试 {attempt} 次后失败[{last_category.value}]: {e}",
                    stop_reason="error",
                    usage={"error_category": last_category.value},
                )

        return LLMResponse(
            content=f"[API 错误] {last_error}",
            stop_reason="error",
        )

    def _compress_messages(self, messages: list[dict]) -> list[dict]:
        """消息压缩策略：丢弃最旧的 tool 结果，保留对话结构。"""
        if len(messages) < 10:
            return messages

        # 移除最古老的 tool 消息对（保留 user/assistant 结构）
        compressed = []
        tool_results_removed = 0
        for msg in messages:
            if msg.get("role") == "tool" and tool_results_removed < len(messages) // 4:
                tool_results_removed += 1
                continue
            compressed.append(msg)

        # 如果压缩比例不够，移除最旧的 user/assistant 对
        if tool_results_removed == 0:
            compressed = compressed[-int(len(compressed) * 0.75):]

        return compressed

    def set_cache_prefix(self, texts: list[str]):
        """设置上下文缓存前缀（用于 DeepSeek prefix caching）。"""
        self.cache_prefix = texts
        self.enable_caching = bool(texts)

    @abstractmethod
    def name(self) -> str:
        ...


# ── Anthropic Claude ──

class AnthropicProvider(LLMProvider):
    """Anthropic Claude API 提供商。"""

    def name(self) -> str:
        return "Anthropic Claude"

    def chat(self, system_prompt: str, messages: list[dict],
             tools: list[dict] | None = None) -> LLMResponse:
        try:
            import anthropic
        except ImportError:
            return LLMResponse(
                content="[错误] 需要安装 anthropic 包: pip install anthropic",
                stop_reason="error",
            )

        client = anthropic.Anthropic(api_key=self.api_key, timeout=self.api_timeout)

        api_messages = []
        for msg in messages:
            role = msg["role"]
            if role == "system":
                continue
            entry = {"role": role}
            if msg.get("content") is not None:
                entry["content"] = msg["content"]
            if "tool_calls" in msg:
                entry["tool_calls"] = msg["tool_calls"]
            if "tool_call_id" in msg:
                entry["tool_call_id"] = msg["tool_call_id"]
            api_messages.append(entry)

        kwargs = {
            "model": self.model,
            "system": system_prompt,
            "messages": api_messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }

        if tools:
            kwargs["tools"] = tools

        try:
            if self.on_stream:
                kwargs["stream"] = True
                return self._chat_stream(client, **kwargs)
            else:
                response = client.messages.create(**kwargs)
                return self._parse_response(response)
        except Exception as e:
            return LLMResponse(content=f"[API 错误] {e}", stop_reason="error")

    def _chat_stream(self, client, **kwargs):
        content = ""
        tool_calls = []
        last_event_time = time.time()
        stall_active_start = time.time()
        with client.messages.create(**kwargs) as stream:
            for event in stream:
                now = time.time()

                # 被动超时：距上次事件超过 30s → 网络停滞
                if now - last_event_time > STALL_PASSIVE_TIMEOUT:
                    raise TimeoutError(
                        f"流式响应被动超时 {STALL_PASSIVE_TIMEOUT}s（距上次事件）")
                last_event_time = now

                if event.type == "content_block_delta":
                    if event.delta.type == "text_delta":
                        chunk = event.delta.text
                        content += chunk
                        if self.on_stream:
                            self.on_stream(chunk)
                elif event.type == "content_block_start":
                    if event.block.type == "tool_use":
                        tool_calls.append({"name": event.block.name, "args": {}})

                # 主动超时：90s 总耗时上限
                if now - stall_active_start > STALL_ACTIVE_TIMEOUT:
                    raise TimeoutError(
                        f"流式响应主动超时 {STALL_ACTIVE_TIMEOUT}s（总耗时）")
        return LLMResponse(content=content, stop_reason="end_turn", model=kwargs.get("model", ""))

    def _parse_response(self, response) -> LLMResponse:
        content = ""
        tool_calls = []
        for block in response.content:
            if block.type == "text":
                content += block.text
            elif block.type == "tool_use":
                tool_calls.append({
                    "name": block.name,
                    "args": block.input if hasattr(block, 'input') else {},
                })
        return LLMResponse(
            content=content,
            tool_calls=tool_calls if tool_calls else None,
            stop_reason=response.stop_reason or "end_turn",
            usage={"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens},
            model=response.model, raw=response,
        )


# ── OpenAI / DeepSeek ──

class OpenAIProvider(LLMProvider):
    """OpenAI 兼容 API 提供商（也支持 DeepSeek 等）。

    针对 DeepSeek 的特殊适配：
      - thinking 模式可关闭（节省 token）
      - 上下文缓存（prefix caching）
      - 错误分类与精细重试
    """

    def __init__(self, config: dict):
        super().__init__(config)
        self.base_url = config.get("base_url", "https://api.openai.com/v1")
        self._supports_prefix_cache = "deepseek" in self.base_url.lower()

    def name(self) -> str:
        return f"OpenAI ({self.base_url})"

    def chat(self, system_prompt: str, messages: list[dict],
             tools: list[dict] | None = None) -> LLMResponse:
        try:
            from openai import OpenAI
        except ImportError:
            return LLMResponse(
                content="[错误] 需要安装 openai 包: pip install openai",
                stop_reason="error",
            )

        client = OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=self.api_timeout)

        # 构建消息（保留 tool_calls / tool_call_id 等字段）
        api_messages = [{"role": "system", "content": system_prompt}]
        for msg in messages:
            if msg["role"] == "system":
                continue
            entry = {"role": msg["role"]}
            if msg.get("content") is not None:
                entry["content"] = msg["content"]
            if "tool_calls" in msg:
                entry["tool_calls"] = msg["tool_calls"]
            if "tool_call_id" in msg:
                entry["tool_call_id"] = msg["tool_call_id"]
            api_messages.append(entry)

        # 消息规范化 + 自动修复序列
        api_messages = self._normalize_messages(api_messages)
        api_messages = self._auto_fix_messages(api_messages)

        kwargs: dict = {
            "model": self.model,
            "messages": api_messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }

        # ── 工具 ──
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        # ── DeepSeek 特殊适配 ──

        extra_body = {}

        # 1. 关闭 thinking 模式（DeepSeek 默认开启，浪费 token）
        if self.disable_thinking and ("deepseek" in self.base_url.lower() or "deepseek" in self.model.lower()):
            extra_body["thinking"] = {"type": "disabled"}

        # 2. 上下文缓存（prefix caching）
        if self.enable_caching and self.cache_prefix and self._supports_prefix_cache:
            # DeepSeek prefix caching: 系统提示词会自动缓存
            # 标记系统消息和前面的消息为可缓存
            pass  # 通过 extra_headers 控制

        if extra_body:
            kwargs["extra_body"] = extra_body

        # 最终防线：发送前校验消息完整性
        api_messages = self._validate_and_strip(api_messages)
        kwargs["messages"] = api_messages

        try:
            if self.on_stream:
                kwargs["stream"] = True
                # 流式模式下 extra_body 可能不支持，分两次调用
                stream_extra = extra_body.copy() if extra_body else {}
                if stream_extra:
                    kwargs["extra_body"] = stream_extra
                return self._chat_stream(client, **kwargs)
            else:
                response = client.chat.completions.create(**kwargs)
                return self._parse_response(response)
        except Exception as e:
            return LLMResponse(
                content=f"[API 错误] [{classify_error(e).value}] {e}",
                stop_reason="error",
            )

    # ── 消息规范化 ──

    @staticmethod
    def _normalize_messages(messages: list[dict]) -> list[dict]:
        """规范化消息列表，确保满足 API 的 user/assistant/tool 交替约束。

        规则：
          - 连续的 user 消息 → 合并
          - 连续的 assistant 消息 → 合并
          - tool 消息前必须是 assistant（含 tool_calls）
          - 第一条非 system 消息必须是 user
        """
        if not messages:
            return messages

        result: list[dict] = []
        last_role = "system"

        for msg in messages:
            role = msg.get("role", "")

            # tool 消息必须跟在 assistant(tool_calls) 后面
            if role == "tool":
                if last_role not in ("assistant", "tool"):
                    continue
                result.append(msg)
                last_role = "tool"
                continue

            # 同角色连续 → 合并 content
            if role == last_role and role in ("user", "assistant"):
                if result and result[-1].get("content") and msg.get("content"):
                    result[-1]["content"] += "\n" + msg["content"]
                    if "tool_calls" in msg and "tool_calls" not in result[-1]:
                        result[-1]["tool_calls"] = msg["tool_calls"]
                else:
                    result.append(msg)
                continue

            result.append(msg)
            last_role = role

        return result

    @staticmethod
    def _validate_and_strip(messages: list[dict]) -> list[dict]:
        """最终防线：发送前校验消息完整性。

        如果发现任何未配对的 tool_calls/tool，回退到最安全状态：
        [system, user(最新), assistant(最近)]。
        """
        if not messages:
            return messages

        # 检查有无孤立 tool_calls
        tc_owner: set[str] = set()
        for m in messages:
            if m.get("tool_calls"):
                for t in m["tool_calls"]:
                    tid = t.get("id", "")
                    if tid:
                        tc_owner.add(tid)

        responded: set[str] = set()
        for m in messages:
            if m.get("role") == "tool":
                tid = m.get("tool_call_id", "")
                if tid:
                    responded.add(tid)

        # 检查未响应的 tool_calls
        has_orphan_tc = False
        for m in messages:
            if not m.get("tool_calls"):
                continue
            tc_ids = {t.get("id", "") for t in m["tool_calls"] if t.get("id")}
            if tc_ids and not tc_ids.issubset(responded):
                has_orphan_tc = True
                break

        # 检查孤立的 tool
        has_orphan_tool = False
        for m in messages:
            if m.get("role") == "tool":
                tid = m.get("tool_call_id", "")
                if tid and tid not in tc_owner:
                    has_orphan_tool = True
                    break

        if not has_orphan_tc and not has_orphan_tool:
            return messages  # 安全的，直接返回

        # 有孤立消息 → 回退到安全状态
        _log.warning("message_validation_failed: orphan_tc=%s orphan_tool=%s. Falling back.",
                     has_orphan_tc, has_orphan_tool)

        # 保留 system + 最近的 user + 最近的 assistant
        safe = [m for m in messages if m.get("role") == "system"]
        for m in reversed(messages):
            if m.get("role") == "user":
                safe.append(m)
                break
        for m in reversed(messages):
            if m.get("role") == "assistant" and not m.get("tool_calls"):
                safe.append(m)
                break

        _log.warning("message_fallback: %d messages → %d messages", len(messages), len(safe))
        return safe

    @staticmethod
    def _auto_fix_messages(messages: list[dict]) -> list[dict]:
        """全面修复消息序列。

        修复所有问题：
          1. 任意位置的孤立 assistant(tool_calls) → 移除
          2. 任意位置的孤立 tool → 移除
          3. user 插队 → 移到对应 tool 完成之后
          4. assistant(tool_calls) 的 content 设为 None
          5. 重复执行直到没有更多修复（应对多重嵌套问题）
        """
        if not messages:
            return messages

        for _ in range(5):  # 最多 5 轮修复
            changed = False

            # 建立 tool_call_id → 所属 assistant 索引映射
            tc_owner: dict[str, int] = {}
            for i, m in enumerate(messages):
                if m.get("tool_calls"):
                    for t in m["tool_calls"]:
                        tid = t.get("id", "")
                        if tid:
                            tc_owner[tid] = i

            # 找出所有已响应的 tool_call_id
            responded_ids: set[str] = set()
            for i, m in enumerate(messages):
                if m.get("role") == "tool":
                    tid = m.get("tool_call_id", "")
                    if tid:
                        responded_ids.add(tid)

            to_remove: set[int] = set()
            to_move: list[tuple[int, int]] = []  # (from_idx, insert_after)

            # 1. 移除所有无对应 tool 响应的 assistant(tool_calls)
            for i, m in enumerate(messages):
                if not m.get("tool_calls"):
                    continue
                tc_ids = {t.get("id", "") for t in m["tool_calls"] if t.get("id")}
                if not tc_ids:
                    continue
                if tc_ids - responded_ids == tc_ids:
                    # 所有 tool_call_id 都没有响应 → 移除整条消息
                    to_remove.add(i)
                    changed = True

            # 2. 移除所有无对应 assistant 的 tool
            for i, m in enumerate(messages):
                if m.get("role") != "tool":
                    continue
                tid = m.get("tool_call_id", "")
                if tid and tid not in tc_owner:
                    to_remove.add(i)
                    changed = True

            # 3. 修复 user 插队
            for i, m in enumerate(messages):
                if m.get("role") != "user" or i in to_remove:
                    continue
                # 检查前面是否有未完成的 tool_calls
                for j in range(i - 1, -1, -1):
                    if j in to_remove:
                        continue
                    prev = messages[j]
                    if prev.get("tool_calls"):
                        pending_ids = {t.get("id", "") for t in prev["tool_calls"] if t.get("id")}
                        unanswered = pending_ids - responded_ids
                        if unanswered:
                            # 检查这些 tool 的响应是否在 user 后面
                            has_response_after = False
                            for k in range(i + 1, len(messages)):
                                if k in to_remove:
                                    continue
                                if messages[k].get("role") == "tool" and messages[k].get("tool_call_id") in unanswered:
                                    has_response_after = True
                                    break
                            if has_response_after:
                                # 找到最后一个关联的 tool 消息，把 user 移过去
                                last_tool_idx = i
                                for k in range(i + 1, len(messages)):
                                    if k in to_remove:
                                        continue
                                    if messages[k].get("role") == "tool":
                                        last_tool_idx = k
                                    else:
                                        break
                                to_move.append((i, last_tool_idx))
                                changed = True
                        break
                    elif prev.get("role") != "tool":
                        break

            # 4. 确保 assistant(tool_calls) 的 content=None
            for m in messages:
                if m.get("tool_calls") and m.get("content") is not None:
                    m["content"] = None
                    changed = True

            if not changed:
                break

            # 执行移除和移动
            result = [m for i, m in enumerate(messages) if i not in to_remove]

            # 从后往前执行移动（避免索引偏移）
            for from_idx, insert_after in sorted(to_move, key=lambda x: -x[0]):
                if from_idx >= len(result):
                    continue
                user_msg = result.pop(from_idx)
                adjusted = insert_after
                # 如果移除了比 insert_after 更前面的消息，要调整
                removed_before = sum(1 for ri in to_remove if ri < insert_after)
                adjusted -= removed_before
                if adjusted < 0:
                    adjusted = 0
                if adjusted > len(result):
                    adjusted = len(result)
                result.insert(adjusted, user_msg)

            messages = result

        return messages

    def _flush_tool_blocks(self, acc: dict[int, dict]):
        """将所有累积的工具调用作为 content_block 事件发出。"""
        if not acc or not self.on_content_block:
            return
        for idx in sorted(acc.keys()):
            tc = acc[idx]
            if not tc["name"]:
                continue
            try:
                args = json.loads(tc.get("arguments", "{}"))
            except json.JSONDecodeError:
                args = {}
            self.on_content_block("tool_use", {
                "name": tc["name"],
                "input": args,
                "id": tc.get("id", ""),
                "index": idx,
            })

    def _chat_stream(self, client, **kwargs):
        """流式调用 OpenAI/DeepSeek API。

        文档对齐：
          - 停滞检测：30s 无事件 → 降级到非流式
          - 内容块类型分发：text / tool_use
          - 异步生成器降级：流式失败 → 回退非流式
        """
        content = ""
        tool_calls_acc: dict[int, dict] = {}
        finish_reason = "stop"
        last_event_time = time.time()
        stall_active_start = time.time()
        last_was_text = False
        last_was_tool = False

        try:
            stream = client.chat.completions.create(**kwargs)
            for chunk in stream:
                now = time.time()

                # 被动超时：距上次事件超过 30s → 网络停滞
                if now - last_event_time > STALL_PASSIVE_TIMEOUT:
                    raise TimeoutError(
                        f"流式响应被动超时 {STALL_PASSIVE_TIMEOUT}s（距上次事件）")
                last_event_time = now

                if not chunk.choices or len(chunk.choices) == 0:
                    continue

                delta = chunk.choices[0].delta
                finish = chunk.choices[0].finish_reason

                if finish:
                    finish_reason = finish

                # 文本增量块 → text_delta
                if delta.content:
                    # 检测块类型切换：之前是 tool → 现在变成 text
                    if last_was_tool and not last_was_text:
                        # tool 块结束 → 通知 agent 执行工具
                        self._flush_tool_blocks(tool_calls_acc)
                    last_was_text = True
                    last_was_tool = False

                    content += delta.content
                    if self.on_stream:
                        self.on_stream(delta.content)

                # 工具调用增量块
                if delta.tool_calls:
                    # 检测块类型切换：之前是 text → 现在变成 tool
                    if last_was_text and not last_was_tool:
                        # text 块结束 → 通知
                        pass
                    last_was_tool = True
                    last_was_text = False

                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in tool_calls_acc:
                            tool_calls_acc[idx] = {"id": "", "name": "", "arguments": ""}
                        if tc.id:
                            tool_calls_acc[idx]["id"] = tc.id
                        if tc.function:
                            if tc.function.name:
                                tool_calls_acc[idx]["name"] = tc.function.name
                            if tc.function.arguments:
                                tool_calls_acc[idx]["arguments"] += tc.function.arguments

                # 主动超时：90s 总耗时上限
                if now - stall_active_start > STALL_ACTIVE_TIMEOUT:
                    raise TimeoutError(
                        f"流式响应主动超时 {STALL_ACTIVE_TIMEOUT}s（总耗时）")

        except Exception as stream_err:
            _log.warning("stream_fallback: %s", stream_err)
            kwargs.pop("stream", None)
            kwargs.pop("extra_body", None)
            try:
                response = client.chat.completions.create(**kwargs)
                return self._parse_response(response)
            except Exception as fallback_err:
                raise fallback_err from stream_err

        # 最后的工具块
        self._flush_tool_blocks(tool_calls_acc)

        call_list = []
        if tool_calls_acc:
            for idx in sorted(tool_calls_acc.keys()):
                tc = tool_calls_acc[idx]
                try:
                    args = json.loads(tc["arguments"]) if tc["arguments"] else {}
                except json.JSONDecodeError:
                    args = {}
                call_list.append({"id": tc.get("id", ""), "name": tc["name"], "args": args})

        stop_reason = "end_turn"
        if call_list or finish_reason == "tool_calls":
            stop_reason = "tool_use"

        return LLMResponse(
            content=content,
            tool_calls=call_list if call_list else None,
            stop_reason=stop_reason,
            model=kwargs.get("model", ""),
        )

    def _parse_response(self, response) -> LLMResponse:
        choice = response.choices[0]
        content = choice.message.content or ""
        tool_calls = []

        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append({"id": tc.id, "name": tc.function.name, "args": args})

        stop_reason = "end_turn"
        if choice.finish_reason == "tool_calls":
            stop_reason = "tool_use"
        elif choice.finish_reason == "length":
            stop_reason = "max_tokens"

        return LLMResponse(
            content=content,
            tool_calls=tool_calls if tool_calls else None,
            stop_reason=stop_reason,
            usage={
                "input_tokens": response.usage.prompt_tokens if response.usage else 0,
                "output_tokens": response.usage.completion_tokens if response.usage else 0,
            },
            model=response.model,
            raw=response,
        )


# ── 工厂函数 ──

def create_provider(config: dict) -> LLMProvider:
    """根据配置创建 LLM 提供商实例。

    Config:
      - provider: "anthropic" | "openai" | "deepseek"
      - disable_thinking: 是否关闭 DeepSeek thinking 模式（默认 true）
      - enable_caching: 是否启用上下文缓存（默认 false）
    """
    provider_type = config.get("provider", "anthropic").lower()

    if provider_type == "anthropic":
        return AnthropicProvider(config)
    elif provider_type in ("openai", "deepseek"):
        return OpenAIProvider(config)
    else:
        raise ValueError(f"不支持的提供商: {provider_type}")
