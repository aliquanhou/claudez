# ClaudeZ — 动态提示词驱动的自主 AI 智能体

**ClaudeZ** 是一个从零构建的、生产级 AI Agent 框架。它的核心创新是**动态提示词引擎**——每次 LLM 调用前根据当前上下文实时构建系统提示词，而非使用静态提示词。

## 设计哲学

> **每次 LLM 调用前，系统提示词都是"状态快照"。**

传统 Agent 的系统提示词是"一次性配置"——启动时写好就不再变化。
ClaudeZ 的核心创新是：**每次调用 LLM 前，根据当前上下文动态构建完整的系统提示词**。

这意味着：
- 工具列表实时注入（新增工具立即可用）
- 工作流模式可切换（chat / research / coding / debug / agent）
- 自适应调整（根据错误率、轮次、重复调用动态调整行为约束）
- 记忆注入（语义记忆 + 短期记忆 + 项目上下文）
- 约束条件动态生成（权限、超时、语言、禁止操作）

## 核心架构

```
用户输入
    │
    ▼
┌────────────────────────────────────────────────┐
│                Agent 主循环 (core.py)            │
│  while _running:                                 │
│    1. 构建动态系统提示词                          │
│    2. 调用 LLM (带重试 + 流式)                    │
│    3. 解析响应（文本 / tool_calls）               │
│    4. 并行执行工具                                │
│    5. 写入会话消息                                │
│    6. 重复直到完成                                │
└──────────────────┬─────────────────────────────┘
           │
           ▼
┌────────────────────────────────────────────────┐
│           Provider 适配层 (providers/)           │
│  AnthropicProvider / OpenAIProvider              │
│  ─ 统一接口抽象                                   │
│  ─ 指数退避重试                                   │
│  ─ 流式 streaming（text_delta + tool_calls）     │
│  ─ DeepSeek thinking 模式控制                    │
│  ─ 自动消息序列修复                               │
└──────────────────┬─────────────────────────────┘
           │
           ▼
┌────────────────────────────────────────────────┐
│             工具系统 (tools/)                    │
│  @tool 装饰器注册                                │
│  Pydantic Schema 校验                            │
│  readonly / concurrency_safe 标记                │
│  结果截断 (6000 chars)                           │
│  流式输出回调 (bash 逐行推送)                     │
│  edit diff 预览                                 │
└──────────────────┬─────────────────────────────┘
           │
           ▼
┌────────────────────────────────────────────────┐
│        会话与记忆管理 (session.py + memory/)     │
│  Session: 消息历史 + 状态追踪                    │
│  ShortTermMemory: 会话内事实                      │
│  SemanticMemory: ChromaDB 向量存储               │
│  磁盘持久化 (JSON)                               │
└──────────────────┬─────────────────────────────┘
           │
           ▼
┌────────────────────────────────────────────────┐
│           Web GUI (web_gui/)                    │
│  FastAPI + SSE + REST API                       │
│  Claude Code 风格 UI                            │
│  工具实时输出流 (bash stdout)                    │
│  调试日志面板 (一键导出 JSON/Markdown)           │
└────────────────────────────────────────────────┘
```

## 快速开始

```bash
# 安装依赖
pip install anthropic openai chromadb psutil fastapi uvicorn sse_starlette

# CLI 模式
python main.py "你的问题"

# 交互模式
python main.py --interactive

# Web GUI 模式（随机端口，自动开浏览器）
python main.py --web

# 指定端口
python main.py --web --port 8080

# 工作流模式
python main.py -w coding "写一个 Python 函数"
python main.py -w research "搜索最新的 AI 新闻"
```

## 项目结构

```
ClaudeZ/
├── main.py                    # 入口（CLI / Web / Harness）
├── config.json                # 配置文件
│
├── agent/                     # ★ Agent 核心
│   ├── __init__.py
│   ├── __main__.py            # python -m agent
│   ├── cli.py                 # CLI 界面
│   ├── core.py                # Agent 主循环（核心）
│   ├── prompt.py              # ★ 动态提示词引擎
│   ├── session.py             # 会话管理 + 持久化
│   ├── types.py               # ContentBlock 类型系统
│   ├── debug_stream.py        # 结构化调试日志
│   ├── permissions.py         # 权限控制 + 审计日志
│   ├── workflow.py            # 工作流引擎
│   ├── webhook.py             # Webhook 远程触发
│   │
│   ├── providers/             # LLM 提供商抽象层
│   │   ├── __init__.py
│   │   └── base.py            # Anthropic + OpenAI/DeepSeek
│   │
│   ├── tools/                 # ★ 工具系统
│   │   ├── __init__.py
│   │   ├── registry.py        # 工具注册表
│   │   ├── schema.py          # Pydantic Schema
│   │   ├── builtin.py         # 内置工具（read/write/bash/edit...）
│   │   ├── subagent.py        # 子 Agent 工具
│   │   ├── artifact.py        # 制品发布工具
│   │   ├── workflow_tool.py   # 工作流管理工具
│   │   └── webhook_tool.py    # Webhook 管理工具
│   │
│   ├── memory/                # 记忆系统
│   │   ├── __init__.py
│   │   ├── short_term.py      # 短期记忆
│   │   └── semantic.py        # 语义记忆（ChromaDB）
│   │
│   └── web_gui/               # ★ Web GUI
│       ├── __init__.py
│       ├── server.py          # FastAPI 后端
│       └── static/
│           ├── index.html     # Claude Code 风格前端
│           └── app.js         # 粒子渲染/SSE/面板
│
├── harness/                   # Go 原生壳层（可选增强）
│   ├── main.go                # Go 入口
│   ├── go.mod
│   ├── tui/                   # bubbletea TUI
│   ├── ipc/                   # IPC 通信
│   ├── lifecycle/             # 进程看门狗
│   └── updater/               # 自动更新
│
├── core/                      # 核心工具
│   └── tool_schema.py         # SDK 工具类型（向后兼容）
│
├── scripts/                   # 构建脚本
│   ├── build.sh
│   └── build.bat
│
├── tests/                     # 测试
│   └── run_all.py             # 全面自检脚本
│
└── @claudez/                  # npm 包装（平台分发）
    ├── cli/                   # CLI 包装
    ├── harness-win32-x64/
    ├── harness-darwin-arm64/
    └── harness-linux-x64/
```
