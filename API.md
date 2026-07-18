# ClaudeZ API Reference (v2.2)

## CLI Interface

```bash
python main.py [options] [message...]
```

| 参数 | 说明 |
|------|------|
| `message` | 直接消息（非交互模式） |
| `--interactive` | 交互模式 |
| `-m, --model` | 模型名称 |
| `-p, --provider` | LLM 提供商 (anthropic/openai/deepseek) |
| `-w, --workflow` | 工作流模式 (chat/research/coding/debug/agent) |
| `--web` | Web GUI 模式（随机端口，自动开浏览器） |
| `--web --port 8080` | 指定端口 |
| `--harness-mode` | Harness IPC 模式 |

## Web GUI API

### SSE 事件流

```
GET /api/stream
```

SSE 事件类型：

| 事件 | 载荷 | 说明 |
|------|------|------|
| `text_delta` | `{"delta": "..."}` | 实时文本块 |
| `thinking_delta` | `{"delta": "..."}` | 思考块 |
| `tool_use_start` | `{"tool_name": ..., "args_preview": ..., "file_path": ...}` | 工具开始 |
| `tool_result` | `{"tool_name": ..., "status": ..., "result": ..., "duration_ms": ...}` | 工具结果 |
| `tool_output` | `{"tool_name": ..., "line": ...}` | 工具实时输出 |
| `session_start` | `{"agent": "claudez"}` | 会话开始 |
| `session_end` | `{"agent": "claudez"}` | 会话结束 |
| `error` | `{"message": ...}` | 错误 |
| `ping` | `{"type": "keepalive"}` | 心跳 |

### REST API

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/send` | 发送消息 `{"text": "..."}` |
| `POST` | `/api/stop` | 终止当前执行 |
| `POST` | `/api/clear` | 清空对话 |
| `GET` | `/api/config` | 获取配置 |
| `POST` | `/api/config` | 设置配置 |
| `GET` | `/api/context` | 获取状态（busy/provider/model） |
| `GET` | `/api/health` | 健康检查 |
| `GET` | `/api/debug` | 导出调试日志 JSON |
| `GET` | `/api/debug/markdown` | 导出调试报告 Markdown |
| `GET` | `/api/debug/summary` | 获取调试摘要 |
| `GET` | `/{path}` | 静态文件 |

## Agent API

### `Agent(config, session)`

```python
from agent.core import Agent
from agent.tools.builtin import *

agent = Agent({"provider": "deepseek", "model": "deepseek-chat"})
result = agent.run("你的问题")
```

#### 回调

```python
agent.on_stream = lambda chunk: print(chunk, end="")
agent.on_tool_start = lambda name, args: print(f"🛠 {name}")
agent.on_tool_call = lambda name, args, result: print(f"  → {result[:50]}")
agent.on_tool_output = lambda name, line: print(f"  [{name}] {line}")
agent.on_thinking = lambda msg: print(f"💭 {msg}")
agent.on_content_block = lambda block_type, data: ...
agent.on_error = lambda ctx, err: print(f"❌ {ctx}: {err}")
```

## IPC 协议

基于 stdin/stdout JSON-RPC：

```json
// 请求
{"id": 1, "method": "tool.call", "params": {"name": "read", "args": {...}}}
// 响应
{"id": 1, "result": "..."}
// 事件
{"method": "event", "params": {"type": "text_delta", "data": "..."}}
// 流式块
{"method": "stream", "params": "字符块"}
// 心跳
{"method": "ping"} → {"id": ..., "result": "pong"}
```
