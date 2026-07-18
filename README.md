<div align="center">
  <h1>ClaudeZ</h1>
  <p><strong>Model + Harness = Agent</strong></p>
  <p>An open-source autonomous AI agent framework, purpose-built for <strong>DeepSeek</strong></p>
  <p>
    <img src="https://img.shields.io/badge/version-2.2-7C3AED" alt="Version 2.2">
    <img src="https://img.shields.io/badge/DeepSeek-Optimized-4D6BFE" alt="DeepSeek Optimized">
    <img src="https://img.shields.io/badge/Go_Harness-Native-00ADD8" alt="Go Harness">
    <img src="https://img.shields.io/badge/Python-3.11%2B-3776AB" alt="Python 3.11+">
    <img src="https://img.shields.io/badge/license-MIT-10B981" alt="MIT License">
    <img src="https://img.shields.io/github/stars/aliquanhou/claudez?style=social" alt="GitHub Stars">
  </p>
  <p>
    <a href="#-quick-start">Quick Start</a> •
    <a href="#-features">Features</a> •
    <a href="#-architecture">Architecture</a> •
    <a href="#-configuration">Configuration</a> •
    <a href="#-roadmap">Roadmap</a>
  </p>
</div>

---

## 🎯 Philosophy

> **Every LLM call gets a fresh system prompt — a snapshot of current state.**

Traditional agents bake a static system prompt at startup. ClaudeZ's core innovation is **Dynamic Prompt Building**: before every LLM call, the system prompt is reconstructed from live context — available tools, workflow mode, semantic memories, session state, error rates, and active constraints.

This means:
- 🛠 **Tools are hot-pluggable** — register a new tool, and it's immediately available to the LLM
- 🔄 **Workflow modes are switchable** — chat / research / coding / debug / agent, each with its own prompt structure
- 🧠 **Memory is injected dynamically** — semantic search + short-term facts + project context, right into the system prompt
- 🔒 **Constraints adapt** — permission mode, timeouts, language, forbidden operations

---

## ✨ Features

### Purpose-Built for DeepSeek

| Feature | Description |
|---------|-------------|
| Native DeepSeek | Default provider is `deepseek` with `deepseek-chat` model |
| Thinking Control | Toggle DeepSeek reasoning mode on/off (`disable_thinking`) |
| Smart Retry | Exponential backoff with jitter, optimized for DeepSeek rate limits |
| Message Repair | Triple-layer auto-fix for message sequences (tool call → tool result pairing) |
| Token Management | 8K max_tokens, 64K context window support |

### Three Run Modes

```
┌─────────────────────────────────────────────────────────┐
│                    ClaudeZ v2.2                          │
├─────────────┬───────────────────┬───────────────────────┤
│  CLI Mode   │   Web GUI Mode    │   Harness TUI Mode   │
│             │                   │                       │
│  python     │  Browser + SSE    │  Go Binary + TUI      │
│  main.py    │  FastAPI Backend  │  Bubble Tea           │
│  "question" │  Real-time Stream │  Process Watchdog     │
├─────────────┴───────────────────┴───────────────────────┤
│              Core: DeepSeek + Tool System + Memory       │
└─────────────────────────────────────────────────────────┘
```

### Key Capabilities

| Capability | Details |
|------------|---------|
| **Dynamic Prompt Engine** | 8 configurable sections: role, tools, workflow, constraints, memory, project, adaptations, examples |
| **Tool System** | Pydantic schema, runtime validation, `@tool` decorator, 17+ built-in tools |
| **Parallel Execution** | Concurrency-safe tools (read/glob/grep/web) run in parallel via ThreadPoolExecutor |
| **Semantic Memory** | ChromaDB vector store cross-session memory |
| **10+ Built-in Tools** | read, write, edit, bash, glob, grep, web, web_search, process, monitor, subagent, artifact, workflow, webhook, memory_search, memory_store, memory_stats |
| **Plugin System** | Discover, load, unload host tool plugins dynamically |
| **Web GUI** | Glassmorphism dark theme, real-time SSE streaming, tool panel, event log, config page, memory browser |
| **Multi-Provider** | DeepSeek (default), OpenAI, Anthropic Claude |
| **Permission System** | Auto / Ask / Deny / Read-only modes with immutable audit log |
| **Context Compression** | Auto-compress when context window reaches 85% |
| **Workflow Engine** | Multi-step workflow creation, checkpoint save/resume |
| **Webhook** | Remote trigger via REST API with API key authentication |
| **Host Tool Detection** | Auto-detects 20+ development tools (node, python, git, docker...) |

---

## 🚀 Quick Start

