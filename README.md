<div align="center">
  <h1>ClaudeZ</h1>
  <p><strong>Model (DeepSeek) + Harness (Go Native) = Agent</strong></p>
  <p>专业为 DeepSeek 打造的自主 AI 智能体框架</p>
  <p>
    <img src="https://img.shields.io/badge/version-2.1-7C3AED" alt="Version 2.1">
    <img src="https://img.shields.io/badge/DeepSeek-Optimized-4D6BFE" alt="DeepSeek Optimized">
    <img src="https://img.shields.io/badge/Go_Harness-Native-00ADD8" alt="Go Harness">
    <img src="https://img.shields.io/badge/Python-3.11%2B-3776AB" alt="Python 3.11+">
    <img src="https://img.shields.io/badge/license-MIT-10B981" alt="MIT License">
  </p>
</div>

---

## 🎯 设计哲学

> **每次 LLM 调用前，系统提示词都是"状态快照"**

ClaudeZ 的核心理念是将**大语言模型**与**原生壳层**深度结合，创造自主 AI 智能体：

```
      DeepSeek                         Go Harness
     ┌────────────┐                  ┌─────────────────┐
     │ 动态提示词   │    IPC/JSON-RPC  │   进程管理       │
     │ 引擎        │◄──────────────►│   TUI 渲染       │
     │ 工具系统     │     stdin/     │   自动更新       │
     │ 记忆系统     │     stdout     │   看门狗         │
     │ Plugin 生态  │                  │   平台分发       │
     └──────┬─────┘                  └────────┬────────┘
            │                                 │
            └───────── Model + Harness ────────┘
                           │
                           ▼
                    ┌──────────────┐
                    │   自主 Agent   │
                    │ workflow     │
                    │ tool_exec    │
                    │ memory       │
                    └──────────────┘
```

**传统 Agent 的系统提示词是"一次性配置"——启动时写好就不再变化。**
**ClaudeZ 的核心创新是：每次调用 LLM 前，根据当前上下文动态构建完整的系统提示词。**

这意味着：
- 🛠️ **工具列表实时注入** — 新增工具立即可用
- 🔄 **工作流模式可切换** — chat / research / coding / debug / agent
- 🧠 **自适应调整** — 根据错误率、轮次、重复调用动态调整行为约束
- 💾 **记忆注入** — 语义记忆 + 短期记忆 + 项目上下文
- 🔒 **约束条件动态生成** — 权限、超时、语言、禁止操作

---

## ✨ 核心特性

### 为 DeepSeek 而生

ClaudeZ **默认配置即针对 DeepSeek 深度优化**：

| 特性 | 说明 |
|------|------|
| 默认 Provider | `deepseek` / `deepseek-chat` |
| Thinking 控制 | 可开关 DeepSeek reasoning 模式 |
| Token 管理 | 8192 max_tokens + 64K 上下文窗口 |
| 消息序列修复 | 三层自动修复确保 API 兼容性 |
| 指数退避重试 | 专为 DeepSeek 限流策略优化 |

### Model + Harness = Agent

| 层 | 技术 | 职责 |
|----|------|------|
| **Model** | DeepSeek API (Python) | 动态提示词引擎、工具系统、记忆、插件 |
| **Harness** | Go Native (Bubble Tea) | 进程管理、TUI 渲染、自动更新、IPC |
| **Agent** | Python Core | Agent 主循环、工作流、权限控制 |

### 三大运行模式

```
┌─────────────────────────────────────────────────────────┐
│                   ClaudeZ v2.1                           │
├─────────────┬───────────────────┬───────────────────────┤
│  CLI Mode   │   Web GUI Mode    │   Harness TUI Mode   │
│             │                   │                       │
│  python     │  Browser + SSE    │  Go Binary + TUI      │
│  main.py    │  FastAPI Backend  │  Bubble Tea           │
│  "question" │  Real-time Stream │  Process Watchdog     │
├─────────────┴───────────────────┴───────────────────────┤
│              Model: DeepSeek + 工具系统 + 记忆            │
└─────────────────────────────────────────────────────────┘
```

---

## 🚀 快速开始

