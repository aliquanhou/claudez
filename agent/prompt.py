"""prompt — ClaudeZ 动态系统提示词引擎。

设计哲学：
  系统提示词不是"一次性配置"，而是每次决策前的"状态快照"。
  每次 LLM 调用前，根据当前上下文动态构建完整的系统提示词。

核心能力：
  1. 工具列表动态注入 — 根据实际注册的工具实时生成
  2. 工作流模式切换 — chat / research / coding / debug / custom
  3. 自适应调整 — 根据对话历史、错误率、轮次动态调整行为约束
  4. 记忆注入 — 语义记忆 + 短期记忆 + 项目上下文
  5. 约束条件动态生成 — 权限、超时、语言、禁止操作

架构：
  DynamicPromptBuilder
    ├── _build_role()          — 角色定义（固定）
    ├── _build_tools()         — 工具列表（动态）
    ├── _build_workflow()      — 工作流（动态，根据模式）
    ├── _build_constraints()   — 约束条件（动态）
    ├── _build_memory()        — 记忆上下文（动态）
    ├── _build_adaptations()   — 自适应调整（动态）
    └── _build_examples()      — 示例（动态，根据场景）
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable


# ── 角色定义模板 ──

ROLE_TEMPLATE = """你是 ClaudeZ，一个工具驱动的 AI 智能体。

## ⚡ 核心规则（必须遵守）
1. **专注用户目标**：用户第一次说的请求就是核心任务，不要偏离做无关探索。
2. **输出 = 工具调用的结果汇报**。你的文本输出只能是对工具调用结果的总结。
3. **禁止空谈**：收到需求后第一反应必须是调用工具，不要用文字回复。
4. **大批量用并行**：需要创建多个文件或多条命令时，**同时调用多个工具**。
5. **一步到位**：完成用户请求所需的所有工具一次执行完，不要"做一步问一步"。
6. **批量读文件用 bash cat**：需要读取多个小文件（如源码、XML、配置），**不要逐个调用 read**，而是用 `bash` + `cat file1 file2 file3` 或 `type file1 file2 file3` 一次搞定。
7. **工作空间规则**：你的工作根目录是 workspace_root。bash 工具会自动 cd 到该目录，所以你只需用相对路径。write/read/edit 等文件操作也基于工作空间根目录。
8. **"写网页" = 创建 HTML 文件**：当用户说"写一个网页"，直接用 write 工具创建 .html 文件并写入内容。不要启动 HTTP 服务器，不要用 bash 运行 python/web 服务。完成后告诉用户文件路径，让用户自己用浏览器打开。

## ❌ 禁止
- 严禁"逐模块验证"循环——不要逐个文件检查/逐个import测试
- 严禁逐个读取文件——用 bash cat/type 一次读多个
- 严禁在工具调用之间输出"思考中..."中转文字
- 严禁向用户提问"接下来做什么"——直接决定下一步并执行
- 不要描述计划——直接调用工具执行
- **不要重复安装已存在的工具**——检查 `where` 或 `which`，如果已安装直接用
- **不要启动 HTTP 服务器** 除非用户明确要求"启动一个服务"

## 命令执行经验（Windows 环境）
- Windows 系统用 `Expand-Archive` 解压 `.zip`，不是 `tar`
- 已安装的工具不要重下——Java/Gradle/Node.js 已存在就直接用
- 路径用反斜杠，PowerShell 调用 exe
- 如果命令报错，仔细看错误信息并精确修复，不要盲目换命令
- `curl` 在 Windows 上是 PowerShell 的别名（不是真正的 curl），下载大文件用 `Invoke-WebRequest`"""


# ── 工作流模板 ──

WORKFLOW_TEMPLATES = {
    "chat": """
## 工作流：对话模式
1. 直接回答用户问题
2. 仅当需要外部信息时才调用工具
3. 保持对话自然流畅
4. 复杂问题可拆解为多步
""",

    "research": """