```bash
# 1. Install dependencies
pip install anthropic openai chromadb psutil fastapi uvicorn sse_starlette pydantic

# 2. Set your API key
#    Option A: Environment variable
set CLAUDEZ_API_KEY=sk-your-key-here        # Windows
export CLAUDEZ_API_KEY=sk-your-key-here      # Linux/macOS

#    Option B: config.json (see Configuration section)
```

### Single Query (CLI)

```bash
python main.py "Write a Python script to calculate Fibonacci numbers"
```

### Interactive Mode

```bash
python main.py --interactive
```

### Web GUI Mode

```bash
# Random port (auto-opens browser)
python main.py --web

# Or pick a port
python main.py --web --port 8080
```

### Workflow Modes

```bash
python main.py -w coding "Build a REST API with FastAPI"
python main.py -w research "Research the latest AI frameworks"
python main.py -w debug "Debug this stack trace: ..."
python main.py -w chat "What's the weather like today?"
```

---

## 🔧 Configuration

### Environment Variables (Recommended)

| Variable | Description | Default |
|----------|-------------|---------|
| `CLAUDEZ_API_KEY` | LLM API key (preferred over config.json) | — |
| `CLAUDEZ_MODEL` | Model name override | — |
| `CLAUDEZ_PROVIDER` | Provider override | — |
| `CLAUDEZ_SESSIONS_DIR` | Session persistence directory | `~/.claudez/sessions/` |

### config.json

```json
{
    "provider": "deepseek",
    "model": "deepseek-chat",
    "base_url": "https://api.deepseek.com/v1",
    "api_key": "sk-your-key-here",
    "max_tokens": 8192,
    "temperature": 0.0,
    "workflow_mode": "agent",
    "disable_thinking": true,
    "enable_memory": true,
    "max_consecutive_errors": 5
}
```

> **Security**: Use environment variables `CLAUDEZ_API_KEY` instead of storing keys in config.json. The `.gitignore` excludes `config.json` by default.

---

## 🧠 Memory System

ClaudeZ features a two-tier memory system:

| Tier | Technology | Scope | Persistence |
|------|-----------|-------|-------------|
| **Short-Term** | In-memory dict | Current session facts, notes, task stack | Session lifetime |
| **Semantic** | ChromaDB vector store | Cross-session knowledge | Disk (persistent) |

Memory is **automatically stored** after each tool-use round and each assistant response. You can also manually search, store, and browse memories via:
- The **Memory tab** in Web GUI
- LLM tool calls: `memory_search`, `memory_store`, `memory_stats`

---

## 📂 Project Structure

```
ClaudeZ/
├── main.py                      # Entry point (CLI / Web / Harness)
├── config.json                  # Configuration file
│
├── agent/                       # Agent core (Python)
│   ├── core.py                  # Agent main loop
│   ├── prompt.py                # Dynamic prompt engine ★
│   ├── cli.py                   # CLI interface
│   ├── session.py               # Session management + persistence
│   ├── types.py                 # ContentBlock type system
│   ├── debug_stream.py          # Structured debug logging
│   ├── permissions.py           # Permission control + audit log
│   ├── workflow.py              # Workflow engine
│   ├── webhook.py               # Remote webhook trigger
│   ├── plugin_manager.py        # Plugin management
│   │
│   ├── providers/               # LLM provider abstraction
│   │   └── base.py              # DeepSeek / OpenAI / Anthropic
│   │
│   ├── tools/                   # Tool system (17+ tools)
│   │   ├── registry.py          # Tool registry (Pydantic)
│   │   ├── schema.py            # Pydantic Schema validation
│   │   ├── builtin.py           # read/write/bash/edit/glob/grep/web...
│   │   ├── subagent.py          # Sub-agent tool
│   │   ├── memory_tool.py       # Memory search/store/stats tools
│   │   ├── artifact.py          # Artifact publishing
│   │   ├── workflow_tool.py     # Workflow management
│   │   └── webhook_tool.py      # Webhook management
│   │
│   ├── memory/                  # Memory system
│   │   ├── short_term.py        # Short-term (session facts)
│   │   └── semantic.py          # Semantic (ChromaDB)
│   │
│   ├── plugins/                 # Plugin system
│   │   └── host_tools/          # Host tool chain detection (20+ tools)
│   │
│   └── web_gui/                 # Web GUI
│       ├── server.py            # FastAPI + SSE + REST API
│       └── static/
│           ├── index.html       # Dark theme frontend
│           └── app.js           # SSE rendering / tool panel / debug
│
├── harness/                     # Go native harness
│   ├── main.go                  # Entry (TUI / headless)
│   ├── go.mod                   # Go 1.22 + Bubble Tea
│   ├── runner.py                # Python-side IPC bridge
│   ├── ipc/protocol.py          # JSON-RPC 2.0 protocol
│   ├── tui/                     # Bubble Tea TUI
│   │   ├── render.go, spinner.go, theme.go
│   ├── lifecycle/watchdog.go    # Process watchdog
│   └── updater/check.go         # Auto-update
│
├── scripts/                     # Build scripts
├── tests/                       # Test suite (9 tests)
└── @claudez/                    # npm distribution
```

