"""Pydantic 请求/响应模型。"""
from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    response: str
    phase: str = ""
    intent: str = ""
    decisions: int = 0
    turn_count: int = 0


class StatusResponse(BaseModel):
    running: bool = False
    phase: str = ""
    intent: str = ""
    goal: str = ""
    decisions: list[dict] = []
    decisions_count: int = 0
    modified_files: list[str] = []
    turn_count: int = 0
    workspace_files: int = 0
    project_type: str = ""
    cognition: bool = False
    execution: bool = False
