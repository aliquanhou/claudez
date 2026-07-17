# -*- coding: utf-8 -*-
"""ClaudeZ 全面自检脚本。"""

import json, os, sys, time, tempfile

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _root)

# Force UTF-8 output
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

PASS = 0
FAIL = 0

def green(msg): return msg
def red(msg): return msg

def test(name, fn):
    global PASS, FAIL
    try:
        fn()
        PASS += 1
        print("  [PASS] %s" % name)
    except Exception as e:
        FAIL += 1
        err = str(e).replace('\n', ' | ')
        print("  [FAIL] %s: %s" % (name, err))

def test_imports():
    import agent, agent.core, agent.prompt, agent.session, agent.cli
    import agent.providers, agent.providers.base
    import agent.tools, agent.tools.registry, agent.tools.builtin
    import agent.tools.subagent, agent.tools.artifact
    import agent.tools.workflow_tool, agent.tools.webhook_tool
    import agent.memory, agent.memory.short_term
    import agent.workflow, core.tool_schema
    from harness.ipc.protocol import IPCClient, IPCServer, EventType, IPCMessage

def test_tool_registry():
    from agent.tools import get_all_tools
    tools = get_all_tools()
    assert len(tools) > 0, "工具列表为空"
    for t in tools:
        assert "function" in t
        assert "name" in t["function"]
    print("    注册工具数: %d" % len(tools))
    from agent.tools.registry import get_registry
    r = get_registry()
    a = r.get_anthropic_tools()
    assert len(a) == len(tools)

def test_prompt_builder():
    from agent.prompt import build_system_prompt, PromptContext
    from agent.tools import get_all_tools
    c = PromptContext(user_id="test", tools=get_all_tools(), workflow_mode="chat")
    p = build_system_prompt(c)
    assert len(p) > 100
    assert "ClaudeZ" in p
    for mode in ("chat","research","coding","debug","agent"):
        ctx = PromptContext(workflow_mode=mode)
        p2 = build_system_prompt(ctx)
        assert len(p2) > 50

def test_session():
    from agent.session import Session
    s = Session()
    s.add_message("user", "hi")
    s.add_message("assistant", "hello")
    s.add_tool_call("read", {"p":"t"}, "ok")
    assert s.turn_count == 1
    assert s.tool_call_count == 1
    d = s.to_dict()
    r = Session.from_dict(d)
    assert r.id == s.id
    assert len(r.messages) == 4
    # 持久化测试
    tmpdir = os.path.join(tempfile.gettempdir(), "claudez_test_%d" % int(time.time()))
    os.makedirs(tmpdir, exist_ok=True)
    try:
        s.enable_persistence(tmpdir)
        s.save()
        loaded = Session.load(s.id, tmpdir)
        assert loaded is not None
        assert loaded.turn_count == 1
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

def test_provider_layer():
    from agent.providers import create_provider, LLMResponse
    p = create_provider({"provider":"anthropic","model":"test"})
    assert "Claude" in p.name()
    p2 = create_provider({"provider":"openai","model":"gpt-4"})
    assert "OpenAI" in p2.name()
    from agent.providers.base import should_retry, exponential_backoff
    assert should_retry(TimeoutError("timeout"))
    assert should_retry(Exception("rate limit"))
    assert not should_retry(ValueError("bad"))
    d = exponential_backoff(0)
    assert d > 0

def test_ipc_protocol():
    from harness.ipc.protocol import IPCMessage, EventType, IPCMethod
    msg = IPCMessage(id=1, method=IPCMethod.PING)
    d = msg.to_dict()
    assert d["id"] == 1
    assert d["method"] == "ping"
    msg2 = IPCMessage.from_dict(d)
    assert msg2.id == 1
    assert msg2.method == "ping"

def test_workflow():
    from agent.workflow import create_workflow, WorkflowResumer, WorkflowSerializer
    s = create_workflow("test", ["s1","s2","s3"])
    assert len(s.steps) == 3
    r = WorkflowResumer(s)
    assert r.get_progress()["total"] == 3
    r.mark_step_completed(0,"ok")
    r.mark_step_completed(1,"ok")
    r.mark_step_completed(2,"ok")
    assert r.is_complete()
    with tempfile.TemporaryDirectory() as tmp:
        p = "%s/wf.json" % tmp
        WorkflowSerializer.save(s, p)
        loaded = WorkflowSerializer.load(p)
        assert loaded.id == s.id

def test_config():
    from agent.cli import load_config
    c = load_config()
    assert "provider" in c
    assert "model" in c
    print("    提供商: %s  模型: %s" % (c["provider"], c["model"]))

def test_memory():
    from agent.memory.short_term import ShortTermMemory
    m = ShortTermMemory()
    m.remember("fact1", "memory 1")
    m.remember("fact2", "memory 2")
    assert len(m.facts) == 2
    m.clear()
    assert len(m.facts) == 0

print("="*50)
print("  ClaudeZ 全面自检")
print("="*50)
print()

tests = [
    ("模块导入", test_imports),
    ("配置加载", test_config),
    ("工具注册表", test_tool_registry),
    ("动态提示词", test_prompt_builder),
    ("会话管理", test_session),
    ("Provider层", test_provider_layer),
    ("IPC协议", test_ipc_protocol),
    ("工作流引擎", test_workflow),
    ("记忆系统", test_memory),
]

for name, fn in tests:
    test(name, fn)

print()
print("="*50)
total = PASS + FAIL
print("  结果: %d/%d 通过" % (PASS, total), end="")
if FAIL > 0:
    print(", %d 失败" % FAIL)
    sys.exit(1)
else:
    print("  [ALL OK]")
print("="*50)
