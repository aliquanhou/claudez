"""debug_stream — 结构化调试日志系统。

在每个关键节点记录结构化事件，支持一键导出 JSON/Markdown 分析。

记录的事件类型：
  - message_flow: 每轮 LLM 调用的消息快照
  - tool_chain: 工具调用链路（顺序/耗时/结果）
  - agent_decision: Agent 决策过程（思考/下一步/置信度）
  - context: 上下文窗口状态（token 用量/压缩）
  - api_call: LLM API 请求/响应日志
  - error: 错误记录
"""

from __future__ import annotations

import json
import time
import traceback
from datetime import datetime
from typing import Any


class DebugCollector:
    """结构化调试数据收集器。"""

    def __init__(self, session_id: str = "", model: str = "", version: str = "2.0"):
        self.session_id = session_id
        self.start_time = time.time()
        self.data: dict[str, Any] = {
            "session": {
                "id": session_id,
                "start_time": datetime.now().isoformat(),
                "model": model,
                "agent_version": version,
            },
            "tool_calls": [],
            "decisions": [],
            "message_flow": [],
            "api_calls": [],
            "context_snapshots": [],
            "errors": [],
        }

    # ── 日志方法 ──

    def log_tool_call(self, name: str, params: dict, result: str,
                      duration_ms: float, success: bool = True):
        """记录工具调用。"""
        self.data["tool_calls"].append({
            "timestamp": datetime.now().isoformat(),
            "name": name,
            "params": params,
            "result_preview": str(result)[:200],
            "result_length": len(str(result)),
            "duration_ms": round(duration_ms, 1),
            "success": success,
            "order": len(self.data["tool_calls"]) + 1,
        })

    def log_decision(self, thought: str = "", action: str = "",
                     confidence: float = 0.0, phase: str = "",
                     alternatives: list | None = None):
        """记录 Agent 决策。"""
        self.data["decisions"].append({
            "timestamp": datetime.now().isoformat(),
            "round": len(self.data["decisions"]) + 1,
            "phase": phase,
            "thought": thought,
            "action": action,
            "confidence": round(confidence, 2),
            "alternatives": alternatives or [],
        })

    def log_message_flow(self, messages: list[dict], round_num: int,
                         role_filter: list[str] | None = None):
        """记录消息流快照。"""
        filtered = messages
        if role_filter:
            filtered = [m for m in messages if m.get("role") in role_filter]

        snapshot = []
        for m in filtered[-8:]:  # 最近 8 条
            entry: dict = {"role": m.get("role")}
            content = m.get("content", "")
            if content:
                entry["content_preview"] = str(content)[:100]
                entry["char_length"] = len(str(content))
            if m.get("tool_calls"):
                entry["tool_calls"] = [
                    {
                        "id": tc.get("id", "")[:16],
                        "name": tc.get("function", {}).get("name", tc.get("name", "")),
                        "args_preview": str(
                            tc.get("function", {}).get("arguments", tc.get("args", {}))
                        )[:80],
                    }
                    for tc in m["tool_calls"]
                ]
            if m.get("tool_call_id"):
                entry["tool_call_id"] = m["tool_call_id"][:16]
            snapshot.append(entry)

        self.data["message_flow"].append({
            "timestamp": datetime.now().isoformat(),
            "round": round_num,
            "total_count": len(messages),
            "snapshot": snapshot,
        })

    def log_api_call(self, model: str, stop_reason: str,
                     prompt_tokens: int = 0, completion_tokens: int = 0,
                     duration_ms: float = 0.0, tool_count: int = 0,
                     error: str = ""):
        """记录 API 调用。"""
        self.data["api_calls"].append({
            "timestamp": datetime.now().isoformat(),
            "model": model,
            "stop_reason": stop_reason,
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
            "duration_ms": round(duration_ms, 1),
            "tool_count": tool_count,
            "error": error,
            "order": len(self.data["api_calls"]) + 1,
        })

    def log_context(self, total_messages: int, max_messages: int,
                    tokens_used: int = 0, max_tokens: int = 0,
                    compressed: bool = False):
        """记录上下文窗口状态。"""
        self.data["context_snapshots"].append({
            "timestamp": datetime.now().isoformat(),
            "messages": total_messages,
            "max_messages": max_messages,
            "usage_percent": round(
                (total_messages / max_messages) * 100 if max_messages else 0, 1
            ),
            "tokens_used": tokens_used,
            "max_tokens": max_tokens,
            "compressed": compressed,
        })

    def log_error(self, source: str, message: str, tb: str = ""):
        """记录错误。"""
        self.data["errors"].append({
            "timestamp": datetime.now().isoformat(),
            "source": source,
            "message": message,
            "traceback": tb[:500] if tb else "",
        })

    # ── 导出 ──

    def export_json(self) -> str:
        """导出为 JSON。"""
        self.data["session"]["end_time"] = datetime.now().isoformat()
        self.data["session"]["total_duration_ms"] = round(
            (time.time() - self.start_time) * 1000, 1
        )
        # 汇总统计
        self.data["summary"] = self._summary()
        return json.dumps(self.data, indent=2, ensure_ascii=False)

    def export_markdown(self) -> str:
        """导出为 Markdown 报告。"""
        self.export_json()  # 刷新 end_time
        d = self.data
        s = d["session"]

        md = f"# 🐛 ClaudeZ 调试报告\n\n"
        md += f"**会话**: `{s['id']}`  **模型**: {s['model']}  **版本**: {s['agent_version']}\n\n"
        md += f"**开始**: {s['start_time']}  **结束**: {s.get('end_time', '')}  "
        md += f"**总耗时**: {s.get('total_duration_ms', 0)}ms\n\n"

        # 工具统计
        tc = d["tool_calls"]
        md += "---\n## 🔧 工具调用\n\n"
        md += f"总次数: {len(tc)}\n\n"
        for t in tc:
            icon = "✅" if t["success"] else "❌"
            md += f"| {icon} {t['name']} | {t['duration_ms']}ms | {t['result_length']} chars |\n"
            md += f"| 参数: `{json.dumps(t['params'], ensure_ascii=False)[:100]}` |\n\n"

        # 决策
        dec = d["decisions"]
        md += "---\n## 🧠 决策过程\n\n"
        for de in dec:
            md += f"### 第 {de['round']} 轮 ({de['phase']})\n"
            md += f"- **思考**: {de['thought']}\n"
            md += f"- **行动**: {de['action']}\n"
            md += f"- **置信度**: {de['confidence']}\n\n"

        # API 调用
        api = d["api_calls"]
        md += "---\n## 🌐 API 调用\n\n"
        for a in api:
            md += f"| #{a['order']} | {a['model']} | {a['stop_reason']} | "
            md += f"{a['usage']['total_tokens']}tokens | {a['duration_ms']}ms |\n"
            if a["error"]:
                md += f"  ❌ {a['error']}\n"
            md += "\n"

        # 错误
        err = d["errors"]
        if err:
            md += "---\n## ❌ 错误\n\n"
            for e in err:
                md += f"**{e['source']}**: {e['message']}\n"
                if e["traceback"]:
                    md += f"```\n{e['traceback']}\n```\n"

        # 消息流
        mf = d["message_flow"]
        md += "---\n## 💬 消息流快照\n\n"
        for m in mf[-3:]:  # 最近 3 条
            md += f"### 第 {m['round']} 轮 (共 {m['total_count']} 条)\n"
            md += "```json\n" + json.dumps(m["snapshot"], indent=2, ensure_ascii=False) + "\n```\n\n"

        return md

    def _summary(self) -> dict:
        return {
            "total_tool_calls": len(self.data["tool_calls"]),
            "total_api_calls": len(self.data["api_calls"]),
            "total_errors": len(self.data["errors"]),
            "total_decisions": len(self.data["decisions"]),
            "successful_tools": sum(1 for t in self.data["tool_calls"] if t["success"]),
            "failed_tools": sum(1 for t in self.data["tool_calls"] if not t["success"]),
            "total_tool_duration_ms": round(
                sum(t["duration_ms"] for t in self.data["tool_calls"]), 1
            ),
            "total_api_duration_ms": round(
                sum(a["duration_ms"] for a in self.data["api_calls"]), 1
            ),
        }
