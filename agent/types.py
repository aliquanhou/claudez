"""types — 消息内容块类型系统。

参考 Claude Code 消息类型设计：
  - AssistantMessage 可包含多个 ContentBlock
  - ContentBlock 类型：TextBlock / ThinkingBlock / ToolUseBlock
  - 每条消息 = 多个块的序列，块之间可以交错

Claude API 流式响应：
  content_block_start (text, index=0)
  content_block_delta (text_delta)     → 实时文本
  content_block_stop (index=0)         → TextBlock 完成
  content_block_start (tool_use, index=1)
  content_block_delta (input_json_delta) → 工具 JSON 参数片段
  content_block_stop (index=1)         → ToolUseBlock 完成
  content_block_start (text, index=2)
  content_block_delta (text_delta)
  content_block_stop (index=2)         → TextBlock 完成
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ── 内容块类型 ──

class BlockType(str, Enum):
    TEXT = "text"
    THINKING = "thinking"
    TOOL_USE = "tool_use"
    TOOL_RESULT = "tool_result"


# ── 内容块 ──

@dataclass
class ContentBlock:
    """单个内容块。

    对应 Claude API 的 content_block：
      - text: content + 签名
      - thinking: content + 签名
      - tool_use: name + input（JSON 对象）+ id
      - tool_result: tool_use_id + content
    """
    type: BlockType
    index: int = 0
    content: str = ""
    signature: str = ""        # thinking 块签名
    tool_name: str = ""        # tool_use 时
    tool_input: dict = field(default_factory=dict)  # tool_use 时
    tool_call_id: str = ""     # tool_use 时
    partial: bool = True       # 是否尚未完成（流式中间态）

    def is_complete(self) -> bool:
        """块是否已完成。"""
        return not self.partial

    def is_text(self) -> bool:
        return self.type == BlockType.TEXT

    def is_thinking(self) -> bool:
        return self.type == BlockType.THINKING

    def is_tool_use(self) -> bool:
        return self.type == BlockType.TOOL_USE

    def to_dict(self) -> dict:
        d = {"type": self.type.value, "index": self.index, "partial": self.partial}
        if self.content:
            d["content"] = self.content
        if self.tool_name:
            d["tool_name"] = self.tool_name
        if self.tool_input:
            d["tool_input"] = self.tool_input
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        return d

    @classmethod
    def text(cls, content: str = "", index: int = 0) -> ContentBlock:
        return cls(type=BlockType.TEXT, index=index, content=content)

    @classmethod
    def thinking(cls, content: str = "", signature: str = "", index: int = 0) -> ContentBlock:
        return cls(type=BlockType.THINKING, index=index, content=content, signature=signature)

    @classmethod
    def tool_use(cls, name: str, tool_input: dict | None = None,
                 call_id: str = "", index: int = 0) -> ContentBlock:
        return cls(type=BlockType.TOOL_USE, index=index,
                   tool_name=name, tool_input=tool_input or {},
                   tool_call_id=call_id)

    def __repr__(self) -> str:
        if self.type == BlockType.TEXT:
            return f"TextBlock({self.content[:50]}{'...' if len(self.content) > 50 else ''})"
        if self.type == BlockType.THINKING:
            return f"ThinkingBlock({len(self.content)} chars)"
        if self.type == BlockType.TOOL_USE:
            return f"ToolUseBlock({self.tool_name})"
        return f"ContentBlock({self.type.value})"


# ── 消息 ──

@dataclass
class Message:
    """一条消息，包含多个内容块。

    对应 Claude API 的 Message 对象：
      - role: user / assistant / system / tool
      - content: ContentBlock 列表
      - 支持的块类型组合：
        - assistant: [Text], [Text, ToolUse, Text], [Thinking, Text, ToolUse], ...
        - user: [Text] 或 [ToolResult]
        - tool: [ToolResult]
    """
    role: str = "user"
    blocks: list[ContentBlock] = field(default_factory=list)
    id: str = ""
    timestamp: float = 0.0
    stop_reason: str = ""

    def add_block(self, block: ContentBlock):
        self.blocks.append(block)

    def get_text(self) -> str:
        """获取所有 TextBlock 的拼接内容。"""
        return "".join(b.content for b in self.blocks if b.is_text())

    def get_thinking(self) -> str:
        """获取所有 ThinkingBlock 的拼接内容。"""
        return "".join(b.content for b in self.blocks if b.is_thinking())

    def get_tool_calls(self) -> list[dict]:
        """获取所有 ToolUseBlock 的工具调用（兼容旧格式）。"""
        return [
            {"id": b.tool_call_id, "name": b.tool_name, "args": b.tool_input}
            for b in self.blocks if b.is_tool_use()
        ]

    def to_api_messages(self) -> list[dict]:
        """转换为 API 消息格式。

        处理规则：
          - 如果只有文本 → {"role", "content"}
          - 如果有 tool_use → {"role", "content", "tool_calls"}
          - 如果是 tool result → {"role": "tool", "tool_call_id", "content"}
        """
        if self.role == "tool":
            tool_blocks = [b for b in self.blocks if b.is_text()]
            return [{
                "role": "tool",
                "tool_call_id": self.id,
                "content": "".join(b.content for b in tool_blocks),
            }]

        result = {"role": self.role}
        text = self.get_text()
        tool_calls = self.get_tool_calls()

        if text is not None:
            result["content"] = text if text else None
        if tool_calls:
            result["tool_calls"] = [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": json.dumps(tc["args"], ensure_ascii=False),
                    },
                }
                for tc in tool_calls
            ]
        return result

    def is_empty(self) -> bool:
        return not self.blocks

    def __repr__(self) -> str:
        types = [b.type.value for b in self.blocks]
        return f"Message({self.role}, {types})"


# ── 辅助函数 ──

def message_from_api(role: str, content: Any) -> Message:
    """从 API 响应创建一个 Message。"""
    import time
    msg = Message(role=role, timestamp=time.time())

    if isinstance(content, str):
        # 纯文本
        if content:
            msg.add_block(ContentBlock.text(content))
    elif isinstance(content, dict):
        # 工具调用格式
        if "tool_calls" in content:
            for tc in content["tool_calls"]:
                msg.add_block(ContentBlock.tool_use(
                    name=tc.get("function", {}).get("name", ""),
                    tool_input=json.loads(tc.get("function", {}).get("arguments", "{}")),
                    call_id=tc.get("id", ""),
                ))
        text = content.get("content", "")
        if text:
            msg.add_block(ContentBlock.text(text))
    elif isinstance(content, list):
        for item in content:
            if isinstance(item, str):
                msg.add_block(ContentBlock.text(item))

    return msg
