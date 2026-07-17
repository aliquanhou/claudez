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
