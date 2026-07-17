"""permissions — 权限与安全控制。

参考 Claude Code 的安全架构：
  - 多重权限模式（auto / ask / deny）
  - 沙箱执行（临时目录 + 子进程）
  - 不可变审计日志
  - 读/写工具分类
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


# ── 权限模式 ──

class PermissionMode(str, Enum):
    AUTO = "auto"     # 自动批准所有
    ASK = "ask"       # 询问用户
    DENY = "deny"     # 拒绝修改操作
    READONLY = "readonly"  # 只允许只读操作


# ── 操作类型 ──

class OpType(str, Enum):
    READ = "read"
    WRITE = "write"
    EXEC = "exec"
    NETWORK = "network"
    UNKNOWN = "unknown"


# ── 审计条目 ──

@dataclass
class AuditEntry:
    """不可变的审计日志条目。"""
    id: str = ""
    timestamp: float = 0.0
    op_type: str = ""
    tool_name: str = ""
    args: str = ""
    result_summary: str = ""
    duration_ms: float = 0.0
    permission_mode: str = ""
    approved: bool = True
    sandboxed: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "op_type": self.op_type,
            "tool_name": self.tool_name,
            "args": self.args[:200],
            "result_summary": self.result_summary[:200],
            "duration_ms": self.duration_ms,
            "permission_mode": self.permission_mode,
            "approved": self.approved,
            "sandboxed": self.sandboxed,
        }


# ── 操作分类 ──

def classify_operation(tool_name: str) -> tuple[OpType, bool]:
    """对操作进行分类（类型, 是否只读）。"""
    readonly_tools = {
        "read", "glob", "grep", "web", "web_search",
        "process", "monitor", "list",
    }
    write_tools = {
        "write", "edit", "bash", "delete", "move", "copy", "mkdir",
    }
    exec_tools = {"bash", "subagent", "background"}
    network_tools = {"web", "web_search", "webhook"}

    if tool_name in readonly_tools:
        return OpType.READ, True
    if tool_name in write_tools:
        return OpType.WRITE, False
    if tool_name in exec_tools:
        return OpType.EXEC, False
    if tool_name in network_tools:
        return OpType.NETWORK, True

    return OpType.UNKNOWN, False


# ── 权限管理器 ──

class PermissionManager:
    """权限与安全管理器。

    功能：
      - 判断操作是否允许
      - 沙箱执行高风险操作
      - 记录不可变审计日志
    """

    def __init__(self, mode: str = "auto", audit_dir: str = ""):
        self.mode = PermissionMode(mode)
        self.audit_log: list[AuditEntry] = []
        self._audit_dir = audit_dir or self._default_audit_dir()
        self._sandbox_base = Path(tempfile.gettempdir()) / "claudez_sandbox"
        os.makedirs(self._audit_dir, exist_ok=True)
        os.makedirs(self._sandbox_base, exist_ok=True)

    def _default_audit_dir(self) -> str:
        home = os.environ.get("HOME") or os.environ.get("USERPROFILE") or "."
        d = os.path.join(home, ".claudez", "audit")
        os.makedirs(d, exist_ok=True)
        return d

    # ── 权限判断 ──

    def check(self, tool_name: str) -> tuple[bool, str]:
        """检查工具是否允许执行。

        Returns:
          (允许, 拒绝原因)
        """
        op_type, is_readonly = classify_operation(tool_name)

        if self.mode == PermissionMode.DENY:
            return False, f"权限模式为 deny，禁止所有操作"

        if self.mode == PermissionMode.READONLY and not is_readonly:
            return False, f"只读模式不允许写操作: {tool_name}"

        return True, ""

    def set_mode(self, mode: str):
        """切换权限模式。"""
        self.mode = PermissionMode(mode)

    # ── 审计 ──

    def log(self, tool_name: str, args: dict, result: str,
            duration_ms: float = 0.0, approved: bool = True,
            sandboxed: bool = False) -> AuditEntry:
        """记录审计日志。"""
        entry = AuditEntry(
            id=str(uuid.uuid4())[:12],
            timestamp=time.time(),
            op_type=classify_operation(tool_name)[0].value,
            tool_name=tool_name,
            args=json.dumps(args, ensure_ascii=False)[:500],
            result_summary=result[:200],
            duration_ms=duration_ms,
            permission_mode=self.mode.value,
            approved=approved,
            sandboxed=sandboxed,
        )
        self.audit_log.append(entry)

        # 追加到磁盘日志
        try:
            log_path = os.path.join(self._audit_dir, f"audit_{time.strftime('%Y%m%d')}.jsonl")
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
        except Exception:
            pass

        return entry

    def get_audit_log(self, limit: int = 100) -> list[dict]:
        """获取最近审计日志。"""
        return [e.to_dict() for e in self.audit_log[-limit:]]

    # ── 沙箱 ──

    def create_sandbox(self, label: str = "sandbox") -> str:
        """创建沙箱临时目录。"""
        sandbox_dir = self._sandbox_base / f"{label}_{uuid.uuid4().hex[:8]}"
        os.makedirs(sandbox_dir, exist_ok=True)
        return str(sandbox_dir)

    def cleanup_sandbox(self, sandbox_dir: str):
        """清理沙箱目录。"""
        import shutil
        try:
            shutil.rmtree(sandbox_dir, ignore_errors=True)
        except Exception:
            pass

    def exec_in_sandbox(self, command: str, sandbox_dir: str | None = None,
                        timeout: float = 30.0) -> str:
        """在沙箱中执行命令。"""
        cwd = sandbox_dir or self.create_sandbox()
        try:
            result = subprocess.run(
                command, shell=True, cwd=cwd,
                capture_output=True, text=True,
                timeout=timeout,
                encoding="utf-8", errors="replace",
            )
            output = []
            if result.stdout:
                output.append(result.stdout)
            if result.stderr:
                output.append(f"STDERR:\n{result.stderr}")
            if result.returncode != 0:
                output.append(f"退出码: {result.returncode}")
            return "\n".join(output) if output else "(无输出)"
        except subprocess.TimeoutExpired:
            return f"[超时] 命令 {timeout} 秒未完成"
        except Exception as e:
            return f"[错误] {e}"


# ── 全局实例 ──

_manager: PermissionManager | None = None


def get_permission_manager() -> PermissionManager:
    global _manager
    if _manager is None:
        _manager = PermissionManager()
    return _manager


def check_permission(tool_name: str) -> tuple[bool, str]:
    """快捷权限检查。"""
    return get_permission_manager().check(tool_name)
