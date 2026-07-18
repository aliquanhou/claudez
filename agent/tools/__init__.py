"""ClaudeZ 工具系统。

工具注册、执行、描述自动生成。
每个工具是一个函数，通过 @tool 装饰器注册。
"""

from .registry import ToolRegistry, tool, get_registry, get_all_tools, execute_tool

# 导入所有工具模块以触发注册
from . import builtin
from . import subagent
from . import workflow_tool
from . import artifact
from . import webhook_tool
