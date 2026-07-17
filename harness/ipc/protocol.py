"""IPC 协议 — Harness ↔ Python Core 通信层。

文档对齐：stdin/stdout JSON-RPC 2.0 + 流式事件推送

消息格式:
  请求:     {"id": 1, "method": "tool.call", "params": {...}}
  响应:     {"id": 1, "result": "..."}
  错误:     {"id": 1, "error": "错误信息"}
  事件:     {"method": "event", "params": {"type": "text", "data": "..."}}
  流式块:   {"method": "stream", "params": "字符块"}
  心跳:     {"method": "ping"} → {"id": ..., "result": "pong"}
"""

from __future__ import annotations

import json
import select
import sys
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


# ── 消息类型 ──

class IPCMethod(str, Enum):
    """IPC 方法名。"""
    TOOL_CALL = "tool.call"
    TOOL_RESULT = "tool.result"
    EVENT = "event"
    STREAM = "stream"
    PING = "ping"
    SHUTDOWN = "shutdown"
    CONFIGURE = "configure"
    STATUS = "status"
    HELLO = "hello"


# ── 消息数据类 ──

@dataclass
class IPCMessage:
    """IPC 消息。"""
    id: int | None = None
    method: str = ""
    params: dict | None = None
    result: Any = None
    error: str | None = None

    def to_dict(self) -> dict:
        d = {}
        if self.id is not None:
            d["id"] = self.id
        if self.method:
            d["method"] = self.method
        if self.params is not None:
            d["params"] = self.params
        if self.result is not None:
            d["result"] = self.result
        if self.error is not None:
            d["error"] = self.error
        return d

    @classmethod
    def from_dict(cls, d: dict) -> IPCMessage:
        return cls(
            id=d.get("id"),
            method=d.get("method", ""),
            params=d.get("params"),
            result=d.get("result"),
            error=d.get("error"),
        )


# ── 事件类型 ──

class EventType(str, Enum):
    """事件类型（Claude Code 结构化事件体系）。

    对应 Claude API 的事件类型层次：
      - content_block_delta: text / thinking / tool_use 的增量
      - content_block_start/stop: 块生命周期
      - message_start/delta: 消息级事件
      - tool: 工具执行生命周期
      - session: 会话生命周期
      - error: 错误事件
    """
    # ── 消息级 ──
    MESSAGE_START = "message_start"
    MESSAGE_DELTA = "message_delta"
    MESSAGE_STOP = "message_stop"

    # ── 内容块级（对应 content_block_delta.type） ──
    TEXT_DELTA = "text_delta"           # 文本增量块
    THINKING_DELTA = "thinking_delta"   # 思考增量块
    TOOL_USE_START = "tool_use_start"   # 工具调用开始
    TOOL_USE_DELTA = "tool_use_delta"   # 工具参数增量
    TOOL_USE_STOP = "tool_use_stop"     # 工具调用完成

    # ── 工具执行生命周期 ──
    TOOL_START = "tool_start"           # 工具开始执行
    TOOL_RESULT = "tool_result"         # 工具执行结果
    TOOL_ERROR = "tool_error"           # 工具执行错误

    # ── 会话 ──
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    STATUS = "status"
    PROGRESS = "progress"
    ERROR = "error"


# ── 传输层接口 ──

class Transport:
    """消息传输层抽象。"""

    def send(self, data: str):
        """发送一行数据。"""
        raise NotImplementedError

    def recv(self, timeout: float | None = None) -> str | None:
        """接收一行数据（阻塞/超时）。"""
        raise NotImplementedError

    def close(self):
        """关闭传输。"""
        raise NotImplementedError


