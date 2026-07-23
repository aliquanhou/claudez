"""tools/registry — 工具注册表（Pydantic 升级版）。

参考 Claude Code 的工具系统设计：
  - Tool 类：Pydantic Schema + readonly + concurrency_safe
  - @tool 装饰器保持兼容
  - 运行时参数校验
  - 统一格式生成（OpenAI + Anthropic）
  - 执行上下文
"""

from __future__ import annotations

import inspect
import json
from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel, Field

from .schema import Tool, ToolContext, ToolResult

# 向后兼容
ToolDef = Tool


# ── 注册表 ──

class ToolRegistry:
    """全局工具注册表（Pydantic 版）。"""

    def __init__(self):
        self._tools: dict[str, Tool] = {}
        self._context = ToolContext()
        self._host_tool_plugins: dict = {}

    def set_context(self, ctx: ToolContext):
        """设置全局执行上下文。"""
        self._context = ctx

    def register(self, fn: Callable | None = None, *,
                 name: str | None = None,
                 description: str | None = None,
                 category: str = "general",
                 timeout: float = 60.0,
                 require_confirmation: bool = False,
                 is_readonly: bool = False,
                 is_concurrency_safe: bool = False) -> Callable:
        """注册工具（装饰器或直接调用）。

        升级：支持 is_readonly / is_concurrency_safe 标记。
        """
        def _register(f: Callable) -> Callable:
            nonlocal name, description
            if name is None:
                name = f.__name__
            if description is None:
                description = (f.__doc__ or "").strip()

            # 创建 Pydantic Schema
            sig = inspect.signature(f)
            fields = {}
            required = []

            for pname, param in sig.parameters.items():
                if pname in ("self", "cls"):
                    continue

                py_type = param.annotation if param.annotation != inspect.Parameter.empty else str
                default = param.default if param.default != inspect.Parameter.empty else ...

                # 提取描述（从 docstring 或参数注解）
                pdesc = ""
                if default is not ...:
                    fields[pname] = (py_type, Field(default=default, description=pdesc))
                else:
                    fields[pname] = (py_type, Field(..., description=pdesc))
                    required.append(pname)

            # 动态创建 Pydantic model
            if fields:
                input_model = BaseModel.__class__.__new__(
                    BaseModel.__class__, f"{name.capitalize()}Input",
                    (BaseModel,),
                    {"__annotations__": {n: t for n, (t, _) in fields.items()}},
                )
                for n, (_, fld) in fields.items():
                    setattr(input_model, n, fld)
            else:
                input_model = BaseModel

            # 创建 Tool 实例
            tool = Tool(
                name=name,
                description=description,
                input_schema=input_model,
                category=category,
                is_readonly=is_readonly,
                is_concurrency_safe=is_concurrency_safe,
                timeout=timeout,
                require_confirmation=require_confirmation,
            )(f)

            self._tools[name] = tool
            return f

        if fn is not None:
            return _register(fn)
        return _register

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def get_all(self) -> list[dict]:
        """获取 OpenAI 兼容格式。"""
        return [t.to_openai_tool() for t in sorted(self._tools.values(), key=lambda t: t.name)]

    def get_all_tools(self) -> list[Tool]:
        """获取所有 Tool 实例。"""
        return list(self._tools.values())

    def get_openai_tools(self) -> list[dict]:
        return self.get_all()

    def get_anthropic_tools(self) -> list[dict]:
        return [t.to_anthropic_tool() for t in sorted(self._tools.values(), key=lambda t: t.name)]

    def get_readonly_tools(self) -> list[Tool]:
        """获取所有只读工具（用于权限判断）。"""
        return [t for t in self._tools.values() if t.is_readonly]

    def get_mutating_tools(self) -> list[Tool]:
        """获取所有写工具。"""
        return [t for t in self._tools.values() if not t.is_readonly]

    def execute(self, name: str, args: dict, timeout: float | None = None) -> str:
        """执行工具（返回字符串结果，兼容旧接口）。"""
        tool = self._tools.get(name)
        if not tool:
            return f"[错误] 未知工具: {name}"

        result = tool.execute(args, self._context)
        return result.to_str()

    def execute_typed(self, name: str, args: dict) -> ToolResult:
        """执行工具（返回结构化结果）。"""
        tool = self._tools.get(name)
        if not tool:
            return ToolResult(error=f"未知工具: {name}")
        return tool.execute(args, self._context)

    # ── 主机工具（插件）管理 ──

    def register_host_tool(self, name: str, tool_def: dict, plugin_info=None):
        """注册主机工具（来自插件）。

        创建一个带有 args 参数的 Tool 对象，LLM 可见并可调用。
        tool_def 格式:
          {
              "name": "node",
              "display_name": "Node.js",
              "version": "v20.11.0",
              "category": "command",
              "icon": "🔵",
              "exec_path": "/usr/bin/node",
              "description": "...",
          }
        """
        from pydantic import BaseModel, Field

        # 为宿主工具动态创建输入 Schema，使 LLM 知道如何传参
        exec_path = tool_def.get("exec_path", name)

        class HostToolInput(BaseModel):
            args: str = Field(
                default="",
                description=f"传给 {name} 的命令行参数，例如 '--version' 或 'hello.py'"
            )

        def execute_host(args: str = "") -> str:
            """执行主机工具。"""
            return self._execute_host_tool(name, args)

        desc = tool_def.get("description", tool_def.get("display_name", name))
        desc += f" (路径: {exec_path})"
        cat = tool_def.get("category", "general")

        tool = Tool(
            name=name,
            description=desc,
            input_schema=HostToolInput,
            category=cat,
            is_readonly=True,
            is_concurrency_safe=False,
            timeout=60,
        )(execute_host)

        self._tools[name] = tool
        if plugin_info:
            self._host_tool_plugins[name] = plugin_info

    def unregister_host_tool(self, name: str):
        """注销主机工具。"""
        self._tools.pop(name, None)
        self._host_tool_plugins.pop(name, None)

    def get_host_tools(self) -> list[dict]:
        """获取所有主机工具定义。"""
        result = []
        for name, plugin_info in self._host_tool_plugins.items():
            tool = self._tools.get(name)
            if tool:
                result.append({
                    "name": name,
                    "display_name": name,
                    "category": tool.category,
                    "source": "host",
                    "plugin_id": plugin_info.id if plugin_info else "",
                })
        return result

    def _execute_host_tool(self, name: str, args: str) -> str:
        """执行主机工具（委托给插件管理器）。"""
        from ..plugin_manager import get_plugin_manager
        pm = get_plugin_manager()
        plugin_info = self._host_tool_plugins.get(name)
        if not plugin_info:
            return f"[错误] 主机工具 {name} 没有关联插件"
        result = pm.execute(plugin_info.id, name, args.split() if args else [])
        if "error" in result:
            return f"[错误] {result['error']}"
        return result.get("output", str(result))

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)