```bash
# 1. 安装依赖
pip install anthropic openai chromadb psutil fastapi uvicorn sse_starlette

# 2. 配置 DeepSeek API Key
# 编辑 config.json 或设置环境变量
set CLAUDEZ_API_KEY=sk-your-key-here

# 3. CLI 单次执行
python main.py "用 Python 写一个斐波那契数列"

# 4. 交互模式
python main.py --interactive

# 5. Web GUI 模式（随机端口，自动开浏览器）
python main.py --web
python main.py --web --port 8080

# 6. 工作流模式
python main.py -w coding "写一个 REST API"
python main.py -w research "搜索最新的 AI 框架"
python main.py -w debug "排查这个 bug"

# 7. 原生 Harness 模式（需要 Go 编译）
python main.py --harness-mode
```

---

## 📦 技术栈全景

| 层级 | 技术 | 版本 |
|------|------|------|
| **LLM Provider** | DeepSeek / OpenAI / Anthropic | v2.1 |
| **动态提示词引擎** | Python (自研) | — |
| **工具系统** | Pydantic Schema + @tool 装饰器 | — |
| **向量记忆** | ChromaDB | latest |
| **Web GUI** | FastAPI + SSE + Canvas | — |
| **Go Harness** | Bubble Tea + Lipgloss | v1.1.0 |
| **IPC 协议** | JSON-RPC 2.0 over stdin/stdout | — |
| **进程管理** | Watchdog (自研) | — |
| **自动更新** | GitHub Releases API | — |
| **插件系统** | PluginManager + manifest.json | — |
| **主机工具探测** | 20+ 开发工具自动挂载 | — |
| **分发** | npm / pip 双渠道 | — |

---

## 📂 项目结构

```
ClaudeZ/
├── main.py                    # ★ 入口（CLI / Web / Harness）
├── config.json                # 配置文件（默认 DeepSeek）
├── DEEPSEEK_TECH_STACK.md     # DeepSeek 技术栈文档
├── UX_AUDIT.md                # 全球用户体验审计报告
│
├── agent/                     # ★ Agent 核心（Python）
│   ├── core.py                # Agent 主循环（核心）
│   ├── prompt.py              # ★ 动态提示词引擎
│   ├── cli.py                 # CLI 界面
│   ├── session.py             # 会话管理 + 持久化
│   ├── types.py               # ContentBlock 类型系统
│   ├── debug_stream.py        # 结构化调试日志
│   ├── permissions.py         # 权限控制 + 审计日志
│   ├── workflow.py            # 工作流引擎
│   ├── webhook.py             # Webhook 远程触发
│   ├── plugin_manager.py      # 插件管理系统
│   │
│   ├── providers/             # LLM 提供商抽象层
│   │   └── base.py            # ★ DeepSeek / OpenAI / Anthropic
│   │
│   ├── tools/                 # ★ 工具系统（10+ 内置工具）
│   │   ├── registry.py        # 工具注册表
│   │   ├── schema.py          # Pydantic Schema 校验
│   │   ├── builtin.py         # read/write/bash/edit/glob/grep...
│   │   ├── subagent.py        # 子 Agent 工具
│   │   ├── artifact.py        # 制品发布工具
│   │   ├── workflow_tool.py   # 工作流管理工具
│   │   └── webhook_tool.py    # Webhook 管理工具
│   │
│   ├── memory/                # 记忆系统
│   │   ├── short_term.py      # 短期记忆（会话内事实）
│   │   └── semantic.py        # 语义记忆（ChromaDB 向量存储）
│   │
│   ├── plugins/               # 插件系统
│   │   └── host_tools/        # 主机工具链探测（20+ 工具）
│   │
│   └── web_gui/               # ★ Web GUI
│       ├── server.py          # FastAPI + SSE + REST API
│       └── static/
│           ├── index.html     # 深色主题前端（粒子背景）
│           └── app.js         # SSE 流式渲染 / 工具面板 / 调试
│
├── harness/                   # ★ Go 原生壳层
│   ├── main.go                # 入口（TUI / 无头模式）
│   ├── go.mod                 # Go 1.22 + Bubble Tea
│   ├── runner.py              # Python 侧 IPC 桥接
│   ├── ipc/protocol.py        # JSON-RPC 2.0 协议
│   ├── tui/                   # Bubble Tea TUI 渲染
│   │   ├── render.go          # 分屏聊天界面
│   │   ├── spinner.go         # 加载动画
│   │   └── theme.go           # 颜色主题
│   ├── lifecycle/watchdog.go  # 进程看门狗（自动重启）
│   └── updater/check.go       # 自动更新检查
│
├── core/tool_schema.py        # 向后兼容 SDK 层
├── scripts/                   # 构建脚本
│   ├── build.sh               # 跨平台构建
│   └── build.bat
├── tests/                     # 全面测试套件（9 项）
└── @claudez/                  # npm 平台分发
    ├── cli/                   # CLI 包装
    ├── harness-win32-x64/     # Windows 原生二进制
    ├── harness-darwin-arm64/  # macOS Apple Silicon
    └── harness-linux-x64/     # Linux x64
```

