# ClaudeZ Architecture Guide

## Module Dependency

```
main.py
  ├── agent.cli            (CLI mode)
  ├── agent.core           (Agent main loop)
  │   ├── agent.prompt            (Dynamic prompt engine)
  │   ├── agent.providers         (LLM providers)
  │   ├── agent.session           (Session management)
  │   ├── agent.tools             (Tool system)
  │   ├── agent.memory            (Short-term + Semantic memory)
  │   ├── agent.permissions       (Permission control)
  │   ├── agent.workflow          (Workflow engine)
  │   └── agent.debug_stream      (Debug logging)
  ├── agent.web_gui.server  (Web GUI)
  └── harness.runner        (IPC harness mode)
```

## Core Loop Flow

```
run(user_message)
  │
  ├─ session.add_message("user", ...)
  │
  └─ while _running:
       │
       ├─ messages = session.get_recent_messages()
       │
       ├─ system_prompt = prompt_builder.build(PromptContext{
       │      tools=get_all_tools(),
       │      workflow_mode="agent",
       │      memories=search_memories(),
       │      session_state=get_state(),
       │      constraints={...},
       │  })
       │
       ├─ response = provider.chat_with_retry(
       │      system_prompt, messages, tools)
       │
       ├─ if response.tool_calls:
       │    │
       │    ├─ separate concurrency_safe vs serial tools
       │    ├─ parallel(concurrency_safe)  # ThreadPoolExecutor
       │    ├─ serial(remaining)
       │    │
       │    ├─ auto-store tool memories
       │    ├─ session.append(assistant + tool messages)
       │    └─ continue
       │
       └─ else:
            ├─ auto-store response memory
            └─ return response.content
```

## Memory System Architecture

```
┌─────────────────────────────────────────────────────┐
│                  Memory System                       │
├─────────────────────┬───────────────────────────────┤
│   ShortTermMemory   │      SemanticMemory           │
│   (session scope)   │    (ChromaDB vector store)    │
├─────────────────────┼───────────────────────────────┤
│ • facts (key/value) │ • store(content, metadata)    │
│ • notes (timeline)  │ • search(query, top_k)        │
│ • tags              │ • get_recent(limit)           │
│ • task_stack        │ • delete / clear / count      │
│ • clear()           │ • auto-persisted to disk      │
└─────────────────────┴───────────────────────────────┘
         │                       │
         └──────────┬────────────┘
                    ▼
         PromptContext.memories
                    │
                    ▼
         _build_memory_block()
                    │
                    ▼
         System prompt (dynamic injection)
```

## Web GUI Event Flow

```
Browser                    FastAPI                    Agent
  │                         │                         │
  │──GET /api/stream───────▶│                         │
  │                         │ SSE connection           │
  │◀───event: text_delta────│◀───on_stream(chunk)─────│
  │◀───event: tool_use_start│◀───on_tool_start()──────│
  │◀───event: tool_output──│◀───on_tool_output()──────│
  │◀───event: tool_result──│◀───on_tool_call()────────│
  │◀───event: session_end──│◀───run() complete────────│
  │                         │                         │
  │──POST /api/send────────▶│                         │
  │──{"text": "message"}────│──thread: agent.run()───▶│
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Index HTML |
| GET | `/api/stream` | SSE event stream |
| POST | `/api/send` | Send message |
| POST | `/api/stop` | Stop agent |
| POST | `/api/clear` | Clear session |
| GET | `/api/config` | Get config |
| POST | `/api/config` | Set config |
| GET | `/api/context` | Get context |
| GET | `/api/health` | Health check |
| GET | `/api/debug` | Export debug JSON |
| GET | `/api/debug/markdown` | Export debug MD |
| GET | `/api/memory` | Memory stats + recent |
| POST | `/api/memory/search` | Semantic memory search |
| POST | `/api/memory/store` | Store memory |
| POST | `/api/memory/clear` | Clear all memories |
| GET | `/api/plugins` | List plugins + tools |
| POST | `/api/plugins/discover` | Rescan plugins |

## Tool Execution Model

1. LLM returns `tool_calls` with N tools
2. Each tool is classified: `is_concurrency_safe` or serial
3. Concurrency-safe tools (read, glob, grep, web_search, memory_search, memory_stats) → **ThreadPoolExecutor (max 8 workers)**
4. Serial tools (write, edit, bash, subagent, artifact) → **sequential execution**
5. Results are assembled in original order and appended to session
6. Memory is auto-stored after tool round

## Extension Points

- **Add a tool**: Create a function with `@tool()` decorator, import in `agent/tools/__init__.py`
- **Add a provider**: Subclass `LLMProvider` in `agent/providers/base.py`, add to `create_provider()`
- **Add a prompt section**: Call `prompt_builder.register_section()` with a builder function
- **Add a plugin**: Create `plugin.py` + `manifest.json` in a plugin directory
- **Add an API endpoint**: Add route handlers in `agent/web_gui/server.py`
