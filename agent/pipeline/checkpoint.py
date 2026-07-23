"""Pipeline checkpoint — JSON 序列化/反序列化。"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from .types import PipelineTask, PipelinePhase


def save_checkpoint(task: PipelineTask, filepath: str) -> None:
    """将流水线任务序列化到 JSON 文件。"""
    try:
        dirname = os.path.dirname(filepath)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        data = {
            "id": task.id,
            "goal": task.goal,
            "phase": task.phase.value,
            "plan_text": task.plan_text,
            "execution_result": task.execution_result,
            "verification_report": task.verification_report,
            "verdict": task.verdict,
            "retry_count": task.retry_count,
            "max_retries": task.max_retries,
            "created_at": task.created_at,
            "completed_at": task.completed_at,
            "error": task.error,
            "metadata": task.metadata,
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        import logging
        logging.getLogger("claudez.pipeline").warning(
            "checkpoint_save_error path=%s %s", filepath, e
        )


def load_checkpoint(filepath: str) -> PipelineTask | None:
    """从 JSON 文件加载流水线任务。"""
    try:
        if not os.path.exists(filepath):
            return None
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        task = PipelineTask(
            id=data.get("id", ""),
            goal=data.get("goal", ""),
            phase=PipelinePhase(data.get("phase", "planning")),
            plan_text=data.get("plan_text", ""),
            execution_result=data.get("execution_result", ""),
            verification_report=data.get("verification_report", ""),
            verdict=data.get("verdict", ""),
            retry_count=data.get("retry_count", 0),
            max_retries=data.get("max_retries", 3),
            created_at=data.get("created_at", 0.0),
            completed_at=data.get("completed_at"),
            error=data.get("error", ""),
            metadata=data.get("metadata", {}),
        )
        return task
    except Exception as e:
        import logging
        logging.getLogger("claudez.pipeline").warning(
            "checkpoint_load_error path=%s %s", filepath, e
        )
        return None
