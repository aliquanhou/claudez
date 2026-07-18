# ClaudeZ Technical Whitepaper

> Version 2.2 | 2026-07-19
> 
> An open-source autonomous AI agent framework, purpose-built for DeepSeek
> 
> **Model + Harness = Agent** — Every LLM call gets a fresh, dynamic system prompt.

---

## 摘要

ClaudeZ 是一个从零构建的、生产级 AI Agent 框架。它提出了 **"动态提示词引擎"** 的新范式：系统提示词不是一次性配置，而是每次 LLM 决策前的"状态快照"。配合完善的工具系统、会话管理、流式输出架构和 Web GUI，ClaudeZ 提供了一个完整的 AI Agent 基础设施。

---

## 1. 核心创新

### 1.1 动态提示词引擎 (`agent/prompt.py`)

```python
# 每次 LLM 调用前动态构建
system_prompt = prompt_builder.build(PromptContext(
    tools=get_all_tools(),          # 实时工具列表
    workflow_mode="agent",          # 工作流模式
    constraints={...},              # 动态约束
    memories=[...],                 # 语义记忆
    session_state={...},            # 自适应状态
))
```

传统 Agent 使用静态系统提示词。ClaudeZ 每次调用 LLM 前重建系统提示词，注入：
- **工具列表**：当前实际注册的工具
- **工作流模式**：chat / research / coding / debug / agent
- **自适应调整**：根据错误率、轮次、重复调用动态调整行为约束
- **记忆注入**：语义记忆 + 短期记忆 + 项目上下文
- **约束条件**：权限、超时、语言、禁止操作

### 1.2 ContentBlock 类型系统 (`agent/types.py`)

参考 Claude Code 的消息类型设计：

| 类型 | 说明 |
|------|------|
| `TextBlock` | 普通文本 |
| `ThinkingBlock` | 思考块 |
| `ToolUseBlock` | 工具调用请求 |
| `ToolResultBlock` | 工具执行结果 |

每条 `Message` 包含多个 `ContentBlock`，允许 text 和 tool_use 交错。

### 1.3 结构化调试日志 (`agent/debug_stream.py`)

内置完整的调试数据收集器：

| 事件类型 | 内容 |
|---------|------|
| `message_flow` | 每轮 LLM 调用的消息快照 |
| `tool_chain` | 工具调用链路（顺序/耗时/结果） |
| `agent_decision` | Agent 决策过程 |
| `api_call` | LLM API 请求/响应日志 |
| `context` | 上下文窗口状态 |
| `error` | 错误记录 |

支持一键导出 JSON / Markdown 格式。

---

## 2. 消息协议

### 2.1 SSE 事件体系

```
事件: text_delta        → 实时文本块
事件: thinking_delta    → 思考块
事件: tool_use_start    → 工具调用开始
事件: tool_result       → 工具执行结果
事件: tool_output       → 工具实时输出（bash 逐行）
事件: session_start     → 会话开始
事件: session_end       → 会话结束
事件: error             → 错误
```

### 2.2 消息格式（DeepSeek/OpenAI 兼容）

```
assistant(content="文本", tool_calls=[
    {id, type="function", function={name, arguments}}
])
  ↓
tool(tool_call_id=id, content="结果")
tool(tool_call_id=id, content="结果")
  ↓
assistant(content="完成")
```

### 2.3 消息序列自动修复

在 API 调用前执行三层防护：

1. **`_clean_session()`** — 每次 `run()` 开始前清理孤立消息
2. **`_auto_fix_messages()`** — 自动修复：移除孤立 tool_calls、移动插队 user 消息
3. **`_validate_and_strip()`** — 最终防线：检测到任何孤立消息回退到安全状态

---

## 3. 工具系统

### 3.1 注册模式

```python
@tool(category="file", timeout=30, is_readonly=True, is_concurrency_safe=True)
def read(file_path: str, head: int = 0, tail: int = 0) -> str:
    """读取文件内容。"""
    ...
```

### 3.2 工具属性

| 属性 | 说明 |
|------|------|
| `is_readonly` | 只读标记（用于权限控制） |
| `is_concurrency_safe` | 可并发执行 |
| `require_confirmation` | 需要用户确认 |
| `timeout` | 超时秒数 |
| `result_truncate` | 结果截断长度（默认6000） |

### 3.3 内置工具（14个）

| 工具 | 分类 | 只读 | 并发安全 |
|------|------|------|---------|
| `read` | file | ✅ | ✅ |
| `write` | file | ❌ | ❌ |
| `edit` | file | ❌ | ❌ |
| `glob` | file | ✅ | ✅ |
| `grep` | file | ✅ | ✅ |
| `bash` | shell | ❌ | ❌ |
| `web` | web | ✅ | ✅ |
| `web_search` | web | ✅ | ✅ |
| `process` | system | ✅ | ✅ |
| `monitor` | system | ✅ | ✅ |
| `subagent` | agent | ❌ | ❌ |
| `artifact` | artifact | ❌ | ❌ |
| `workflow` | workflow | ❌ | ❌ |
| `webhook` | webhook | ❌ | ❌ |

