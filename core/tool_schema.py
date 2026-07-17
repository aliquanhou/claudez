"""tool_schema — 工具类型定义（统一注册表别名）。

此模块已合并到 agent/tools/registry.py + agent/tools/schema.py。
保留此文件为向后兼容导入。
"""

from agent.tools.registry import ToolRegistry, ToolDef, tool, get_registry
from agent.tools.schema import ToolResult, ToolContext

# 向后兼容
ToolRegistrySDK = ToolRegistry
get_sdk_registry = get_registry
sdk_tool = tool