## 工作流：研究模式
1. 拆解问题为多个子问题
2. 每个子问题调用搜索/读取工具
3. 交叉验证不同来源的信息
4. 综合所有信息给出结论
5. 标注信息来源
""",

    "coding": """
## 工作流：编程模式
1. 分析需求或问题
2. 设计解决方案
3. 生成可运行的代码
4. 执行测试验证
5. 解释修改原因
""",

    "debug": """
## 工作流：调试模式
1. 读取错误信息/日志
2. 分析可能原因（调用链、依赖、环境）
3. 定位根因
4. 生成修复方案
5. 验证修复
6. 如失败，回到步骤 2
""",

    "agent": """
## 工作流：Agent 模式
1. 听到需求 → **立即用工具执行**，不要先回复文字
2. 如果需要信息 → 直接调 read/grep/web_search 获取
3. 如果需要操作 → 直接调 bash/write/edit 执行
4. 每调完一个工具 → 检查结果并决定下一步
5. 所有步骤完成后 → 用自然语言总结汇报
6. 遇到问题 → 换工具或换参数重试
""",
}


# ── 约束条件模板 ──

def _build_constraints_block(constraints: dict) -> str:
    """根据约束字典生成约束条件块。"""
    if not constraints:
        return ""

    lines = ["## 约束条件"]
    for key, value in constraints.items():
        if key == "max_tool_calls":
            lines.append(f"- 最多调用 {value} 次工具")
        elif key == "tool_timeout":
            lines.append(f"- 单次工具调用超时：{value} 秒")
        elif key == "response_language":
            lines.append(f"- 使用 {value} 回答")
        elif key == "forbidden_actions":
            items = ", ".join(value) if isinstance(value, list) else value
            lines.append(f"- 禁止操作：{items}")
        elif key == "max_turns":
            lines.append(f"- 最多 {value} 轮对话")
        elif key == "require_confirmation":
            lines.append(f"- 以下操作需要用户确认：{', '.join(value)}")
        else:
            lines.append(f"- {key}: {value}")

    return "\n".join(lines)


# ── 自适应调整 ──

def _build_adaptations_block(session_state: dict) -> str:
    """根据会话状态动态生成自适应提示。"""
    blocks = []

    # 工具错误检测
    error_count = session_state.get("tool_error_count", 0)
    if error_count > 3:
        blocks.append("""
## ⚠️ 注意：工具调用错误较多
请仔细检查：
1. 参数名称和类型是否正确
2. 必填参数是否都已提供
3. 如果持续失败，改用其他方式回答
""")
    elif error_count > 0:
        blocks.append(f"""
## 💡 提示：最近有 {error_count} 次工具调用错误
请检查参数格式后再试。
""")

    # 对话轮次检测
    turn_count = session_state.get("turn_count", 0)
    if turn_count > 10:
        blocks.append("""
## 📌 提示：对话已进行多轮
1. 总结之前的讨论要点
2. 确认用户的核心需求
3. 避免重复询问相同信息
""")

    # 重复工具检测
    repeated_tools = session_state.get("repeated_tools", [])
    if repeated_tools:
        tools_str = ", ".join(repeated_tools[-3:])
        blocks.append(f"""
## 🔄 检测到重复调用：{tools_str}
如果该工具持续失败，请换一种策略。
""")

    # 长时间运行
    elapsed = session_state.get("elapsed_seconds", 0)
    if elapsed > 300:
        blocks.append(f"""
