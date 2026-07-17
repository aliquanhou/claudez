# ClaudeZ DeepSeek 技术栈文档

> ClaudeZ v2.1 — Model + Harness = Agent，专业为 DeepSeek 而生

---

## 目录

1. [设计哲学](#1-设计哲学)
2. [DeepSeek 原生集成](#2-deepseek-原生集成)
3. [动态提示词引擎](#3-动态提示词引擎)
4. [Provider 适配层](#4-provider-适配层)
5. [Go Harness 原生壳层](#5-go-harness-原生壳层)
6. [IPC 通信协议](#6-ipc-通信协议)
7. [工具系统](#7-工具系统)
8. [插件系统](#8-插件系统)
9. [记忆系统](#9-记忆系统)
10. [工作流引擎](#10-工作流引擎)
11. [Web GUI](#11-web-gui)
12. [会话管理](#12-会话管理)
13. [权限与安全](#13-权限与安全)
14. [调试与可观测性](#14-调试与可观测性)
15. [构建与分发](#15-构建与分发)
16. [跨平台支持](#16-跨平台支持)
17. [性能基准](#17-性能基准)
18. [与 DeepSeek 的最佳实践](#18-与-deepseek-的最佳实践)

---

## 1. 设计哲学

### 核心公式

```
Model (DeepSeek) + Harness (Go Native) = Agent (ClaudeZ)
```

ClaudeZ 的核心理念是将**大语言模型**与**原生壳层**深度结合，创造自主 AI 智能体。与传统的"聊天机器人+工具调用"不同，ClaudeZ 从架构底层即围绕以下原则设计：

| 原则 | 描述 |
|------|------|
| **动态提示词** | 每次 LLM 调用前根据当前上下文实时构建系统提示词 |
| **原生壳层** | Go 编写的原生 Harness 提供进程管理、TUI、自动更新 |
| **工具即接口** | 所有能力通过工具暴露，LLM 自主选择调用 |
| **记忆分层** | 短期记忆 + 语义记忆（ChromaDB）两级记忆架构 |
| **插件生态** | 插件系统支持动态发现、加载、卸载工具 |

### 为什么选择 DeepSeek 作为默认引擎？

ClaudeZ 的默认配置、提示词模板、重试逻辑、上下文窗口管理均针对 DeepSeek 系列模型进行了深度优化：

```
config.json (默认):
{
    "provider": "deepseek",
    "model": "deepseek-chat",
    "base_url": "https://api.deepseek.com/v1",
    "max_tokens": 8192,
    "temperature": 0.0
}
```

---

## 2. DeepSeek 原生集成

### 2.1 默认 Provider

ClaudeZ 以 DeepSeek 作为首选 LLM Provider，从三个层面实现深度集成：

```
用户输入
    │
    ▼
┌─────────────────────────────────────────────┐
│   Agent Core (core.py)                       │
│   └─ 自动选择 DeepSeek Provider              │
│       ├─ deepseek-chat (默认)                │
│       ├─ deepseek-reasoner (推理模式)        │
│       └─ deepseek-coder (代码模式)           │
└─────────────────────────────────────────────┘
```

### 2.2 Thinking 模式控制

DeepSeek 的 reasoning/thinking 能力在 ClaudeZ 中得到一等支持：

```python
# providers/base.py — DeepSeek Provider
class DeepSeekProvider(BaseProvider):
    """DeepSeek API 适配器，支持 thinking 模式控制。"""

    def _build_request(self, messages, tools, **kwargs):
        # 自动注入 thinking 参数
        if self.config.get("disable_thinking"):
            payload["thinking"] = {"type": "disabled"}
        else:
            payload["thinking"] = {"type": "enabled", "budget_tokens": 2048}
        return payload
```

**流式 thinking 事件**：DeepSeek 的 thinking 内容通过 SSE 实时推送到 Web GUI 和 Go TUI，以 🧠 图标区分显示：

```
🧠 Thinking: 让我分析一下这个问题...
    └─ 用户想实现一个 REST API，需要先设计数据模型
💬 根据您的需求，我建议使用 FastAPI + SQLAlchemy...
```

### 2.3 DeepSeek API 配置

完整的 DeepSeek API 配置项：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `provider` | `"deepseek"` | LLM 提供商 |
| `model` | `"deepseek-chat"` | 模型名称 |
| `api_key` | `"sk-..."` | API 密钥 |
| `base_url` | `"https://api.deepseek.com/v1"` | API 端点 |
| `max_tokens` | `8192` | 最大输出 Token |
| `temperature` | `0.0` | 生成温度 |
| `timeout` | `3600` | API 超时（秒） |
| `disable_thinking` | `true` | 禁用 thinking 模式 |
| `enable_caching` | `false` | 启用语义缓存 |

### 2.4 指数退避重试

针对 DeepSeek API 的限流和超时做了专门的重试策略：

```python
# providers/base.py
def _call_with_retry(self, payload):
    for attempt in range(self.config.get("max_retries", 3)):
        try:
            return self._do_request(payload)
        except (ConnectionError, TimeoutError) as e:
            if attempt == max_retries - 1:
                raise
            delay = base_delay * (2 ** attempt) + random.uniform(0, 0.5)
            time.sleep(delay / 1000)
        except HTTPStatusError as e:
            if e.response.status_code == 429:  # Rate limited
                retry_after = int(e.response.headers.get("retry-after", 10))
                time.sleep(retry_after)
```

---

## 3. 动态提示词引擎

### 3.1 架构

```python
# agent/prompt.py — 每次 LLM 调用前执行
class DynamicPromptEngine:
    def build_system_prompt(self, context):
        return "\n".join([
            self._build_persona(context),       # 身份角色
            self._build_capabilities(context),   # 能力描述
            self._build_tools(context),          # 工具列表（实时注入）
            self._build_memory(context),         # 记忆注入
            self._build_constraints(context),    # 约束条件（动态生成）
            self._build_adaptations(context),    # 自适应调整
            self._build_workflow_mode(context),  # 工作流模式
        ])
```

### 3.2 动态注入的内容

| 模块 | 内容 | 更新频率 |
|------|------|----------|
| 工具列表 | 所有已注册工具的 JSON Schema | 每次调用 |
| 工作流模式 | chat / research / coding / debug / agent | 每次调用 |
| 自适应调整 | 基于错误率、重复调用的行为约束 | 每次调用 |
| 记忆注入 | 语义记忆 + 短期记忆 + 项目上下文 | 每次调用 |
| 约束条件 | 权限、超时、语言、禁止操作 | 每次调用 |

### 3.3 DeepSeek 特定优化

针对 DeepSeek 模型家族的提示词模板优化：

```python
# 针对 deepseek-reasoner 的提示词模板
DEEPSEEK_REASONER_SYSTEM = """You are ClaudeZ, an autonomous AI agent powered by DeepSeek.
You have access to a comprehensive tool system. Think step by step.

工具使用规则:
1. 每次思考后，选择最合适的工具执行
2. 工具执行结果会以 JSON 格式返回
3. 根据结果决定下一步行动或给出最终答案
"""

# 针对 deepseek-coder 的提示词模板
DEEPSEEK_CODER_SYSTEM = """You are ClaudeZ-Coder, a coding agent powered by DeepSeek.
You excel at code generation, debugging, and refactoring.

代码工具:
- read: 读取文件内容
- write: 写入文件
- edit: 编辑现有文件
- bash: 执行命令
"""
```

---

## 4. Provider 适配层

### 4.1 统一接口

```python
class BaseProvider(ABC):
    """所有 Provider 的统一抽象。"""

    @abstractmethod
    def send_message(self, messages, tools=None, **kwargs) -> Message:
        """发送消息并获取回复。"""

    @abstractmethod
    def stream_message(self, messages, tools=None, **kwargs) -> Iterator[Chunk]:
        """流式发送消息。"""

    @abstractmethod
    def count_tokens(self, text: str) -> int:
        """计算 token 数量。"""
```

### 4.2 Provider 实现

| Provider | 模型 | 特性 |
|----------|------|------|
| `DeepSeekProvider` | deepseek-chat, deepseek-reasoner, deepseek-coder | Thinking 控制、8192 max_tokens、FIM |
| `AnthropicProvider` | claude-sonnet-4, claude-opus-4 | Tool use、Streaming、缓存 |
| `OpenAIProvider` | gpt-4o, gpt-4o-mini | Function calling、视觉 |

### 4.3 自动消息序列修复

针对 DeepSeek API 对消息序列的严格要求，Provider 层实现自动修复：

```python
def _fix_message_sequence(self, messages):
    """修复消息序列，确保符合 DeepSeek API 要求。"""
    fixed = []
    for i, msg in enumerate(messages):
        # 确保首条消息为 system 或 user 角色
        if i == 0 and msg["role"] not in ("system", "user"):
            fixed.append({"role": "user", "content": "[Context] " + msg.get("content", "")})
            continue
        # 修复连续的 assistant 消息
        if msg["role"] == "assistant" and i > 0 and messages[i-1]["role"] == "assistant":
            fixed.append({"role": "user", "content": "[Continue]"})
        fixed.append(msg)
    return fixed
```

---

## 5. Go Harness 原生壳层

### 5.1 架构总览

```
┌──────────────────────────────────────────────────┐
│              Go Harness (main.go)                  │
│  ┌─────────────┐  ┌────────────┐  ┌────────────┐  │
│  │   TUI       │  │  Watchdog  │  │  Updater   │  │
│  │ (bubbletea) │  │ (lifecycle)│  │  (GitHub)  │  │
│  └──────┬──────┘  └─────┬──────┘  └─────┬──────┘  │
│         │               │               │         │
│  ┌──────┴────────────────┴───────────────┴──────┐  │
│  │            IPC Protocol (stdin/stdout)        │  │
│  └──────────────────────┬───────────────────────┘  │
│                         │                          │
├─────────────────────────┼──────────────────────────┤
│              Python Core (runner.py)               │
│  ┌─────────────┐  ┌────┴─────┐  ┌──────────────┐  │
│  │  Agent Loop │  │  Tools   │  │  Web GUI     │  │
│  └─────────────┘  └──────────┘  └──────────────┘  │
└──────────────────────────────────────────────────┘
```

### 5.2 技术规格

| 组件 | 技术 | 版本 |
|------|------|------|
| TUI 框架 | Charmbracelet Bubble Tea | v1.1.0 |
| 终端样式 | Charmbracelet Lipgloss | v0.13.0 |
| 终端检测 | mattn/go-isatty | v0.0.20 |
| IPC 协议 | JSON-RPC 2.0 over stdin/stdout | 自定义 |
| 进程管理 | OS 信号 + 看门狗定时器 | 自定义 |

### 5.3 进程看门狗

Watchdog 提供生产级进程生命周期管理：

| 特性 | 参数 | 说明 |
|------|------|------|
| 最大重启次数 | 3 次 | 崩溃后自动重启 |
| 重启延迟 | 2 秒 | 重启前的等待时间 |
| 关闭超时 | 5 秒 | 优雅关闭等待时间 |
| 心跳间隔 | 5 秒 | 子进程健康检查 |
| 心跳超时 | 10 秒 | 超时触发强制重启 |

### 5.4 Bubble Tea TUI

TUI 提供分屏聊天风格界面：

```
┌──────────────────────────────────────────────────┐
│  ⣾ ClaudeZ v2.1 — DeepSeek Agent                 │
├──────────────────────────────────────────────────┤
│                                                  │
│  💬 你好！我可以帮你完成各种任务...                │
│                                                  │
│  🛠️ 使用工具: bash                              │
│  └─ $ python --version                          │
│     Python 3.12.0                                │
│                                                  │
│  🧠 Thinking: 让我分析一下...                     │
│                                                  │
│  ✅ 任务完成                                     │
│                                                  │
├──────────────────────────────────────────────────┤
│  Ready           Tools: 5  Errors: 0 │ agent │ DS │
└──────────────────────────────────────────────────┘
```

---

## 6. IPC 通信协议

### 6.1 协议规范

基于 JSON-RPC 2.0 的双向通信协议：

```json
// 请求
{"id": 1, "method": "tool_call", "params": {"name": "bash", "args": ["ls"]}}
// 响应
{"id": 1, "result": {"stdout": "file1.txt\nfile2.txt", "exit_code": 0}}
// 事件（流式）
{"method": "event", "params": {"type": "stream", "data": "正在处理..."}}
// 心跳
{"id": 2, "method": "ping", "params": {}}
{"id": 2, "result": "pong"}
```

### 6.2 事件类型

| 事件 | 方向 | 说明 |
|------|------|------|
| `MESSAGE_START` | Core → Harness | 消息开始 |
| `MESSAGE_DELTA` | Core → Harness | 流式内容块 |
| `MESSAGE_STOP` | Core → Harness | 消息结束 |
| `TEXT_DELTA` | Core → Harness | 文本增量 |
| `THINKING_DELTA` | Core → Harness | DeepSeek thinking 内容 |
| `TOOL_START` | Core → Harness | 工具开始执行 |
| `TOOL_RESULT` | Core → Harness | 工具执行结果 |
| `TOOL_ERROR` | Core → Harness | 工具执行错误 |
| `SESSION_START` | Core → Harness | 会话开始 |
| `SESSION_END` | Core → Harness | 会话结束 |
| `PING` | 双向 | 心跳检测 |

### 6.3 Python 侧 Transport

```python
class StdioTransport(Transport):
    """基于 stdin/stdout 的传输层实现。"""

    def send(self, data: str):
        with self._lock:
            sys.stdout.write(data + "\n")
            sys.stdout.flush()

    def recv(self, timeout: float = None) -> str | None:
        # Unix: select.select() 非阻塞读取
        # Windows: sys.stdin.readline() 阻塞读取
```

---

## 7. 工具系统

### 7.1 工具注册

使用 `@tool` 装饰器声明工具：

```python
@tool(
    name="bash",
    description="执行 shell 命令并返回输出",
    readonly=False,
    concurrency_safe=False,
)
def bash_execute(command: str, timeout: int = 30) -> dict:
    """执行 bash 命令。"""
    result = subprocess.run(command, shell=True, capture_output=True, timeout=timeout)
    return {
        "stdout": result.stdout[-6000:],  # 截断至 6000 字符
        "stderr": result.stderr[-6000:],
        "exit_code": result.returncode,
    }
```

### 7.2 内置工具清单

| 工具 | 说明 | Readonly | 并发安全 |
|------|------|----------|----------|
| `read` | 读取文件内容 | ✅ | ✅ |
| `write` | 写入文件 | ❌ | ❌ |
| `edit` | 编辑文件（diff 预览） | ❌ | ❌ |
| `bash` | 执行 shell 命令 | ❌ | ❌ |
| `glob` | 文件模式匹配 | ✅ | ✅ |
| `grep` | 内容搜索 | ✅ | ✅ |
| `thinking` | 显式思考步骤 | ✅ | ✅ |
| `subagent` | 启动子 Agent | ❌ | ✅ |
| `web_fetch` | 获取网页内容 | ✅ | ✅ |
| `web_search` | 搜索网络 | ✅ | ✅ |

### 7.3 工具 Schema

基于 Pydantic 的 Schema 校验：

```python
class ToolContext(BaseModel):
    """工具执行上下文。"""
    working_dir: str = Field(default=".", description="工作目录")
    env: dict[str, str] = Field(default_factory=dict, description="环境变量")
    timeout: int = Field(default=30, description="超时秒数")
    session_id: str = Field(default="", description="会话 ID")

class ToolResult(BaseModel):
    """工具执行结果。"""
    success: bool = Field(default=True)
    output: str = Field(default="", max_length=6000)
    error: str | None = Field(default=None)
    metadata: dict = Field(default_factory=dict)
```

---

## 8. 插件系统

### 8.1 架构

```python
PluginManager
├── discover()          # 扫描插件目录
├── load(plugin_id)     # 加载插件（调用 on_load + 注册工具）
├── unload(plugin_id)   # 卸载插件（调用 on_unload + 注销工具）
├── reload(plugin_id)   # 重新加载（re-probe 后刷新工具）
├── execute(id, tool, args)  # 执行插件工具
└── get_all_tools()     # 获取所有已启用插件的工具
```

### 8.2 插件目录结构

```
~/.claudez/plugins/
├── builtin/          # 内置插件（随 Agent 发布）
│   └── host_tools/   # 主机工具链探测插件
│       ├── manifest.json  # 插件元数据
│       └── plugin.py      # 插件实现
├── community/        # 社区插件（用户安装）
└── user/             # 用户自定义插件
```

### 8.3 主机工具链探测

自动探测本机开发工具链并挂载为 Agent 可调用工具：

| 工具 | 探测命令 | 版本检测 |
|------|----------|----------|
| Node.js | `node --version` | v20.11.0 |
| Python | `python --version` | Python 3.12.0 |
| Git | `git --version` | git version 2.40.0 |
| Docker | `docker --version` | Docker version 24.0.2 |
| Go | `go version` | go1.22.0 |
| Java | `java -version` | 17.0.6 |
| Rust | `rustc --version` | rustc 1.70.0 |
| .NET SDK | `dotnet --version` | 7.0.100 |
| Flutter | `flutter --version` | Flutter 3.10.0 |
| 共 20+ 工具 | — | — |

### 8.4 插件屏蔽机制

用户可通过 `.tool_mask.json` 屏蔽不需要的工具：

```json
{
    "masked": ["adb", "aapt2", "zipalign"]
}
```

被屏蔽的工具在 `get_tools()` 中自动过滤，不会注册到 LLM 工具列表中。

---

## 9. 记忆系统

### 9.1 两层记忆架构

```
短期记忆 (ShortTermMemory)
├── 会话内事实存储
├── 自动提取关键信息
└── 会话结束时可选持久化

语义记忆 (SemanticMemory)
├── ChromaDB 向量存储
├── 相似度检索 (top-k)
└── 跨会话记忆持久化
```

### 9.2 短期记忆

```python
class ShortTermMemory:
    def __init__(self):
        self.facts: dict[str, str] = {}  # key -> value 事实存储

    def add_fact(self, key: str, value: str):
        self.facts[key] = value

    def get_context(self) -> str:
        """返回当前短期记忆的文本表示。"""
        if not self.facts:
            return ""
        return "【短期记忆】\n" + "\n".join(
            f"- {k}: {v}" for k, v in self.facts.items()
        )
```

### 9.3 语义记忆

```python
class SemanticMemory:
    def __init__(self, persist_dir: str = ".claudez_memory"):
        self.client = chromadb.PersistentClient(path=persist_dir)
        self.collection = self.client.get_or_create_collection(
            name="claudez_memory",
            embedding_function=embeddings  # 可插拔嵌入模型
        )

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        return self.collection.query(query_texts=[query], n_results=top_k)

    def store(self, text: str, metadata: dict = None):
        self.collection.add(
            documents=[text],
            metadatas=[metadata or {}],
            ids=[str(uuid4())]
        )
```

---

## 10. 工作流引擎

### 10.1 内置工作流模式

| 模式 | 触发方式 | 说明 |
|------|----------|------|
| `chat` | `python main.py -w chat` | 自由对话模式 |
| `research` | `python main.py -w research` | 深度研究模式（多步搜索+验证） |
| `coding` | `python main.py -w coding` | 代码开发模式（严格文件操作） |
| `debug` | `python main.py -w debug` | 调试模式（详细日志+分步执行） |
| `agent` | `python main.py -w agent`（默认） | 全功能 Agent 模式 |

### 10.2 工作流切换

```python
# workflow.py
class WorkflowEngine:
    def build_prompt(self, mode: str) -> str:
        if mode == "coding":
            return """
## 代码开发工作流
1. 先理解需求
2. 设计代码结构
3. 分步实现
4. 测试验证
5. 优化改进
"""
        elif mode == "research":
            return """
## 深度研究工作流
1. 明确研究问题
2. 搜索多个来源
3. 交叉验证信息
4. 综合整理结果
5. 引用来源
"""
```

---

## 11. Web GUI

### 11.1 技术栈

| 组件 | 技术 |
|------|------|
| 后端框架 | FastAPI |
| 实时通信 | Server-Sent Events (SSE) |
| 前端 | 原生 HTML + CSS + JS |
| 自动开浏览器 | Python webbrowser 模块 |

### 11.2 API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/` | GET | Web GUI 主页 |
| `/api/chat` | POST | 发送消息（流式响应） |
| `/api/tools` | GET | 获取工具列表 |
| `/api/session` | GET | 获取会话状态 |
| `/api/config` | GET/PUT | 获取/更新配置 |
| `/api/plugins` | GET | 获取插件列表 |
| `/api/plugins/toggle` | POST | 启用/禁用插件 |
| `/api/plugins/reload` | POST | 重新加载插件 |
| `/api/logs` | GET | 获取调试日志 |
| `/stream` | GET | SSE 流式端点 |

### 11.3 启动方式

```bash
python main.py --web              # 随机端口，自动开浏览器
python main.py --web --port 8080  # 指定端口
# 或双击 启动WebUI.bat
```

---

## 12. 会话管理

### 12.1 Session 生命周期

```python
class Session:
    def __init__(self):
        self.id: str = str(uuid4())
        self.messages: list[dict] = []
        self.created_at: float = time.time()
        self.metadata: dict = {}

    def add_message(self, role: str, content: str):
        self.messages.append({"role": role, "content": content})

    def get_context(self, max_messages: int = 50) -> list[dict]:
        return self.messages[-max_messages:]

    def save(self, path: str):
        """持久化会话到磁盘。"""
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"id": self.id, "messages": self.messages}, f)
```

### 12.2 上下文压缩

当上下文利用率超过阈值时自动压缩：

| 配置 | 默认值 | 说明 |
|------|--------|------|
| `max_context_messages` | 50 | 最大消息数 |
| `context_compress_at` | 0.85 | 压缩触发阈值 |
| `compression_strategy` | summary | 压缩策略 |

---

## 13. 权限与安全

### 13.1 权限模式

| 模式 | 说明 |
|------|------|
| `auto` | 自动批准已知安全操作 |
| `allow_all` | 允许所有操作 |
| `strict` | 每次操作都需要确认 |

### 13.2 审计日志

所有工具调用和权限决策都记录到结构化日志：

```python
class PermissionManager:
    def log_decision(self, action: str, tool: str, allowed: bool):
        self.audit_log.append({
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "tool": tool,
            "allowed": allowed,
            "session_id": self.session.id,
        })
```

---

## 14. 调试与可观测性

### 14.1 DebugCollector

```python
class DebugCollector:
    """结构化调试数据收集器。"""
    data = {
        "session": {"id": "...", "model": "deepseek-chat", "version": "2.1"},
        "tool_calls": [],     # 每次工具调用的详情
        "decisions": [],      # LLM 决策记录
        "message_flow": [],   # 消息流记录
        "api_calls": [],      # API 调用记录（含耗时）
    }
```

### 14.2 调试面板

Web GUI 中包含调试面板，支持：

| 功能 | 说明 |
|------|------|
| 实时工具调用日志 | 查看每次工具调用的输入输出 |
| API 调用耗时 | 查看每次 LLM API 调用的延迟 |
| 消息流回放 | 回溯完整的消息交互序列 |
| 一键导出 | JSON / Markdown 格式导出 |

---

## 15. 构建与分发

### 15.1 构建脚本

```bash
# Windows
scripts\build.bat

# Linux/macOS
./scripts/build.sh
```

### 15.2 npm 分发

```json
// @claudez/cli/package.json
{
  "name": "@claudez/cli",
  "version": "2.1.0",
  "bin": { "claudez": "./bin/claudez.js" },
  "optionalDependencies": {
    "@claudez/harness-win32-x64": "2.1.0",
    "@claudez/harness-darwin-arm64": "2.1.0",
    "@claudez/harness-linux-x64": "2.1.0"
  }
}
```

### 15.3 平台二进制

| 包名 | 平台 | CPU |
|------|------|-----|
| `@claudez/harness-win32-x64` | Windows | x64 |
| `@claudez/harness-darwin-arm64` | macOS | ARM64 (Apple Silicon) |
| `@claudez/harness-linux-x64` | Linux | x64 |

---

## 16. 跨平台支持

| 特性 | Windows | macOS | Linux |
|------|---------|-------|-------|
| Python Core | ✅ | ✅ | ✅ |
| Go Harness | ✅ | ✅ | ✅ |
| IPC (stdin/stdout) | ✅ | ✅ | ✅ |
| TUI (bubbletea) | ✅ | ✅ | ✅ |
| Web GUI | ✅ | ✅ | ✅ |
| ChromaDB | ✅ | ✅ | ✅ |
| Auto-updater | ✅ | ✅ | ✅ |
| npm install | ✅ | ✅ | ✅ |

---

## 17. 性能基准

### 17.1 DeepSeek API 性能

| 指标 | deepseek-chat | deepseek-reasoner |
|------|---------------|-------------------|
| 首 Token 延迟 | ~300ms | ~500ms |
| 输出速度 | ~50 tokens/s | ~30 tokens/s |
| 最大输出 | 8192 tokens | 8192 tokens |
| 上下文窗口 | 64K tokens | 64K tokens |

### 17.2 工具执行延迟

| 工具 | 平均延迟 | P99 延迟 |
|------|----------|----------|
| `read` (100 lines) | 2ms | 5ms |
| `write` (100 lines) | 3ms | 8ms |
| `edit` (diff) | 5ms | 15ms |
| `bash` (simple) | 50ms | 200ms |
| `glob` (100 files) | 10ms | 30ms |
| `grep` (100 files) | 100ms | 500ms |
| `web_fetch` | 500ms | 2000ms |

### 17.3 启动时间

| 模式 | 冷启动 | 热启动 |
|------|--------|--------|
| CLI | 1.2s | 0.3s |
| Web GUI | 2.5s | 0.5s |
| Harness TUI | 1.5s | 0.4s |

---

## 18. 与 DeepSeek 的最佳实践

### 18.1 配置推荐

```json
{
    "provider": "deepseek",
    "model": "deepseek-chat",
    "temperature": 0.0,
    "max_tokens": 8192,
    "disable_thinking": true,
    "retry_base_delay_ms": 1000,
    "max_retries": 3
}
```

### 18.2 模型选择指南

| 任务类型 | 推荐模型 | 说明 |
|----------|----------|------|
| 通用对话 | deepseek-chat | 快速、经济 |
| 复杂推理 | deepseek-reasoner | 更长思考时间 |
| 代码生成 | deepseek-coder | 代码专项优化 |
| 代码审查 | deepseek-coder | 擅长发现代码问题 |

### 18.3 Token 管理

```python
# 针对 DeepSeek 的上下文管理
MAX_TOKENS = 8192
CONTEXT_WINDOW = 65536  # DeepSeek 上下文窗口
COMPRESS_THRESHOLD = 0.85  # 85% 触发压缩
```

### 18.4 错误处理

| 错误类型 | 处理策略 |
|----------|----------|
| 超时 (Timeout) | 指数退避重试，最多 3 次 |
| 限流 (429) | 读取 Retry-After 头，等待后重试 |
| 连接错误 | 立即重试 1 次 |
| 认证错误 (401) | 停止重试，提示用户检查 API Key |

---

> ClaudeZ v2.1 — Model (DeepSeek) + Harness (Go Native) = Agent
>
> 文档更新: 2026-07-18
