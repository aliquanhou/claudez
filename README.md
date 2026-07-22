<div align="center">

# ⚡ ForgeX

**AI Agent 框架 — 认知层 · 执行层 · 工具层 · Web UI**

*ForgeX v1.0 — From Cognition to Execution*

[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green)](LICENSE)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-teal)](https://fastapi.tiangolo.com/)

</div>

---

## 📖 概述

ForgeX 是一个**四层架构**的自主 AI Agent 框架：

```
认知层 (Cognition)    → 理解用户意图、规划任务步骤
执行层 (Execution)    → 拆解方案、并行执行工具、验证结果
工具层 (Tool System)  → 内置 12+ 工具 + 主机工具链自动探测
Web UI (Cockpit)      → 3 栏驾驶舱 + 实时 SSE 流式输出
```

从**认知**到**执行**形成完整闭环：Agent 先理解需求，再自动规划、执行、验证、反馈。

---

## ✨ 核心特性

| 特性 | 说明 |
|------|------|
| 🧠 **认知层** | 意图识别、任务管理、方案验证、执行验证、上下文编译（6 模块） |
| ⚡ **执行层** | 方案拆解、并行工具编排、路径安全校验、反馈闭环 |
| 🔧 **12+ 内置工具** | read/write/edit/bash/glob/grep/web_search/web_fetch/subagent 等 |
| 🔍 **Web 搜索 + 网页抓取** | DuckDuckGo 搜索 + BeautifulSoup 网页纯文本提取（闭环） |
| 🖥️ **主机工具链探测** | 自动检测 Python/Node/Java/Git/Docker 等 20 种工具，注入 Agent 感知 |
| 🎛️ **3 栏驾驶舱** | 左栏（文件树 + 工具 + LLM 配置）、主区（对话流 + Diff）、右栏（实时状态 + 日志） |
| 🔐 **权限管理** | Auto / Ask / Deny 三级 + 写操作确认机制 |
| 🌐 **多 Provider** | DeepSeek / OpenAI / Anthropic Claude，统一接口 + 智能重试 |
| 💾 **双层记忆** | 短期记忆（LRU 淘汰）+ 语义记忆（ChromaDB / SQLite） |
| 🐛 **调试系统** | 结构化日志 + 请求链路追踪（文件级） |

---

## 🚀 快速开始

### 安装

```bash
git clone https://github.com/aliquanhou/claudez.git
cd claudez

# 核心依赖
pip install fastapi uvicorn pydantic sse-starlette psutil requests beautifulsoup4

# LLM Provider SDK（选一）
pip install openai          # DeepSeek / OpenAI
pip install anthropic       # Anthropic Claude

# 可选增强
pip install chromadb         # 语义记忆向量存储
pip install duckduckgo_search # 网络搜索
```

### 配置

编辑 `config.json`：

```json
{
    "provider": "deepseek",
    "model": "deepseek-chat",
    "api_key": "your-api-key-here",
    "base_url": "https://api.deepseek.com/v1",
    "max_tokens": 8192,
    "temperature": 0.0,
    "api_timeout": 30,
    "disable_thinking": true,
    "enable_memory": true,
    "max_context_messages": 50
}
```

### 启动

```bash
# Web UI 模式（推荐）
python run_web.py
# → 自动扫描端口 (8080→8089)，自动打开浏览器

# CLI 模式
python agent/__main__.py
```

访问 `http://localhost:8080` 进入 ForgeX 驾驶舱。

---

## 🎮 Web UI 驾驶舱

```
┌──────────────┬───────────────────────────────┬──────────────┐
│  左栏 200px   │     主工作区（弹性）            │  右栏 260px   │
├──────────────┼───────────────────────────────┼──────────────┤
│ 📁 文件树     │  对话流（SSE 实时推送）         │ 🧠 认知面板   │
│ 🔧 工具列表   │  Plan Card（执行计划）         │ 🎯 任务面板   │
│ 🔧 主机工具链 │  Diff 视图（文件变更）          │ 📋 决策列表   │
│ ⚙️ LLM 配置   │  Tool Badge（工具调用状态）     │ 📝 日志流     │
│  模型/温度    │  输入框 + 发送 + 停止          │  SSE 连接状态 │
└──────────────┴───────────────────────────────┴──────────────┘
  状态栏: 连接状态 | 阶段 | Token | 耗时
```

### API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/send` | POST | 发送消息 `{"text":"你好"}` |
| `/api/stream` | GET | SSE 事件流（实时） |
| `/api/config` | GET | 获取当前 LLM 配置 |
| `/api/config/llm` | POST | 实时更新模型/温度/MaxTokens |
| `/api/stop` | POST | 中断 Agent 执行 |
| `/api/files` | GET | 文件树（深度 4） |
| `/api/tools` | GET | 已注册工具列表 |
| `/api/env/tools` | GET | 本机工具链探测结果 |
| `/api/status` | GET | Agent 实时状态 |

---

## 🏗️ 架构

```
claudez/
├── run_web.py                      # 入口（动态端口 + 自动开浏览器）
├── config.json                     # 配置文件
├── agent/
│   ├── core.py                     # Agent 核心循环
│   ├── prompt.py                   # 动态提示词引擎
│   ├── session.py                  # 会话管理
│   ├── _trace.py                   # 请求链路追踪
│   │
│   ├── cognition/                  # ★ 认知层 (v0.3.4)
│   │   ├── task_context.py         #   任务管理器
│   │   ├── workspace_scanner.py    #   工作区扫描→文件树
│   │   ├── intent_resonator.py     #   意图蒸馏
│   │   ├── plan_verifier.py        #   方案验证
│   │   ├── execution_verifier.py   #   执行验证
│   │   └── context_compiler.py     #   上下文编译→Prompt 注入
│   │
│   ├── execution/                  # ★ 执行层 (v0.4.0)
│   │   ├── plan_executor.py        #   方案拆解→执行步骤
│   │   ├── tool_orchestrator.py    #   并行编排
│   │   ├── path_validator.py       #   文件路径安全校验
│   │   └── feedback_loop.py        #   执行反馈闭环
│   │
│   ├── providers/                  # LLM 提供商
│   │   ├── base.py                 #   Anthropic / OpenAI / DeepSeek
│   │   └── __init__.py
│   │
│   ├── tools/                      # 工具系统
│   │   ├── registry.py             #   @tool 注册表
│   │   ├── builtin.py              #   read/write/bash/glob/grep/web_search...
│   │   ├── web_fetch.py            #   网页抓取 (requests+BS4)
│   │   ├── env_probe.py            #   主机工具链探测
│   │   ├── subagent.py             #   子 Agent
│   │   ├── artifact.py             #   制品发布
│   │   └── ...
│   │
│   ├── memory/                     # 记忆系统
│   │   ├── short_term.py           #   短期 (LRU)
│   │   └── semantic.py             #   语义 (ChromaDB/SQLite)
│   │
│   └── web/                        # Web UI
│       ├── server.py               #   FastAPI + SSE
│       └── static/index.html       #   3 栏驾驶舱
```

---

## 🔧 工具系统

### 内置工具

| 工具 | 类别 | 说明 |
|------|------|------|
| `read` | file | 读取文件（head/tail 截取） |
| `write` | file | 写入文件（自动创建目录） |
| `edit` | file | 替换文本（带 diff 预览） |
| `glob` | file | 通配符搜索 |
| `grep` | file | 正则搜索内容 |
| `bash` | shell | 执行命令（流式输出） |
| `web_search` | web | DuckDuckGo 搜索 |
| `web_fetch` | web | 网页纯文本抓取 |
| `web` | web | HTTP 请求 |
| `subagent` | agent | 子 Agent |
| `artifact` | artifact | 制品发布 |
| `process` | system | 进程管理 |
| `monitor` | system | 系统监控 |
| `workflow` | workflow | 工作流管理 |

### 主机工具链探测

Agent 自动感知本机可用工具（20 种引擎）：

```
Python 3.12.10   ✅   Node.js 24.15.0   ✅   Git 2.53   ✅
Java 17          ✅   curl 8.13         ✅   OpenSSH     ✅
Docker           ❌   npm                ❌   Go/Rust     ❌
```

探测结果 60 秒缓存，自动注入每轮对话的 system prompt。

---

## 🧠 认知 → 执行闭环

```
用户输入 "搜索 Python async 教程并保存到文件"
    │
    ▼
┌─ 认知层 ──────────────────────────────────┐
│  意图识别: EXPLORING → 执行意图           │
│  任务创建: {goal, phase, turn_count}      │
│  方案验证: 拆解为 3 步                    │
└───────────────────────────────────────────┘
    │
    ▼
┌─ 执行层 ──────────────────────────────────┐
│  PlanExecutor: 方案→ [搜索, 抓取, 写入]   │
│  ToolOrchestrator: 并行执行无依赖步骤     │
│  PathValidator: 校验写入路径安全性         │
│  FeedbackLoop: 验证结果 → 推进阶段        │
└───────────────────────────────────────────┘
    │
    ▼
        web_search("Python async/await")   ✅
        web_fetch("tutorial-url")          ✅
        write("async_demo.py", "content")  ✅
        bash("python async_demo.py")       ✅
    │
    ▼
  回复用户: 结果摘要
```

---

## 🗺️ 工作流模式

| 模式 | 场景 |
|------|------|
| `agent`（默认） | 听到需求 → 立即用工具执行 → 汇报 |
| `chat` | 直接回答，按需调用工具 |
| `research` | 拆解子问题 → 交叉验证 → 综合 |
| `coding` | 分析 → 设计 → 编码 → 测试 → 解释 |
| `debug` | 读错误 → 分析根因 → 修复 → 验证 |

---

## 📋 发布记录

| 版本 | 里程碑 |
|------|--------|
| v0.3.4 | 认知层：6 模块（意图/任务/验证/上下文） |
| v0.4.0 | 执行层：4 模块 + P0 UI（3 栏框架） |
| v0.4.1 | 动态端口 + 自动开浏览器 |
| v0.5.0 | LLM 配置实时生效 + 停止执行 |
| v0.5.1 | web_fetch 网页抓取工具 |
| v0.5.2 | 主机工具链探测 + web_search 修复 |
| **v1.0.0** | **完整四层架构正式发布** |

---

## 📄 License

MIT License © 2024-2026 aliquanhou

---

<div align="center">

**ForgeX — 从认知到执行，构建完整 AI Agent**

[GitHub](https://github.com/aliquanhou/claudez)

</div>