## ⏱ 已运行 {elapsed//60} 分钟
如果任务卡住，考虑：
1. 拆分为更小的步骤
2. 使用后台模式运行
3. 向用户报告当前进度
""")

    return "\n".join(blocks)


# ── 工具描述生成 ──

def _build_tools_block(tools: list[dict]) -> str:
    """将工具定义转换为 LLM 可读的描述文本。

    格式：
      tool_name(param1: type, param2: type) — 描述
        参数说明：
          param1* (string) — 描述（* = 必填）
          param2 (integer) — 描述

    Args:
        tools: 工具定义列表（OpenAI 兼容格式）

    Returns:
        格式化的工具描述文本
    """
    if not tools:
        return "## 可用工具\n当前无可用工具，请直接回答用户问题。"

    lines = ["## 可用工具", ""]
    for tool in tools:
        func = tool.get("function", {})
        name = func.get("name", "?")
        desc = func.get("description", "")
        params = func.get("parameters", {})
        properties = params.get("properties", {})
        required = params.get("required", [])

        # 参数签名
        sig_parts = []
        for pname, pinfo in properties.items():
            ptype = pinfo.get("type", "string")
            if pname in required:
                sig_parts.append(f"{pname}: {ptype}")
            else:
                sig_parts.append(f"[{pname}: {ptype}]")

        sig = ", ".join(sig_parts)
        lines.append(f"### {name}({sig})")
        if desc:
            lines.append(f"{desc}")
        if properties:
            lines.append("参数：")
            for pname, pinfo in properties.items():
                ptype = pinfo.get("type", "string")
                pdesc = pinfo.get("description", "")
                marker = " *必填" if pname in required else ""
                lines.append(f"  - {pname}: {ptype}{marker}")
                if pdesc:
                    lines.append(f"    {pdesc}")
        lines.append("")

    return "\n".join(lines)


# ── 记忆上下文注入 ──

def _build_memory_block(memories: list[dict] | None, max_items: int = 5,
                        short_memories: dict | None = None) -> str:
    """将记忆注入提示词。

    Args:
        memories: 语义记忆搜索结果
        max_items: 最大条目数
        short_memories: 短期记忆（facts/notes/tasks）
    """
    parts = []

    # 短期记忆（当前会话内的关键信息）
    if short_memories:
        facts = short_memories.get("facts", {})
        if facts:
            parts.append("## 当前会话信息")
            for k, v in facts.items():
                parts.append(f"- {k}: {v}")
        notes = short_memories.get("notes", [])
        if notes:
            for n in notes:
                parts.append(f"- [{n.get('category','general')}] {n.get('content','')}")

    # 长期语义记忆（跨会话）
    if memories:
        parts.append("## 相关长期记忆")
        for m in memories[:max_items]:
            content = m.get("content", "")
            if len(content) > 200:
                content = content[:200] + "..."
            parts.append(f"- {content}")

    return "\n".join(parts)


# ── 项目上下文注入 ──

def _build_project_context(project_info: dict | None) -> str:
    """注入项目上下文信息。"""
    if not project_info:
        return ""

    lines = ["## 项目上下文"]
    if "name" in project_info:
        lines.append(f"项目：{project_info['name']}")
    if "root" in project_info:
        lines.append(f"根目录：{project_info['root']}")
    if "language" in project_info:
        lines.append(f"语言：{project_info['language']}")
    if "files" in project_info:
        lines.append(f"文件数：{project_info['files']}")

    return "\n".join(lines)


# ── 示例注入 ──

EXAMPLES = {
    "chat": [],
    "coding": [
        {
            "user": "帮我写一个 Python 函数，计算斐波那契数列",
            "assistant": "好的，我来写一个高效的斐波那契函数：\n\n```python\ndef fibonacci(n: int) -> int:\n    \"\"\"计算第 n 个斐波那契数。\"\"\"\n    if n <= 1:\n        return n\n    a, b = 0, 1\n    for _ in range(2, n + 1):\n        a, b = b, a + b\n    return b\n```\n\n这个实现使用迭代而非递归，时间复杂度 O(n)，空间复杂度 O(1)。"
        }
    ],
    "research": [
        {
            "user": "Python 3.13 有什么新特性？",
            "assistant": "让我搜索一下最新信息。\n\n[调用 web_search 工具]\n\n根据搜索结果，Python 3.13 的主要新特性包括：\n1. 自由线程（no-GIL）模式\n2. JIT 编译器（实验性）\n3. 改进的交互式解释器\n...\n\n信息来源：python.org 官方文档"
        }
    ],
    "debug": [
        {
            "user": "我的程序报错：KeyError: 'name'",
            "assistant": "让我分析这个错误。\n\n[调用 read 工具读取代码]\n\n错误原因：在访问字典时使用了不存在的键 'name'。\n\n修复方案：使用 dict.get() 方法或先检查键是否存在。"
        }
    ]
}


def _build_examples_block(mode: str, count: int = 1) -> str:
    """根据工作流模式注入示例。"""
    examples = EXAMPLES.get(mode, [])
    if not examples:
        return ""

    lines = ["## 示例"]
    for ex in examples[:count]:
        lines.append(f"用户：{ex['user']}")
        lines.append(f"ClaudeZ：{ex['assistant']}")
        lines.append("")

    return "\n".join(lines)


# ── 动态提示词构建器 ──

@dataclass
class PromptContext:
    """构建提示词的上下文。"""
    user_id: str = "default"
    tools: list[dict] | None = None
    workflow_mode: str = "chat"
    constraints: dict | None = None
    memories: list[dict] | None = None
    short_memories: dict | None = None
    """短期记忆上下文（事实、笔记、任务栈）"""
    project_info: dict | None = None
    session_state: dict | None = None
    custom_sections: list[tuple[str, str]] | None = None
    """自定义节段列表，每项为 (标题, 内容)"""


class DynamicPromptBuilder:
    """动态系统提示词构建器。

    每次调用 build() 都会根据当前上下文重新生成完整的提示词。
    这是 ClaudeZ 的核心能力——每次 LLM 决策前都有一份"状态快照"。
    """

    def __init__(self):
        self._sections: list[Callable] = [
            ("role", lambda ctx: ROLE_TEMPLATE),
            ("tools", lambda ctx: _build_tools_block(ctx.tools)),
            ("workflow", lambda ctx: WORKFLOW_TEMPLATES.get(ctx.workflow_mode, WORKFLOW_TEMPLATES["chat"])),
            ("constraints", lambda ctx: _build_constraints_block(ctx.constraints or {})),
            ("memory", lambda ctx: _build_memory_block(ctx.memories, short_memories=ctx.short_memories)),
            ("project", lambda ctx: _build_project_context(ctx.project_info)),
            ("adaptations", lambda ctx: _build_adaptations_block(ctx.session_state or {})),
            ("examples", lambda ctx: _build_examples_block(ctx.workflow_mode)),
        ]

    def build(self, context: PromptContext) -> str:
        """构建完整的系统提示词。

        Args:
            context: 提示词上下文

        Returns:
            完整的系统提示词字符串
        """
        parts = []

        for name, builder in self._sections:
            content = builder(context)
            if content.strip():
                parts.append(content)

        # 添加自定义节段
        if context.custom_sections:
            for title, content in context.custom_sections:
                if content.strip():
                    parts.append(f"## {title}\n{content}")

        return "\n\n".join(parts)

    def register_section(self, name: str, builder: Callable, position: int | None = None):
        """注册自定义节段构建器。

        Args:
            name: 节段名称
            builder: 接收 PromptContext 返回字符串的函数
            position: 插入位置（None = 末尾）
        """
        section = (name, builder)
        if position is None:
            self._sections.append(section)
        else:
            self._sections.insert(position, section)


# ── 全局实例 ──

_BUILDER: DynamicPromptBuilder | None = None


def get_builder() -> DynamicPromptBuilder:
    """获取全局提示词构建器实例。"""
    global _BUILDER
    if _BUILDER is None:
        _BUILDER = DynamicPromptBuilder()
    return _BUILDER


def build_system_prompt(context: PromptContext) -> str:
    """便捷函数：构建系统提示词。

    Args:
        context: 提示词上下文

    Returns:
        完整的系统提示词
    """
    return get_builder().build(context)
