"""tools/schema — Pydantic 工具 Schema 系统。

参考 Claude Code 的 Tool 接口设计：
  - Pydantic 定义严格参数 Schema
  - readonly 标记用于权限控制
  - concurrency_safe 标记用于并发执行
  - 结果截断（默认 6000 字符）
  - 执行前校验
"""

from __future__ import annotations

import json
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel, ValidationError


# ── 默认截断大小 ──

DEFAULT_RESULT_TRUNCATE = 6000  # Claude Code 标准


# ── 工具执行上下文 ──

@dataclass
class ToolContext:
    """工具执行上下文。"""
    session_id: str = ""
    user_id: str = ""
    permission_mode: str = "auto"  # auto | ask | deny
    working_dir: str = ""
    audit_log: list[dict] = field(default_factory=list)


# ── 工具结果 ──

@dataclass
class ToolResult:
    """结构化工具执行结果。"""
    content: str = ""
    truncated: bool = False
    error: str | None = None
    duration_ms: float = 0.0
    cached: bool = False
    raw: Any = None

    def to_str(self) -> str:
        if self.error:
            return f"[错误] {self.error}"
        if self.truncated:
            return self.content + f"\n... (结果已截断，共 {len(self.content)} 字符)"
        return self.content


# ── 工具定义 ──

class Tool:
    """Claude Code 风格工具定义。

    用法:
        class ReadInput(BaseModel):
            file_path: str = Field(description="文件路径")
            head: int = Field(0, description="前 N 行")

        read_tool = Tool(
            name="read",
            description="读取文件内容",
            input_schema=ReadInput,
            is_readonly=True,
            is_concurrency_safe=True,
        )(my_read_fn)
    """

    def __init__(
        self,
        name: str,
        description: str,
        input_schema: type[BaseModel] | None = None,
        *,
        category: str = "general",
        is_readonly: bool = False,
        is_concurrency_safe: bool = False,
        timeout: float = 60.0,
        require_confirmation: bool = False,
        result_truncate: int = DEFAULT_RESULT_TRUNCATE,
    ):
        self.name = name
        self.description = description
        self.input_schema = input_schema or BaseModel
        self.category = category
        self.is_readonly = is_readonly
        self.is_concurrency_safe = is_concurrency_safe
        self.timeout = timeout
        self.require_confirmation = require_confirmation
        self.result_truncate = result_truncate
        self.fn: Callable | None = None

    def __call__(self, fn: Callable) -> Tool:
        """装饰器模式绑定函数。"""
        self.fn = fn
        return self

    def validate(self, args: dict) -> tuple[bool, str, BaseModel | None]:
        """使用 Pydantic Schema 校验参数。"""
        if self.input_schema is BaseModel:
            return True, "", None
        try:
            validated = self.input_schema(**args)
            return True, "", validated
        except ValidationError as e:
            errors = "; ".join(f"{err['loc']}: {err['msg']}" for err in e.errors())
            return False, f"参数错误: {errors}", None

    def execute(self, args: dict, context: ToolContext | None = None) -> ToolResult:
        """执行工具（带校验 + 截断 + 错误处理）。"""
        import time

        start = time.time()

        # 校验
        valid, msg, validated = self.validate(args)
        if not valid:
            return ToolResult(error=msg, duration_ms=0)

        # 执行
        if self.fn is None:
            return ToolResult(error=f"工具 {self.name} 没有绑定的函数", duration_ms=0)

        try:
            if validated is not None:
                result = self.fn(**validated.model_dump())
            else:
                result = self.fn(**args)

            if result is None:
                result = "[完成]"
            result_str = str(result)

            # 截断
            truncated = False
            if len(result_str) > self.result_truncate:
                result_str = result_str[:self.result_truncate]
                truncated = True

            dur = (time.time() - start) * 1000
            return ToolResult(content=result_str, truncated=truncated, duration_ms=dur)

        except Exception as e:
            tb = traceback.format_exc()
            dur = (time.time() - start) * 1000
            return ToolResult(error=f"{self.name}: {e}\n{tb[:500]}", duration_ms=dur)

    def to_openai_tool(self) -> dict:
        """转换为 OpenAI 兼容格式。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self._get_parameters(),
            },
        }

    def to_anthropic_tool(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self._get_parameters(),
        }

    def _get_parameters(self) -> dict:
        if self.input_schema is BaseModel or self.input_schema is None:
            return {"type": "object", "properties": {}, "required": []}
        schema = self.input_schema.model_json_schema()
        # 移除 Pydantic 内部字段
        schema.pop("title", None)
        schema.pop("description", None)
        return schema
