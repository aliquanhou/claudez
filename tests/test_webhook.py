"""测试 webhook 模块。"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.webhook import WebhookManager, WebhookTask


def test_create_task():
    """测试创建任务。"""
    manager = WebhookManager()
    task = manager.create_task("执行测试", source_ip="127.0.0.1")

    assert task.id
    assert task.prompt == "执行测试"
    assert task.status == "pending"
    assert task.source_ip == "127.0.0.1"

    print(f"✓ create_task: {task.id}")


def test_get_task():
    """测试获取任务。"""
    manager = WebhookManager()
    created = manager.create_task("测试任务")
    fetched = manager.get_task(created.id)

    assert fetched is not None
    assert fetched.prompt == "测试任务"

    # 不存在的 ID
    assert manager.get_task("nonexistent") is None

    print("✓ get_task: 通过")


def test_update_task():
    """测试更新任务状态。"""
    manager = WebhookManager()
    task = manager.create_task("更新测试")

    manager.update_task(task.id, status="running")
    assert manager.get_task(task.id).status == "running"

    manager.update_task(task.id, status="completed", result="成功")
    assert manager.get_task(task.id).status == "completed"
    assert manager.get_task(task.id).result == "成功"

    print("✓ update_task: 通过")


def test_list_tasks():
    """测试列出任务。"""
    manager = WebhookManager()
    manager.create_task("任务1")
    manager.create_task("任务2")
    manager.create_task("任务3")

    tasks = manager.list_tasks(10)
    assert len(tasks) >= 3

    print(f"✓ list_tasks: {len(tasks)} 个任务")


def test_api_key():
    """测试 API Key 验证。"""
    manager = WebhookManager()

    # 无 Key 时不验证
    assert manager.verify_key("") is True
    assert manager.verify_key("anything") is True

    # 设置 Key
    manager.set_api_key("my-secret-key")
    assert manager.verify_key("my-secret-key") is True
    assert manager.verify_key("wrong-key") is False

    print("✓ api_key: 通过")


def test_task_to_dict():
    """测试任务序列化。"""
    task = WebhookTask(
        id="test-123",
        prompt="测试序列化",
        status="completed",
        result="成功结果",
    )

    data = task.to_dict()
    assert data["id"] == "test-123"
    assert data["prompt"] == "测试序列化"
    assert data["status"] == "completed"
    assert data["result"] == "成功结果"

    print("✓ to_dict: 通过")


if __name__ == "__main__":
    test_create_task()
    test_get_task()
    test_update_task()
    test_list_tasks()
    test_api_key()
    test_task_to_dict()
    print("\n✅ 所有 webhook 测试通过!")
