# ClaudeZ 架构指南 (Architecture Guide)

## 模块依赖关系

```
main.py
  ├── agent.cli         (CLI 模式)
  ├── agent.core        (Agent 主循环)
  │   ├── agent.prompt         (动态提示词)
  │   ├── agent.providers      (LLM 提供商)
  │   ├── agent.session        (会话管理)
  │   ├── agent.tools          (工具系统)
  │   ├── agent.memory         (记忆)
  │   ├── agent.permissions    (权限)
  │   ├── agent.workflow       (工作流)
  │   └── agent.debug_stream   (调试日志)
  ├── agent.web_gui.server (Web GUI)
  └── harness.runner          (IPC 模式)
```

## 核心循环流程

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
       ├─ if response.stop_reason == "error":
       │     break
       │
       ├─ if response.tool_calls:
       │    │
       │    ├─ for tc in response.tool_calls:
       │    │    ├─ check_permission(tc.name)
       │    │    ├─ on_tool_start(name, args)   # → UI
       │    │    └─ collect tasks
       │    │
       │    ├─ execute tools (parallel safe, serial unsafe)
       │    │    └─ for each: on_tool_output(line)  # → UI 逐行
       │    │
       │    ├─ session.messages.append({
       │    │      role="assistant",
       │    │      tool_calls=[all results]
       │    │  })
       │    ├─ for each result:
       │    │    session.messages.append({
       │    │        role="tool",
       │    │        tool_call_id=id
       │    │    })
       │    │
       │    └─ continue  # 下一轮
       │
       └─ else:  # 无工具调用
            return response.content
```

## Web GUI 事件流

```
浏览器                     FastAPI                    Agent
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
  │──{"text": "消息"}───────│──thread: agent.run()───▶│
```