---

## 🌐 Web GUI Dashboard

The Web GUI provides a full-featured dashboard with:

| Panel | Content |
|-------|---------|
| 🛠 **Tools** | All registered tools with live usage stats, host tool masking |
| 🧩 **Plugins** | Plugin management, probe/reprobe, mask/unmask tools |
| 🧠 **Memory** | Memory stats, semantic search, quick store, recent memories |
| 📡 **Events** | Real-time event log with type filters |
| 🐛 **Debug** | Export structured debug logs (JSON / Markdown) |
| ⚙ **Config** | Provider, model, base URL, API key, workflow mode |

---

## 🔌 Tool System

Tools are registered via the `@tool` decorator:

```python
from agent.tools.registry import tool

@tool(category="file", timeout=30, is_readonly=True, is_concurrency_safe=True)
def read(file_path: str, head: int = 0, tail: int = 0) -> str:
    """Read file content."""
    ...
```

| Attribute | Description |
|-----------|-------------|
| `category` | Tool category (file, shell, web, system, memory...) |
| `timeout` | Execution timeout in seconds |
| `is_readonly` | Marks as read-only for permission system |
| `is_concurrency_safe` | Enables parallel execution with other safe tools |
| `require_confirmation` | Requires user confirmation before execution |

---

## 🧪 Testing

```bash
python tests/run_all.py
```

Runs 9 tests covering imports, configuration, tool registry, prompt building, session management, provider layer, IPC protocol, workflow engine, and memory system.

---

## 🌍 Comparison

| Feature | ClaudeZ v2.2 | Claude Code | Cursor | Windsurf |
|---------|-------------|-------------|--------|----------|
| **Dynamic Prompts** | ✅ **Proprietary** | ❌ | ❌ | ❌ |
| **DeepSeek Native** | ✅ **Default** | ❌ | ⚠️ 3rd party | ⚠️ 3rd party |
| **Go Native Harness** | ✅ **Unique** | ❌ Node.js | ❌ Electron | ❌ Electron |
| **Host Tool Detection** | ✅ **Unique** | ❌ | ❌ | ❌ |
| **Semantic Memory** | ✅ ChromaDB | ❌ | ❌ | ❌ |
| **Web GUI** | ✅ | ❌ | ❌ | ❌ |
| **Plugin System** | ✅ | ❌ | ✅ | ✅ |
| **Multi-Provider** | ✅ 3 providers | ❌ 1 provider | ✅ | ✅ |
| **Open Source** | ✅ MIT | ❌ | ❌ | ❌ |
| **Parallel Tool Exec** | ✅ | ❌ | ❌ | ❌ |

---

## 📚 Documentation

| Document | Description |
|----------|-------------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | System architecture and data flow |
| [API.md](API.md) | Complete API reference |
| [DEEPSEEK_TECH_STACK.md](DEEPSEEK_TECH_STACK.md) | DeepSeek integration deep dive |
| [TECHNICAL_WHITEPAPER.md](TECHNICAL_WHITEPAPER.md) | Technical whitepaper |
| [UX_AUDIT.md](UX_AUDIT.md) | UX audit report |

---

## 🤝 Contributing

Contributions are welcome! Here's how you can help:

- **🐛 Report bugs** — Open an issue with reproduction steps
- **💡 Suggest features** — Start a discussion
- **🔧 Submit PRs** — Fix bugs, add tools, improve docs
- **🌐 Translate** — Help localize documentation

Before submitting a PR:
1. Run `python tests/run_all.py` to verify nothing is broken
2. Follow the existing code style (Pydantic schemas, type hints, docstrings)
3. Add tests for new functionality

---

## 📄 License

MIT License — free to use, modify, and distribute.

---

<div align="center">
  <p><strong>Model (DeepSeek) + Harness (Go Native) = Agent</strong></p>
  <p>ClaudeZ v2.2 | 2026-07-19</p>
  <p>
    <a href="https://github.com/aliquanhou/claudez">GitHub</a> •
    <a href="https://github.com/aliquanhou/claudez/issues">Issues</a> •
    <a href="https://github.com/aliquanhou/claudez/discussions">Discussions</a>
  </p>
</div>
