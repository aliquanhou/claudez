"""测试 workflow 模块。"""

import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.workflow import (
    WorkflowState, WorkflowStep, WorkflowSerializer, WorkflowResumer,
    create_workflow, get_workflow, list_workflows,
)


def test_create_workflow():
    """测试创建工作流。"""
    state = create_workflow("测试工作流", ["步骤1", "步骤2", "步骤3"])
    assert state.title == "测试工作流"
    assert len(state.steps) == 3
    assert state.steps[0].description == "步骤1"
    assert state.steps[0].status == "pending"
    assert state.id
    print(f"✓ create_workflow: {state.id} ({len(state.steps)} 步)")


def test_workflow_step_status():
    """测试步骤状态管理。"""
    state = create_workflow("状态测试", ["A", "B", "C"])
    resumer = WorkflowResumer(state)

    # 标记运行中
    resumer.mark_step_running(0)
    assert state.steps[0].status == "running"
    assert state.current_step == 0

    # 标记完成
    resumer.mark_step_completed(0, "结果A")
    assert state.steps[0].status == "completed"
    assert state.steps[0].result == "结果A"

    # 标记失败
    resumer.mark_step_failed(1, "出错了")
    assert state.steps[1].status == "failed"
    assert state.steps[1].error == "出错了"

    # 标记跳过
    resumer.mark_step_skipped(2)
    assert state.steps[2].status == "skipped"

    print("✓ 步骤状态管理: 全部通过")


def test_workflow_resumer():
    """测试恢复执行器。"""
    state = create_workflow("恢复测试", ["X", "Y", "Z"])
    resumer = WorkflowResumer(state)

    # 获取下一步
    next_step = resumer.get_next_step()
    assert next_step is not None
    assert next_step.index == 0
    assert next_step.description == "X"

    # 完成所有步骤
    resumer.mark_step_completed(0)
    resumer.mark_step_completed(1)
    resumer.mark_step_completed(2)

    assert resumer.is_complete()
    assert resumer.get_next_step() is None

    # 进度
    progress = resumer.get_progress()
    assert progress["total"] == 3
    assert progress["completed"] == 3
    assert progress["percent"] == 100.0

    print("✓ WorkflowResumer: 全部通过")


def test_serialization():
    """测试序列化/反序列化。"""
    state = create_workflow("序列化测试", ["步骤1", "步骤2"])
    resumer = WorkflowResumer(state)
    resumer.mark_step_completed(0, "完成")

    # 序列化
    data = state.to_dict()
    assert data["title"] == "序列化测试"
    assert len(data["steps"]) == 2
    assert data["steps"][0]["status"] == "completed"

    # 反序列化
    restored = WorkflowState.from_dict(data)
    assert restored.title == "序列化测试"
    assert restored.steps[0].status == "completed"
    assert restored.steps[0].result == "完成"

    print("✓ 序列化/反序列化: 全部通过")


def test_file_save_load():
    """测试文件保存/加载。"""
    state = create_workflow("文件测试", ["A", "B"])
    resumer = WorkflowResumer(state)
    resumer.mark_step_completed(0, "OK")

    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = os.path.join(tmpdir, "test_workflow.json")

        # 保存
        saved = WorkflowSerializer.save(state, filepath)
        assert os.path.exists(saved)

        # 加载
        loaded = WorkflowSerializer.load(filepath)
        assert loaded.title == "文件测试"
        assert loaded.steps[0].status == "completed"

    print("✓ 文件保存/加载: 全部通过")


def test_checkpoint():
    """测试检查点。"""
    state = create_workflow("检查点测试", ["S1", "S2", "S3"])
    state.checkpoint_dir = tempfile.mkdtemp()

    resumer = WorkflowResumer(state)
    resumer.mark_step_completed(0, "完成")
    state.save_checkpoint()

    # 检查检查点文件
    import glob
    checkpoints = glob.glob(os.path.join(state.checkpoint_dir, f"workflow_{state.id}_*.json"))
    assert len(checkpoints) >= 1

    print(f"✓ 检查点: 已创建 {len(checkpoints)} 个文件")


def test_list_workflows():
    """测试列出工作流。"""
    create_workflow("WF1", ["A"])
    create_workflow("WF2", ["B", "C"])

    workflows = list_workflows()
    assert len(workflows) >= 2

    print(f"✓ list_workflows: {len(workflows)} 个工作流")


if __name__ == "__main__":
    test_create_workflow()
    test_workflow_step_status()
    test_workflow_resumer()
    test_serialization()
    test_file_save_load()
    test_checkpoint()
    test_list_workflows()
    print("\n✅ 所有 workflow 测试通过!")