# ── 流式输出回调（线程局部） ──
# 工具函数通过这个回调实时推送输出
import threading as _threading
_stream_output: _threading.local = _threading.local()


def set_stream_callback(callback: Callable[[str], None] | None):
    """设置当前线程的工具流式输出回调。"""
    _stream_output.callback = callback


def get_stream_callback() -> Callable[[str], None] | None:
    """获取当前线程的工具流式输出回调。"""
    return getattr(_stream_output, 'callback', None)


# ── 全局实例 ──

_REGISTRY: ToolRegistry | None = None


def get_registry() -> ToolRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = ToolRegistry()
    return _REGISTRY


def create_isolated_registry() -> ToolRegistry:
    """创建一个隔离的工具注册表（不修改全局单例，供子 Agent 使用）。"""
    return ToolRegistry()


def tool(fn=None, *, name=None, description=None, category="general",
         timeout=60.0, require_confirmation=False,
         is_readonly=False, is_concurrency_safe=False):
    """工具注册装饰器（升级版）。

    新增参数:
      is_readonly: 标记为只读（用于权限控制）
      is_concurrency_safe: 标记为可并发执行
    """
    registry = get_registry()
    return registry.register(
        fn, name=name, description=description,
        category=category, timeout=timeout,
        require_confirmation=require_confirmation,
        is_readonly=is_readonly, is_concurrency_safe=is_concurrency_safe,
    )


def get_all_tools() -> list[dict]:
    return get_registry().get_all()


def execute_tool(name: str, args: dict, timeout: float | None = None) -> str:
    return get_registry().execute(name, args, timeout)
