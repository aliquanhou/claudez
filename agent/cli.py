"""cli — ClaudeZ 命令行界面。"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .core import Agent
from .tools import get_registry
from .tools.builtin import *  # 注册内置工具


def load_config(config_path: str = "") -> dict:
    """加载配置文件。"""
    paths = [
        config_path,
        "config.json",
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json"),
    ]

    for p in paths:
        if p and os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)

    return {}


def main():
    """CLI 主入口。"""
    import argparse

    parser = argparse.ArgumentParser(description="ClaudeZ — 动态提示词驱动的 AI 智能体")
    parser.add_argument("message", nargs="*", help="直接输入消息（非交互模式）")
    parser.add_argument("-c", "--config", default="", help="配置文件路径")
    parser.add_argument("-m", "--model", default="", help="模型名称")
    parser.add_argument("-p", "--provider", default="", help="LLM 提供商")
    parser.add_argument("-w", "--workflow", default="agent",
                        choices=["chat", "research", "coding", "debug", "agent"],
                        help="工作流模式")
    parser.add_argument("--interactive", action="store_true", help="交互模式")

    args = parser.parse_args()

    # 加载配置
    config = load_config(args.config)
    if args.model:
        config["model"] = args.model
    if args.provider:
        config["provider"] = args.provider
    if args.workflow:
        config["workflow_mode"] = args.workflow

    # 创建 Agent
    agent = Agent(config)

    # 设置回调
    def on_tool(name, args, result):
        print(f"\n  🛠  {name}({json.dumps(args, ensure_ascii=False)[:100]})")
        if len(result) > 200:
            print(f"     → {result[:200]}...")
        else:
            print(f"     → {result}")

    agent.on_tool_call = on_tool

    # 交互模式
    if args.interactive or not args.message:
        print("🤖 ClaudeZ — 动态提示词驱动的 AI 智能体")
        print(f"   工作流: {agent.config['workflow_mode']}")
        print(f"   模型: {agent.config['model']}")
        print("   输入 /exit 退出, /mode <模式> 切换工作流")
        print()

        while True:
            try:
                user_input = input("你 > ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if not user_input:
                continue
            if user_input.lower() in ("/exit", "/quit", "/q"):
                break
            if user_input.startswith("/mode "):
                mode = user_input[6:].strip()
                agent.set_workflow_mode(mode)
                print(f"  切换到 {mode} 模式")
                continue
            if user_input.startswith("/"):
                print(f"  未知命令: {user_input}")
                continue

            print(f"\nClaudeZ > ", end="", flush=True)
            response = agent.run(user_input)
            print(response)
            print()

    # 单次模式
    else:
        message = " ".join(args.message)
        response = agent.run(message)
        print(response)


if __name__ == "__main__":
    main()
