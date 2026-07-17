"""ClaudeZ — 动态提示词驱动的自主 AI 智能体。

快速启动:
  python main.py "你的问题"
  python main.py --interactive
  python main.py -w coding "写一个 Python 函数"
  python main.py --web              # Web GUI（随机端口，自动开浏览器）
  python main.py --web --port 8080  # 指定端口
  python main.py --harness-mode     # Harness IPC 模式
"""

import sys

# 注册内置工具（必须在 Agent 创建前 import）
from agent.tools import builtin  # noqa: F401


def main():
    """主入口。"""
    if "--web" in sys.argv:
        sys.argv = [a for a in sys.argv if a != "--web"]
        _run_web()
    elif "--harness-mode" in sys.argv:
        sys.argv.remove("--harness-mode")
        _run_harness()
    else:
        from agent.cli import main as cli_main
        cli_main()


def _run_web():
    """以 Web GUI 模式启动。"""
    from agent.web_gui.server import start
    from agent.core import Agent
    from agent.cli import load_config

    config = load_config()

    # 从 sys.argv 中提取额外参数
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("-m", "--model", default="")
    parser.add_argument("-p", "--provider", default="")
    parser.add_argument("-w", "--workflow", default="")
    parser.add_argument("message", nargs="*")
    args, _ = parser.parse_known_args()

    if args.model:
        config["model"] = args.model
    if args.provider:
        config["provider"] = args.provider
    if args.workflow:
        config["workflow_mode"] = args.workflow

    agent = Agent(config)
    ws = start(host=args.host, port=args.port, agent=agent)
    try:
        ws._thread.join()
    except KeyboardInterrupt:
        pass


def _run_harness():
    """以 Harness IPC 模式启动。"""
    from agent.core import Agent
    from agent.cli import load_config
    from harness.runner import HarnessRunner

    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("message", nargs="*")
    parser.add_argument("-c", "--config", default="")
    parser.add_argument("-m", "--model", default="")
    parser.add_argument("-p", "--provider", default="")
    parser.add_argument("-w", "--workflow", default="agent")
    args, _ = parser.parse_known_args()

    config = load_config(args.config)
    if args.model:
        config["model"] = args.model
    if args.provider:
        config["provider"] = args.provider
    if args.workflow:
        config["workflow_mode"] = args.workflow

    agent = Agent(config)
    runner = HarnessRunner(agent)
    message = " ".join(args.message) if args.message else ""
    runner.run(message)


if __name__ == "__main__":
    main()
