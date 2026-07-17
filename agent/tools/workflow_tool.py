"""tools/workflow_tool — 工作流工具。

让 Agent 可以在对话中：
  - 创建多步骤工作流
  - 序列化/保存到磁盘
  - 从检查点恢复
  - 查询进度
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .registry import tool
from ..workflow import (
    WorkflowState, WorkflowStep, WorkflowSerializer, WorkflowResumer,
    create_workflow, get_workflow, list_workflows,
)


@tool(category="workflow", timeout=30)
def workflow(action: str = "create", title: str = "",
             steps: str = "", workflow_id: str = "",
             step_index: int = 0, step_status: str = "",
             step_result: str = "", filepath: str = "") -> str:
    """工作流管理 — 创建、执行、恢复多步骤工作流。

    工作流是一系列有序步骤，可以序列化保存、从检查点恢复。

    Args:
        action: 操作类型
            create — 创建工作流（需 title + steps）
            show — 查看工作流详情
            list — 列出所有工作流
            save — 保存到文件
            load — 从文件加载
            resume — 恢复执行未完成的工作流
            update_step — 更新步骤状态
            progress — 查看进度
        title: 工作流标题（create 时使用）
        steps: 步骤列表，每行一个步骤（create 时使用）
        workflow_id: 工作流 ID
        step_index: 步骤索引（update_step 时使用）
        step_status: 步骤状态（update_step 时使用）
        step_result: 步骤结果（update_step 时使用）
        filepath: 文件路径（save/load 时使用）
    """
    # ── 创建工作流 ──
    if action == "create":
        if not title or not steps:
            return "[错误] 创建需要 title 和 steps 参数"

        step_list = [s.strip() for s in steps.split("\n") if s.strip()]
        if not step_list:
            return "[错误] steps 不能为空"

        state = create_workflow(title, step_list)
        return json.dumps({
            "workflow_id": state.id,
            "title": state.title,
            "steps": len(state.steps),
            "message": f"工作流已创建 ({len(state.steps)} 步)",
        }, ensure_ascii=False)

    # ── 查看工作流 ──
    if action == "show":
        if not workflow_id:
            return "[错误] 需要 workflow_id"
        state = get_workflow(workflow_id)
        if not state:
            return f"[错误] 未找到工作流: {workflow_id}"
        return state.get_summary()

    # ── 列出所有工作流 ──
    if action == "list":
        workflows = list_workflows()
        if not workflows:
            return "(无活跃工作流)"
        lines = ["活跃工作流:"]
        for w in workflows:
            lines.append(f"  [{w['status']}] {w['id']}: {w['title']} ({w['progress']})")
        return "\n".join(lines)

    # ── 保存到文件 ──
    if action == "save":
        if not workflow_id:
            return "[错误] 需要 workflow_id"
        state = get_workflow(workflow_id)
        if not state:
            return f"[错误] 未找到工作流: {workflow_id}"

        save_path = filepath or f".workflows/{workflow_id}.json"
        path = WorkflowSerializer.save(state, save_path)
        return f"[完成] 工作流已保存 → {path}"

    # ── 从文件加载 ──
    if action == "load":
        if not filepath:
            return "[错误] 需要 filepath"
        if not os.path.exists(filepath):
            return f"[错误] 文件不存在: {filepath}"

        try:
            state = WorkflowSerializer.load(filepath)
            # 注册到活跃工作流
            from ..workflow import _active_workflows
            _active_workflows[state.id] = state
            return json.dumps({
                "workflow_id": state.id,
                "title": state.title,
                "status": state.status,
                "steps": len(state.steps),
                "current_step": state.current_step,
                "message": f"工作流已加载 ({len(state.steps)} 步, 当前第 {state.current_step} 步)",
            }, ensure_ascii=False)
        except Exception as e:
            return f"[错误] 加载失败: {e}"

    # ── 恢复执行 ──
    if action == "resume":
        if not workflow_id:
            return "[错误] 需要 workflow_id"
        state = get_workflow(workflow_id)
        if not state:
            return f"[错误] 未找到工作流: {workflow_id}"

        resumer = WorkflowResumer(state)
        remaining = resumer.get_remaining_steps()

        if not remaining:
            return "[完成] 工作流已全部完成，无需恢复"

        lines = [f"待恢复步骤 ({len(remaining)} 步):"]
        for s in remaining:
            lines.append(f"  [{s.index}] {s.description} ({s.status})")
        lines.append("")
        lines.append("使用 workflow action=update_step 逐步骤执行")

        return "\n".join(lines)

    # ── 更新步骤状态 ──
    if action == "update_step":
        if not workflow_id:
            return "[错误] 需要 workflow_id"
        state = get_workflow(workflow_id)
        if not state:
            return f"[错误] 未找到工作流: {workflow_id}"

        resumer = WorkflowResumer(state)

        if step_status == "running":
            resumer.mark_step_running(step_index)
            return f"[完成] 步骤 {step_index} 标记为运行中"
        elif step_status == "completed":
            resumer.mark_step_completed(step_index, step_result)
            # 自动保存检查点
            state.save_checkpoint()
            if resumer.is_complete():
                state.status = "completed"
                return f"[完成] 步骤 {step_index} 已完成！工作流全部完成 🎉"
            return f"[完成] 步骤 {step_index} 已完成 (进度: {resumer.get_progress()['percent']:.0f}%)"
        elif step_status == "failed":
            resumer.mark_step_failed(step_index, step_result)
            return f"[完成] 步骤 {step_index} 标记为失败"
        elif step_status == "skipped":
            resumer.mark_step_skipped(step_index)
            return f"[完成] 步骤 {step_index} 已跳过"
        else:
            return f"[错误] 未知状态: {step_status}"

    # ── 查看进度 ──
    if action == "progress":
        if not workflow_id:
            return "[错误] 需要 workflow_id"
        state = get_workflow(workflow_id)
        if not state:
            return f"[错误] 未找到工作流: {workflow_id}"

        resumer = WorkflowResumer(state)
        progress = resumer.get_progress()
        return json.dumps(progress, ensure_ascii=False)

    return f"[错误] 未知操作: {action}"