class StdioTransport(Transport):
    """基于 stdin/stdout 的传输层。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._buffer = ""

    def send(self, data: str):
        """发送一行 JSON 到 stdout。"""
        with self._lock:
            sys.stdout.write(data + "\n")
            sys.stdout.flush()

    def recv(self, timeout: float | None = None) -> str | None:
        """从 stdin 读取一行（支持超时）。"""
        if timeout is not None and timeout > 0:
            # 使用 select 实现超时读取
            if sys.platform != "win32":
                r, _, _ = select.select([sys.stdin], [], [], timeout)
                if not r:
                    return None  # 超时
            else:
                # Windows 不支持 select 在 stdin 上
                # 使用非阻塞近似
                pass

        line = sys.stdin.readline()
        if not line:
            return None
        return line.strip()

    def close(self):
        pass  # stdin/stdout 由系统管理


# ── IPC 客户端（Python Core 端） ──

class IPCClient:
    """IPC 客户端——运行在 Python Core 进程中。

    通过 stdin 接收消息，通过 stdout 发送消息。
    支持流式事件推送、心跳检测、请求-响应。
    """

    def __init__(self, transport: Transport | None = None):
        self.transport = transport or StdioTransport()
        self._lock = threading.Lock()
        self._msg_id = 0
        self._handlers: dict[str, Callable] = {}
        self._pending: dict[int, threading.Event] = {}
        self._results: dict[int, Any] = {}
        self._running = False
        self._reader_thread: threading.Thread | None = None
        self._heartbeat_thread: threading.Thread | None = None
        self._last_pong = time.time()
        self._on_event: Callable | None = None

    # ── 生命周期 ──

    def start(self):
        """启动 IPC 客户端（读取线程 + 心跳线程）。"""
        self._running = True
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()

        self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._heartbeat_thread.start()

        # 发送 HELLO
        self.send_event(EventType.STATUS, {
            "status": "ready",
            "version": "1.0.0",
            "pid": threading.get_native_id() if hasattr(threading, 'get_native_id') else 0,
        })

    def stop(self):
        """停止 IPC 客户端。"""
        self._running = False

    def wait(self, timeout: float | None = None):
        """等待读取线程结束。"""
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=timeout)

    # ── 事件注册 ──

    def set_event_handler(self, handler: Callable):
        """设置全局事件处理器（收到 event/stream 时调用）。"""
        self._on_event = handler

    def register_handler(self, method: str, handler: Callable):
        """注册指定 method 的处理器。"""
        self._handlers[method] = handler

    # ── 发送 ──

    def send_event(self, event_type: str, data: Any):
        """发送事件通知（无需响应）。"""
        msg = IPCMessage(
            method=IPCMethod.EVENT,
            params={"type": event_type, "data": data}
        )
        self._send(msg)

    def send_stream(self, chunk: str):
        """发送流式文本块。"""
        if not chunk:
            return
        msg = IPCMessage(
            method=IPCMethod.STREAM,
            params=chunk,
        )
        self._send(msg)

    def send_request(self, method: str, params: dict | None = None,
                     timeout: float = 60.0) -> Any:
        """发送请求并等待响应。"""
        self._msg_id += 1
        msg_id = self._msg_id

        msg = IPCMessage(
            id=msg_id,
            method=method,
            params=params,
        )

        event = threading.Event()
        with self._lock:
            self._pending[msg_id] = event

        self._send(msg)

        # 等待响应
        if event.wait(timeout=timeout):
            with self._lock:
                result = self._results.pop(msg_id, None)
                self._pending.pop(msg_id, None)
            return result
        else:
            with self._lock:
                self._pending.pop(msg_id, None)
            return {"error": "timeout"}

    def send_ping(self) -> bool:
        """发送心跳检测。"""
        result = self.send_request(IPCMethod.PING, timeout=5)
        if result and result != "timeout":
            self._last_pong = time.time()
            return True
        return False

    # ── 内部发送 ──

    def _send(self, msg: IPCMessage):
        """发送消息。"""
        line = json.dumps(msg.to_dict(), ensure_ascii=False)
        self.transport.send(line)

    # ── 读取循环 ──

    def _reader_loop(self):
        """读取 stdin 消息循环。"""
        while self._running:
            try:
                line = sys.stdin.readline()
                if not line:
                    break

                line = line.strip()
                if not line:
                    continue

                msg = IPCMessage.from_dict(json.loads(line))

                # 响应（匹配 pending 请求）
                if msg.id is not None and msg.id in self._pending:
                    with self._lock:
                        self._results[msg.id] = msg.result if msg.result is not None else msg.error
                        self._pending[msg.id].set()
                    continue

                # 事件通知（无需响应）
                if msg.method == IPCMethod.EVENT and self._on_event:
                    self._on_event(msg.params)
                    continue

                if msg.method == IPCMethod.STREAM and self._on_event:
                    self._on_event({"type": "stream", "data": msg.params})
                    continue

                # 请求/方法调用
                if msg.method:
                    handler = self._handlers.get(msg.method)
                    if handler:
                        try:
                            result = handler(msg.params)
                            if msg.id is not None:
                                resp = IPCMessage(id=msg.id, result=result)
                                self._send(resp)
                        except Exception as e:
                            if msg.id is not None:
                                resp = IPCMessage(id=msg.id, error=str(e))
                                self._send(resp)

            except json.JSONDecodeError:
                continue
            except Exception:
                if self._running:
                    continue
                break

    # ── 心跳循环 ──

    def _heartbeat_loop(self):
        """定期发送心跳检测。"""
        while self._running:
            time.sleep(15)  # 每 15 秒一次心跳
            if not self.send_ping():
                # 心跳失败，记录但不断连（Harness 可能忙）
                pass


# ── IPC 服务器（Harness 端） ──

class IPCServer:
    """IPC 服务器——运行在 Harness 进程中。

    通过 stdout 发送消息，通过 stdin 接收消息。
    """

    def __init__(self):
        self._msg_id = 0
        self._handlers: dict[str, Callable] = {}
        self._running = False
        self._lock = threading.Lock()

    def start(self):
        """启动 IPC 服务器。"""
        self._running = True

    def stop(self):
        """停止 IPC 服务器。"""
        self._running = False

    def send_request(self, method: str, params: dict | None = None) -> Any:
        """发送请求并等待响应。"""
        self._msg_id += 1
        msg = IPCMessage(id=self._msg_id, method=method, params=params)
        self._send(msg)
        return self._read_response(self._msg_id)

    def send_event(self, event_type: str, data: Any):
        """发送事件。"""
        msg = IPCMessage(
            method=IPCMethod.EVENT,
            params={"type": event_type, "data": data}
        )
        self._send(msg)

    def send_stream(self, chunk: str):
        """发送流式文本块。"""
        msg = IPCMessage(method=IPCMethod.STREAM, params=chunk)
        self._send(msg)

    def register_handler(self, method: str, handler: Callable):
        """注册处理器。"""
        self._handlers[method] = handler

    def _send(self, msg: IPCMessage):
        with self._lock:
            line = json.dumps(msg.to_dict(), ensure_ascii=False)
            sys.stdout.write(line + "\n")
            sys.stdout.flush()

    def _read_response(self, expected_id: int, timeout: float = 60.0) -> Any:
        deadline = time.time() + timeout
        while time.time() < deadline:
            line = sys.stdin.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            try:
                msg = IPCMessage.from_dict(json.loads(line))
                if msg.id == expected_id:
                    return msg.result if msg.result is not None else msg.error
            except json.JSONDecodeError:
                continue
        return {"error": "timeout"}