### 3.4 流式输出

Bash 工具使用 `subprocess.Popen` + 逐行读取，通过 `threading.local` 回调实时推送输出行到 UI。

Edit 工具在替换前推送 diff 预览（文件路径、行号、旧/新行）。

---

## 4. Provider 适配层

### 4.1 统一接口

```python
class LLMProvider(ABC):
    def chat(system_prompt, messages, tools) -> LLMResponse
    def chat_with_retry(system_prompt, messages, tools) -> LLMResponse
```

### 4.2 错误分类与重试

```
                    ┌──────────────┐
                    │  API 错误     │
                    └──────┬───────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        可重试           上下文超长      不可重试
     (429/500/502/503)  (压缩后重试)   (401/400)
        指数退避             │            │
        带抖动              ▼            ▼
                       压缩成功?      返回错误
                         │
                         ▼
                       重试
```

### 4.3 DeepSeek 特殊适配

- **thinking 模式关闭**：通过 `extra_body={"thinking": {"type": "disabled"}}` 节省 token
- **tool_choice**: 默认 `"auto"` 推动模型调用工具
- **流式工具调用**：`delta.tool_calls` 逐块累积 JSON 参数

---

## 5. Web GUI

### 5.1 架构

```
FastAPI 后台
  ├─ SSE /api/stream → 实时事件推送
  ├─ POST /api/send  → 消息发送
  ├─ POST /api/stop  → 终止
  ├─ GET /api/debug  → 调试日志导出
  └─ GET /{path}     → 静态文件

前端 (Vanilla JS)
  ├─ Canvas 粒子背景
  ├─ SSE EventSource 接收
  ├─ Markdown 渲染
  ├─ 内联 Diff 显示
  ├─ 工具状态面板
  ├─ 事件日志面板
  └─ 调试报告面板
```

### 5.2 事件流

```
WebStreamHandler (server.py)
  ├─ on_text()        → SSE "text_delta"
  ├─ on_thinking()    → SSE "thinking_delta"
  ├─ on_tool_start()  → SSE "tool_use_start"
  ├─ on_tool_result() → SSE "tool_result"
  ├─ on_tool_output() → SSE "tool_output"
  └─ on_error()       → SSE "error"
```

---

## 6. 工作流引擎 (`agent/workflow.py`)

- **序列化/反序列化**: JSON 格式存储到磁盘
- **检查点**: 自动保存每 N 步
- **恢复执行**: `WorkflowResumer` 从检查点恢复
- **进度追踪**: 每步 pending/running/completed/failed/skipped

---

## 7. 记忆系统

### 7.1 短期记忆 (`agent/memory/short_term.py`)
会话内事实存储，基于字典的键值对，支持标签检索。

### 7.2 语义记忆 (`agent/memory/semantic.py`)
基于 ChromaDB 的向量存储，通过语义相似度搜索相关记忆，自动注入提示词。

---

## 8. 权限与安全 (`agent/permissions.py`)

| 模式 | 行为 |
|------|------|
| `auto` | 自动批准所有操作 |
| `ask` | 询问用户确认修改操作 |
| `deny` | 拒绝所有操作 |
| `readonly` | 只允许只读操作 |

所有关键操作记录不可变审计日志（JSONL 文件）。

---

## 9. 测试覆盖

运行 `python tests/run_all.py` 执行 9 项测试：

| 模块 | 测试项 |
|------|--------|
| 模块导入 | 所有模块 import 成功 |
| 配置加载 | config.json 读取 |
| 工具注册表 | 14 个工具 + OpenAI/Anthropic 格式 |
| 动态提示词 | 5 种工作流模式 |
| 会话管理 | 序列化/反序列化/持久化 |
| Provider 层 | 工厂/重试/退避 |
| IPC 协议 | 消息序列化 |
| 工作流引擎 | 创建/执行/序列化/恢复 |
| 记忆系统 | 短期记忆读写 |

---

## 10. 性能指标

| 指标 | 值 |
|------|-----|
| 工具数量 | 14 个内置工具 |
| API 调用耗时 | ~1.5-5s/次（DeepSeek） |
| 工具执行耗时 | ~50ms-10s（取决于工具） |
| 上下文窗口 | 可配置（默认 50 条） |
| 最大工具调用次数 | 可配置（默认 50） |

---

## 参考文献

- [Claude Code 架构设计](https://github.com/6551Team/claude-code-design-guide/blob/main/part3/08-message-loop.md)
- [Agent SDK 流式输出文档](https://code.claude.com/docs/zh-CN/agent-sdk/streaming-output)
- [deepseek-harness](https://github.com/HenryZ838978/deepseek-harness) — DeepSeek V4 协议特性