---

## 🔧 配置文档

默认配置已针对 DeepSeek 优化：

```json
{
    "provider": "deepseek",
    "model": "deepseek-chat",
    "base_url": "https://api.deepseek.com/v1",
    "max_tokens": 8192,
    "temperature": 0.0,
    "workflow_mode": "agent",
    "disable_thinking": true,
    "enable_memory": true,
    "max_consecutive_errors": 5
}
```

> **安全提示**: 建议使用环境变量 `CLAUDEZ_API_KEY` 替代 `config.json` 明文存储 API Key。

---

## 🌐 全球用户体验评级

| 维度 | CLI | Web GUI | TUI | 配置 | 工具 |
|------|-----|---------|-----|------|------|
| 功能性 | 8.0 | 8.5 | 7.5 | 8.0 | 9.0 |
| 易用性 | 7.5 | 8.0 | 6.5 | 7.0 | 8.5 |
| **加权总分** | ⭐⭐⭐⭐☆ 4/5 | | | | |

> 详细审计报告见 [UX_AUDIT.md](UX_AUDIT.md)

---

## 📚 文档索引

| 文档 | 说明 |
|------|------|
| [DEEPSEEK_TECH_STACK.md](DEEPSEEK_TECH_STACK.md) | DeepSeek 技术栈深度解析 |
| [UX_AUDIT.md](UX_AUDIT.md) | 全球用户体验审计报告 |
| [API.md](API.md) | 完整 API 参考 |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 系统架构指南 |
| [TECHNICAL_WHITEPAPER.md](TECHNICAL_WHITEPAPER.md) | 技术白皮书（v2.1） |

---

## 🧪 测试

```bash
python tests/run_all.py
```

包含 9 项测试，覆盖导入、配置、工具注册表、提示词构建、会话管理、Provider 层、IPC 协议、工作流引擎、记忆系统。

---

## 🏗️ 构建原生 Harness

```bash
# Windows
scripts\build.bat

# Linux / macOS
./scripts/build.sh
```

构建产物：`@claudez/harness-{platform}/bin/claudez`

---

## 🤝 对比优势

| 特性 | ClaudeZ v2.1 | Claude Code | Cursor | Windsurf |
|------|-------------|-------------|--------|----------|
| **动态提示词** | ✅ **独家** | ❌ | ❌ | ❌ |
| **DeepSeek 原生** | ✅ **默认** | ❌ | ⚠️ 第三方 | ⚠️ 第三方 |
| **Go 原生壳层** | ✅ **独有** | ❌ Node.js | ❌ Electron | ❌ Electron |
| **主机工具探测** | ✅ **独有** | ❌ | ❌ | ❌ |
| **插件系统** | ✅ | ❌ | ✅ | ✅ |
| **多 Provider** | ✅ 3家 | ❌ 1家 | ✅ 多家 | ✅ 多家 |
| **Web GUI** | ✅ | ❌ | ❌ | ❌ |
| **语义记忆** | ✅ ChromaDB | ❌ | ❌ | ❌ |
| **开源** | ✅ MIT | ❌ | ❌ | ❌ |

---

## 📄 许可

MIT License — 自由使用、修改、分发。

---

<div align="center">
  <p><strong>Model (DeepSeek) + Harness (Go Native) = Agent</strong></p>
  <p>ClaudeZ v2.1 | 2026-07-18</p>
</div>
