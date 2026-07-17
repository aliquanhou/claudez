"""Harness Runner — Harness ↔ Python Core 通信桥梁。

文档对齐：Python 核心通过 IPC 与 Go Harness 通信。
职责：
  1. 初始化 IPC 客户端
  2. 将 Agent 事件推送到 Harness（文本、工具调用、错误）
  3. 支持流式文本推送
  4. 响应 Harness 的 ping/shutdown 请求
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path

# 将项目根目录加入路径
_root = str(Path(__file__).resolve().parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

from harness.ipc.protocol import IPCClient, EventType


class HarnessRunner:
    """Harness 运行器——管理 IPC 通信和 Agent 生命周期。"""

    def __init__(self, agent):
        self.agent = agent
        self.ipc = IPCClient()
        self._running = False
        self._current_stream_text = ""

        # 初始化插件系统
        try:
            from agent.plugin_manager import get_plugin_manager
            from agent.tools import get_registry
            pm = get_plugin_manager()
            pm.set_tool_registry(get_registry())
            pm.discover()
            pm.load_all()
        except Exception:
            pass

        # 注册 IPC 处理器
        self.ipc.register_handler("ping", self._handle_ping)
        self.ipc.register_handler("shutdown", self._handle_shutdown)
        self.ipc.register_handler("configure", self._handle_configure)
        self.ipc.register_handler("status", self._handle_status)

        # 挂载 Agent 回调
        self._setup_agent_callbacks()

    def _setup_agent_callbacks(self):
        """将 Agent 回调挂载到 IPC 事件。"""
        # ── 工具调用回调 ──
        original_on_tool = self.agent.on_tool_call

        def on_tool_wrapper(name, args, result):
            self.ipc.send_event(EventType.TOOL_START, {
                "name": name,
                "args": json.dumps(args, ensure_ascii=False)[:200],
            })
            if original_on_tool:
                original_on_tool(name, args, result)
            is_success = not (
                result.startswith("[错误]") or result.startswith("[超时]")
            )
            self.ipc.send_event(EventType.TOOL_RESULT, {
                "success": is_success,
                "data": result[:500],
                "duration": "",
            })

        self.agent.on_tool_call = on_tool_wrapper

        # ── 消息回调 ──
        original_on_message = self.agent.on_message

        def on_message_wrapper(role, content):
            if role == "assistant" and content:
                # 完整文本事件
                self.ipc.send_event(EventType.TEXT, content)
            if original_on_message:
                original_on_message(role, content)

        self.agent.on_message = on_message_wrapper

        # ── 流式回调 ──
        original_on_stream = self.agent.on_stream

        def on_stream_wrapper(chunk: str):
            if chunk:
                self.ipc.send_stream(chunk)
            if original_on_stream:
                original_on_stream(chunk)

        self.agent.on_stream = on_stream_wrapper

        # ── 错误回调 ──
        original_on_error = self.agent.on_error

        def on_error_wrapper(ctx, err):
            self.ipc.send_event(EventType.ERROR, f"{ctx}: {err}")
            if original_on_error:
                original_on_error(ctx, err)

        self.agent.on_error = on_error_wrapper

        # ── 思考回调 ──
        original_on_thinking = self.agent.on_thinking

        def on_thinking_wrapper(msg):
            self.ipc.send_event(EventType.THINKING, msg)
            if original_on_thinking:
                original_on_thinking(msg)

        self.agent.on_thinking = on_thinking_wrapper

    def run(self, message: str = ""):
        """运行 Agent（IPC 模式）。

        非阻塞式：设置好回调后注册到 IPC 事件循环，
        由 IPC 的读取线程驱动，不主动轮询。
        """
        self._running = True
        self.ipc.start()

        # 注册事件处理器——当用户输入到达时触发 Agent.run
        self.ipc.set_event_handler(self._on_ipc_event)

        try:
            # 如果有初始消息，直接处理
            if message:
                self.ipc.send_event(EventType.THINKING, "正在处理请求...")
                result = self.agent.run(message)
                self.ipc.send_event(EventType.COMPLETE, {"result": result})

            # 保持运行——IPC 读取线程是 daemon，不会阻塞退出
            # 使用事件等待而不是忙等
            while self._running:
                time.sleep(0.5)  # 0.5s 间隔比 0.1s 好很多

        except KeyboardInterrupt:
            self.ipc.send_event(EventType.STATUS, {"status": "shutting_down"})
        except Exception as e:
            self.ipc.send_event(
                EventType.ERROR, f"Agent 错误: {e}\n{traceback.format_exc()[:1000]}"
            )
        finally:
            self._running = False
            self.ipc.stop()

    def _on_ipc_event(self, params):
        """处理来自 Harness 的事件。"""
        if not params:
            return

        event_type = params.get("type")
        data = params.get("data")

        if event_type == "user_message" and data:
            # 来自 Harness 的用户消息
            self.ipc.send_event(EventType.THINKING, "处理消息...")
            try:
                result = self.agent.run(data)
                self.ipc.send_event(EventType.COMPLETE, {"result": result})
            except Exception as e:
                self.ipc.send_event(EventType.ERROR, str(e))

    # ── IPC 处理器 ──

    def _handle_ping(self, params):
        return "pong"

    def _handle_shutdown(self, params):
        self._running = False
        if hasattr(self.agent, 'stop'):
            self.agent.stop()
        return "ok"

    def _handle_configure(self, params):
        if params:
            self.agent.config.update(params)
        return "ok"

    def _handle_status(self, params):
        return {
            "running": self._running,
            "turn_count": self.agent.session.turn_count,
            "tool_call_count": self.agent.session.tool_call_count,
            "memory_size": len(self.agent.short_memory.facts)
            if hasattr(self.agent, 'short_memory')
            else 0,
        }
