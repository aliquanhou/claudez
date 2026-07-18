"""web_server — ClaudeZ Web GUI (AgiCode 架构版)

借鉴 AgiCode v2.1.0 设计：
  - WebStreamHandler 桥接 Agent 事件 → SSE
  - AgentApp 统一生命周期 + 线程安全
  - on_tool_start 在工具执行前触发

API:
  GET  /              → index.html
  GET  /api/stream    → SSE 事件流
  POST /api/send      → 发送消息
  POST /api/stop      → 终止
  POST /api/clear     → 清空
  POST /api/config    → 设置配置
  GET  /api/config    → 获取配置
  GET  /api/context   → 获取上下文
  GET  /api/health    → 健康检查
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import queue as q_module
import socket
import threading
import time
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

_log = logging.getLogger("claudez.web_server")


HERE = Path(__file__).parent
STATIC_DIR = HERE / "static"


class SendBody(BaseModel):
    text: str


class WebStreamHandler:
    """StreamHandler 桥接：将 Agent 事件推送到 SSE。

    设计（AgiCode 架构）：
      - on_text: 实时文本块
      - on_thinking: 思考块
      - on_tool_start: 工具开始执行前触发（关键！）
      - on_tool_result: 工具执行完成后触发
      - on_error: 错误
      - _tool_queue: 追踪多工具调用顺序
    """

    def __init__(self, push_sse: callable):
        self._push_sse = push_sse
        self._tool_queue: list[str] = []

    def on_text(self, text: str):
        if text:
            self._push_sse("text_delta", {"delta": text})

    def on_thinking(self, text: str):
        if text:
            self._push_sse("thinking_delta", {"delta": text})

    def on_tool_start(self, name: str, input_data: dict):
        """工具开始执行前触发（SSE 立即推送 tool_use_start）。"""
        path = (input_data.get("file_path") or input_data.get("command") or
                input_data.get("url") or input_data.get("pattern") or input_data.get("query") or "")
        self._tool_queue.append(name)
        self._push_sse("tool_use_start", {
            "tool_name": name,
            "file_path": path,
            "args_preview": json.dumps(input_data, ensure_ascii=False)[:100],
        })

    def on_tool_result(self, result: str):
        """工具执行完成后触发。"""
        name = self._tool_queue.pop(0) if self._tool_queue else ""
        is_error = result.startswith("[错误]") or result.startswith("[超时]")
        self._push_sse("tool_result", {
            "tool_name": name,
            "status": "error" if is_error else "ok",
            "result": result[:500],
            "duration_ms": 0,
        })

    def on_error(self, error: str):
        self._push_sse("error", {"message": error})

    def on_complete(self):
        self._push_sse("session_end", {"agent": "claudez"})


class WebServer:
    """ClaudeZ Web GUI 服务器。

    通过 WebStreamHandler 桥接 Agent 事件到 SSE。
    """

    def __init__(self, agent=None):
        self.agent = agent
        self.port: int = 0
        self.host: str = "127.0.0.1"
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self._sse_queues: list[q_module.Queue] = []
        self._sse_lock = threading.Lock()

        # 线程安全 busy 标志
        self._busy_lock = threading.Lock()
        self._busy = False

        self._last_text = ""

        # 插件系统
        from agent.plugin_manager import get_plugin_manager
        self._plugin_manager = get_plugin_manager()
        self._plugins_initialized = False

        self.app = FastAPI(title="ClaudeZ Web")
        self._register_routes()

    def _init_plugins(self):
        """初始化插件系统。"""
        if self._plugins_initialized:
            return
        self._plugins_initialized = True

        # 连接 ToolRegistry
        from agent.tools import get_registry
        registry = get_registry()
        self._plugin_manager.set_tool_registry(registry)

        # 发现插件
        discovered = self._plugin_manager.discover()
        _log.info("插件系统初始化: 发现 %d 个插件", len(discovered))

        # 自动加载所有插件
        loaded = self._plugin_manager.load_all()
        _log.info("插件系统: 已加载 %d 个插件", loaded)

        # 注册变化回调（通知前端刷新）
        self._plugin_manager.on_changed(self._on_plugins_changed)

    def _on_plugins_changed(self):
        """插件状态变化时推送事件到前端。"""
        self._push_sse("plugins_changed", {
            "plugin_count": len(self._plugin_manager.get_all_plugins()),
            "enabled_count": len(self._plugin_manager.get_enabled_plugins()),
        })

    def _register_routes(self):
        app = self.app

        @app.get("/")
        async def serve_index():
            index_path = STATIC_DIR / "index.html"
            if not index_path.exists():
                return HTMLResponse("<h1>ClaudeZ</h1><p>Frontend not found.</p>", status_code=404)
            return FileResponse(str(index_path))

        @app.get("/api/stream")
        async def sse_stream(request: Request):
            queue: q_module.Queue = q_module.Queue(maxsize=1000)
            with self._sse_lock:
                self._sse_queues.append(queue)

            async def event_generator():
                loop = asyncio.get_event_loop()
                try:
                    while True:
                        if await request.is_disconnected():
                            break
                        try:
                            data = await loop.run_in_executor(
                                None, lambda: queue.get(timeout=0.5)
                            )
                        except q_module.Empty:
                            yield {"event": "ping", "data": json.dumps({"type": "keepalive"})}
                            continue
                        except Exception:
                            break
                        if data is None:
                            break
                        event_type = data.get("type", "message")
                        payload = data.get("payload", {})
                        yield {"event": event_type, "data": json.dumps(payload, ensure_ascii=False)}
                finally:
                    with self._sse_lock:
                        if queue in self._sse_queues:
                            self._sse_queues.remove(queue)

            return EventSourceResponse(event_generator())

        @app.post("/api/send")
        async def api_send(body: SendBody):
            if not self.agent:
                return {"status": "error", "message": "Agent not initialized"}
            with self._busy_lock:
                if self._busy:
                    return {"status": "error", "message": "Agent 正在工作中"}
                self._busy = True
            text = body.text.strip()
            if not text:
                self._busy = False
                return {"status": "error", "message": "消息不能为空"}
            self._last_text = text

            # 创建 WebStreamHandler 桥接
            handler = WebStreamHandler(self._push_sse)

            def run_agent():
                try:
                    self._push_sse("session_start", {"agent": "claudez"})
                    self._run_with_handler(text, handler)
                except Exception as e:
                    try:
                        handler.on_error(f"Agent 错误: {e}")
                    except Exception:
                        pass
                finally:
                    try:
                        handler.on_complete()
                    except Exception:
                        pass
                    with self._busy_lock:
                        self._busy = False

            t = threading.Thread(target=run_agent, daemon=True, name="claudez-agent")
            t.start()

            # 安全兜底：60s 后自动解锁（防止线程挂死）
            def auto_clear():
                time.sleep(60)
                with self._busy_lock:
                    self._busy = False
            threading.Thread(target=auto_clear, daemon=True).start()

            return {"status": "ok"}

        @app.post("/api/stop")
        async def api_stop():
            if self.agent:
                self.agent.stop()
            with self._busy_lock:
                self._busy = False
            try:
                self._push_sse("session_end", {"agent": "claudez"})
            except Exception:
                pass
            return {"status": "ok"}

        @app.post("/api/clear")
        async def api_clear():
            from agent.session import reset_session
            reset_session()
            return {"status": "ok"}

        @app.post("/api/config")
        async def api_set_config(body: dict):
            if self.agent:
                needs_recreate = False
                if "model" in body:
                    self.agent.config["model"] = body["model"]
                if "provider" in body:
                    self.agent.config["provider"] = body["provider"]
                    needs_recreate = True
                if "base_url" in body:
                    self.agent.config["base_url"] = body["base_url"]
                    needs_recreate = True
                if "api_key" in body and body["api_key"]:
                    # 更新内存中的 key（不存到 config.json）
                    self.agent.config["api_key"] = body["api_key"]
                    # 同时设置环境变量方便子进程继承
                    os.environ["CLAUDEZ_API_KEY"] = body["api_key"]
                    needs_recreate = True
                if "workflow_mode" in body:
                    self.agent.set_workflow_mode(body["workflow_mode"])
                # 有影响 provider 的变更时重新创建 provider 实例
                if needs_recreate:
                    from agent.providers import create_provider
                    self.agent.provider = create_provider(self.agent.config)
                    self.agent._setup_provider_callbacks()
            return {"status": "ok"}

        @app.get("/api/config")
        async def api_get_config():
            if not self.agent:
                return {"provider": "", "model": "", "workflow_mode": "", "base_url": ""}
            cfg = self.agent.config
            return {
                "provider": cfg.get("provider", ""),
                "model": cfg.get("model", ""),
                "workflow_mode": cfg.get("workflow_mode", "agent"),
                "base_url": cfg.get("base_url", ""),
                "api_key_configured": bool(cfg.get("api_key") or os.environ.get("CLAUDEZ_API_KEY")),
                "tool_count": len(self.agent.session.messages) if self.agent else 0,
            }

        @app.get("/api/context")
        async def api_context():
            if not self.agent:
                return {"busy": False, "provider": "", "model": ""}
            with self._busy_lock:
                busy = self._busy
            return {
                "busy": busy,
                "provider": self.agent.config.get("provider", ""),
                "model": self.agent.config.get("model", ""),
            }

        @app.get("/api/health")
        async def api_health():
            return {"status": "ok", "port": self.port}

        @app.get("/api/debug")
        async def api_debug():
            """导出调试日志 JSON。"""
            if not self.agent or not hasattr(self.agent, 'debug'):
                return {"status": "error", "message": "No debug data"}
            return Response(
                content=self.agent.debug.export_json(),
                media_type="application/json",
                headers={
                    "Content-Disposition": "attachment; filename=claudez_debug.json",
                    "Cache-Control": "no-cache",
                },
            )

        @app.get("/api/debug/markdown")
        async def api_debug_markdown():
            """导出调试日志 Markdown。"""
            if not self.agent or not hasattr(self.agent, 'debug'):
                return {"status": "error", "message": "No debug data"}
            return Response(
                content=self.agent.debug.export_markdown(),
                media_type="text/markdown; charset=utf-8",
                headers={
                    "Content-Disposition": "attachment; filename=claudez_debug.md",
                    "Cache-Control": "no-cache",
                },
            )

        @app.get("/api/debug/summary")
        async def api_debug_summary():
            """获取调试摘要。"""
            if not self.agent or not hasattr(self.agent, 'debug'):
                return {"summary": {}}
            return self.agent.debug.data.get("summary", {})

        @app.get("/api/debug/plugins")
        async def api_debug_plugins():
            """获取插件调试日志（从插件实例获取，规避 importlib 模块隔离）。"""
            try:
                pm = self._plugin_manager if hasattr(self, '_plugin_manager') else None
                logs = []
                plugin_info = {}
                if pm:
                    for p in pm.get_all_plugins():
                        plugin_info[p.id] = {
                            "name": p.name,
                            "enabled": p.enabled,
                            "tool_count": len(p.tools or []),
                            "masked": list(getattr(p.instance, '_masked', set())) if p.instance else [],
                        }
                    # 从 host-tools 插件实例获取调试日志（解决 importlib 隔离问题）
                    host = pm.get_plugin("com.claudez.plugins.host-tools")
                    if host and host.instance and hasattr(host.instance, 'get_debug_logs'):
                        logs = host.instance.get_debug_logs()
                return {"logs": logs[-200:], "plugins": plugin_info}
            except Exception as e:
                return {"logs": [], "plugins": {}, "error": str(e)}

        # ── 记忆系统 API ──

        @app.get("/api/memory")
        async def api_memory_stats():
            """获取记忆系统状态。"""
            try:
                from agent.memory import get_semantic_memory, ShortTermMemory
                mem = get_semantic_memory()
                stm = ShortTermMemory()
                stats = {"semantic_enabled": False, "semantic_count": 0, "short_term_facts": len(stm.facts), "short_term_notes": len(stm.notes)}
                recent = []
                if mem:
                    try:
                        stats["semantic_enabled"] = True
                        stats["semantic_count"] = mem.count()
                        recent = mem.get_recent(10)
                    except Exception:
                        pass
                return {"stats": stats, "recent": recent}
            except Exception as e:
                return {"stats": {"error": str(e)}, "recent": []}

        @app.post("/api/memory/search")
        async def api_memory_search(body: dict):
            """搜索记忆。"""
            query = body.get("query", "")
            top_k = min(int(body.get("top_k", 5)), 50)
            if not query:
                return {"results": []}
            try:
                from agent.memory import get_semantic_memory
                mem = get_semantic_memory()
                if not mem:
                    return {"results": [], "error": "语义记忆未启用"}
                results = mem.search(query, n_results=top_k)
                return {"results": results}
            except Exception as e:
                return {"results": [], "error": str(e)}

        @app.post("/api/memory/store")
        async def api_memory_store(body: dict):
            """手动存储一条记忆。"""
            content = body.get("content", "").strip()
            mem_type = body.get("type", "note")
            if not content or len(content) < 5:
                return {"status": "error", "message": "记忆内容至少 5 个字符"}
            try:
                from agent.memory import get_semantic_memory
                mem = get_semantic_memory()
                if not mem:
                    return {"status": "error", "message": "语义记忆未启用（ChromaDB 不可用）"}
                ok = mem.store(content, {"type": mem_type})
                if ok:
                    return {"status": "ok"}
                return {"status": "error", "message": "存储失败"}
            except Exception as e:
                return {"status": "error", "message": str(e)}

        @app.post("/api/memory/clear")
        async def api_memory_clear():
            """清空所有记忆。"""
            try:
                from agent.memory import get_semantic_memory
                mem = get_semantic_memory()
                if mem:
                    mem.clear()
                from agent.memory.short_term import ShortTermMemory
                stm = ShortTermMemory()
                stm.clear()
                return {"status": "ok"}
            except Exception as e:
                return {"status": "error", "message": str(e)}

        # ── 插件 API ──

        @app.get("/api/plugins")
        async def api_get_plugins():
            """获取所有插件及工具列表。

            返回:
            {
                "plugins": [...],         # 插件列表（含 enabled/disabled）
                "tools": [...],           # 所有已启用的工具（含 masked 标记）
                "tools_by_category": {...}
            }
            """
            self._init_plugins()
            pm = self._plugin_manager

            plugins = [p.to_dict() for p in pm.get_all_plugins()]

            # 收集所有探测到的工具（含被屏蔽的）——从 host-tools 插件获取
            all_tools = []
            host_plugin = pm.get_plugin("com.claudez.plugins.host-tools")
            if host_plugin and host_plugin.instance and hasattr(host_plugin.instance, 'get_all_probed'):
                all_tools = host_plugin.instance.get_all_probed()
            else:
                # 降级：只有 tools 属性
                all_tools = pm.get_all_tools()

            tools_by_category = pm.get_tools_by_category()

            return {
                "plugins": plugins,
                "tools": all_tools,
                "tools_by_category": tools_by_category,
            }

        @app.post("/api/plugins/discover")
        async def api_discover_plugins():
            """重新扫描并重新探测全部插件，重新注册工具到 Agent。"""
            self._init_plugins()
            pm = self._plugin_manager
            discovered = pm.discover()
            total_tools = 0
            for p in pm.get_all_plugins():
                if p.instance and hasattr(p.instance, 'probe'):
                    try:
                        p.instance.probe(force=True)
                        pm.reload(p.id)
                        total_tools += len(p.tools or [])
                    except Exception as e:
                        _log.warning("re-probe 失败 %s: %s", p.id, e)
            return {
                "discovered": len(discovered),
                "tool_count": total_tools,
            }

        @app.post("/api/plugins/{plugin_id}/reprobe")
        async def api_reprobe_plugin(plugin_id: str):
            """强制重新探测指定插件并重新注册工具。"""
            self._init_plugins()
            pm = self._plugin_manager
            p = pm.get_plugin(plugin_id)
            if not p:
                return {"success": False, "message": "插件未找到"}
            if not p.instance or not hasattr(p.instance, 'probe'):
                return {"success": False, "message": "插件不支持重新探测"}
            try:
                p.instance.probe(force=True)
                pm.reload(plugin_id)
                return {"success": True, "tool_count": len(p.tools or [])}
            except Exception as e:
                _log.error("reprobe 失败 %s: %s", plugin_id, e)
                return {"success": False, "message": str(e)}

        @app.post("/api/plugins/{plugin_id}/load")
        async def api_load_plugin(plugin_id: str):
            """加载指定插件。"""
            self._init_plugins()
            success = self._plugin_manager.load(plugin_id)
            return {"success": success}

        @app.post("/api/plugins/{plugin_id}/unload")
        async def api_unload_plugin(plugin_id: str):
            """卸载指定插件。"""
            self._init_plugins()
            success = self._plugin_manager.unload(plugin_id)
            return {"success": success}

        @app.get("/api/plugins/{plugin_id}/tools")
        async def api_get_plugin_tools(plugin_id: str):
            """获取指定插件的工具列表。"""
            self._init_plugins()
            plugin = self._plugin_manager.get_plugin(plugin_id)
            if not plugin:
                return {"error": "插件未找到"}
            return {"tools": plugin.tools, "enabled": plugin.enabled}

        # ── 主机工具链：单工具屏蔽/恢复 ──

        @app.post("/api/plugins/com.claudez.plugins.host-tools/tools/{tool_name}/mask")
        async def api_mask_host_tool(tool_name: str):
            """屏蔽单个主机工具（不再挂载给 Agent）。"""
            pm = self._plugin_manager
            plugin = pm.get_plugin("com.claudez.plugins.host-tools")
            if not plugin or not plugin.instance:
                return {"success": False, "message": "插件未加载"}
            if not hasattr(plugin.instance, 'mask_tool'):
                return {"success": False, "message": "不支持"}
            ok = plugin.instance.mask_tool(tool_name)
            if ok:
                # 从 ToolRegistry 注销
                from agent.tools import get_registry
                get_registry().unregister_host_tool(tool_name)
                # 刷新插件工具列表
                plugin.tools = plugin.instance.get_tools()
                return {"success": True}
            return {"success": False, "message": "工具未找到"}

        @app.post("/api/plugins/com.claudez.plugins.host-tools/tools/{tool_name}/unmask")
        async def api_unmask_host_tool(tool_name: str):
            """恢复被屏蔽的主机工具。"""
            pm = self._plugin_manager
            plugin = pm.get_plugin("com.claudez.plugins.host-tools")
            if not plugin or not plugin.instance:
                return {"success": False, "message": "插件未加载"}
            if not hasattr(plugin.instance, 'unmask_tool'):
                return {"success": False, "message": "不支持"}
            plugin.instance.unmask_tool(tool_name)
            # 重新注册到 ToolRegistry
            meta = {"name": tool_name}
            for rule in getattr(plugin.instance, '_probe_rules', []):
                if rule.get("name") == tool_name:
                    meta = rule
                    break
            from agent.tools import get_registry
            get_registry().register_host_tool(tool_name, meta, plugin)
            # 刷新工具列表
            plugin.tools = plugin.instance.get_tools()
            return {"success": True}

        @app.get("/{filename:path}")
        async def serve_static(filename: str):
            if filename.startswith("api/"):
                return HTMLResponse("Not Found", status_code=404)
            file_path = (STATIC_DIR / filename).resolve()
            if not str(file_path).startswith(str(STATIC_DIR.resolve())):
                return HTMLResponse("Forbidden", status_code=403)
            if not file_path.exists() or not file_path.is_file():
                return HTMLResponse("Not Found", status_code=404)
            content = file_path.read_bytes()
            ext = file_path.suffix.lower()
            media_types = {
                '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css',
                '.png': 'image/png', '.svg': 'image/svg+xml', '.ico': 'image/x-icon',
            }
            return Response(
                content=content,
                media_type=media_types.get(ext, 'text/plain'),
                headers={
                    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                    "Pragma": "no-cache", "Expires": "0",
                }
            )

    # ── 生命周期 ──

    def start(self) -> int:
        if self.port == 0:
            self.port = _find_free_port()
        config = uvicorn.Config(
            self.app, host=self.host, port=self.port,
            log_level="warning", access_log=False,
        )
        self._server = uvicorn.Server(config=config)
        self._thread = threading.Thread(
            target=self._server.run, daemon=True,
            name="claudez-web-server",
        )
        self._thread.start()
        return self.port

    def stop(self):
        with self._sse_lock:
            for q in self._sse_queues:
                try:
                    q.put_nowait(None)
                except Exception:
                    pass
            self._sse_queues.clear()
        if self._server:
            self._server.should_exit = True
        if self._thread:
            self._thread.join(timeout=5)

    def get_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def _run_with_handler(self, text: str, handler: WebStreamHandler):
        """通过 handler 桥接执行 Agent。"""
        agent = self.agent

        # 挂载回调
        agent.on_stream = handler.on_text
        agent.on_thinking = handler.on_thinking
        agent.on_tool_start = handler.on_tool_start
        agent.on_tool_call = lambda n, a, r: handler.on_tool_result(r)
        agent.on_tool_output = lambda n, line: self._push_sse("tool_output", {
            "tool_name": n, "line": line,
        })

        result = agent.run(text)
        # 文本已通过 on_stream 逐块推送，不需要再 push 一遍
        # 但如果流式回调未覆盖（如无 stream 的场景），在这里兜底
        if result and not agent.on_stream:
            handler.on_text(result)

    def _push_sse(self, event_type: str, payload: Any):
        with self._sse_lock:
            for q in self._sse_queues:
                try:
                    q.put_nowait({"type": event_type, "payload": payload})
                except q_module.Full:
                    pass


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start(host: str = "127.0.0.1", port: int = 0, agent=None) -> WebServer:
    ws = WebServer(agent)
    ws.host = host
    if port:
        ws.port = port
    # port == 0 自动随机端口
    actual_port = ws.start()
    url = f"http://{host}:{actual_port}"
    print(f"\n  [ClaudeZ] Web GUI")
    print(f"  {'='*40}")
    print(f"  URL: {url}")
    print(f"  Exit: Ctrl+C\n")

    # 自动打开浏览器
    try:
        import webbrowser
        webbrowser.open(url)
    except Exception:
        pass

    return ws
