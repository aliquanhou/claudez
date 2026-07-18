"""tools/memory_tool — 记忆系统工具。

让 LLM 可以在对话中主动存储/检索记忆。
Agent 主循环也会自动存储工具调用和对话摘要。
"""

from __future__ import annotations

import json
import time

from .registry import tool


@tool(category="memory", timeout=15, is_readonly=True, is_concurrency_safe=True)
def memory_search(query: str, top_k: int = 5) -> str:
    """搜索语义记忆，找到与查询相关的历史信息。

    Args:
        query: 搜索关键词或问题描述
        top_k: 返回结果数（1-10）
    """
    try:
        from agent.memory import get_semantic_memory
        mem = get_semantic_memory()
        if not mem:
            return "[记忆] 语义记忆未启用（ChromaDB 不可用）"
        results = mem.search(query, n_results=min(max(top_k, 1), 10))
        if not results:
            return "(无相关记忆)"
        lines = [f"找到 {len(results)} 条相关记忆:"]
        for i, r in enumerate(results, 1):
            content = r.get("content", "")
            meta = r.get("metadata", {})
            ts = meta.get("timestamp", 0)
            time_str = time.strftime("%m-%d %H:%M", time.localtime(ts)) if ts else ""
            mtype = meta.get("type", "general")
            lines.append(f"  [{i}] [{mtype}] {time_str}")
            lines.append(f"      {content[:300]}")
        return "\n".join(lines)
    except Exception as e:
        return f"[记忆搜索错误] {e}"


@tool(category="memory", timeout=15)
def memory_store(content: str, mem_type: str = "note") -> str:
    """主动存储一条记忆到长期记忆系统。

    用于记住：用户偏好、项目关键决策、重要配置、需要跨会话保留的信息。

    Args:
        content: 要记忆的内容（建议简洁完整，50-300 字）
        mem_type: 记忆类型（note=笔记 | preference=偏好 | decision=决策 | fact=事实）
    """
    if not content or len(content.strip()) < 5:
        return "[错误] 记忆内容太短（至少 5 个字符）"

    type_map = {"note": "笔记", "preference": "偏好", "decision": "决策", "fact": "事实"}
    cn_type = type_map.get(mem_type, mem_type)

    try:
        from agent.memory import get_semantic_memory
        mem = get_semantic_memory()
        if not mem:
            return "[记忆] 语义记忆未启用（ChromaDB 不可用）"
        ok = mem.store(content.strip(), {"type": mem_type})
        if ok:
            return f"[完成] 已存储 {cn_type} 记忆 ({len(content.strip())} 字符)"
        return "[错误] 记忆存储失败"
    except Exception as e:
        return f"[记忆存储错误] {e}"


@tool(category="memory", timeout=15, is_readonly=True, is_concurrency_safe=True)
def memory_stats() -> str:
    """查看记忆系统状态：总记忆数、各类型分布等。"""
    try:
        from agent.memory import get_semantic_memory, ShortTermMemory
        mem = get_semantic_memory()
        stm = ShortTermMemory()

        lines = ["## 记忆系统状态"]

        # 语义记忆
        if mem:
            try:
                total = mem.count()
                lines.append(f"语义记忆: {total} 条")
            except Exception:
                lines.append("语义记忆: 查询失败")
        else:
            lines.append("语义记忆: 未启用")

        # 短期记忆
        stm_facts = len(stm.facts)
        stm_notes = len(stm.notes)
        lines.append(f"短期记忆: {stm_facts} 个事实, {stm_notes} 条笔记")

        return "\n".join(lines)
    except Exception as e:
        return f"[错误] {e}"
