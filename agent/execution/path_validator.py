"""PathValidator — 文件路径安全校验。

职责：在执行文件操作前，校验目标路径是否在允许的工作区内。
Windows 环境下不做真正沙箱（无 seccomp），但防止手滑操作。

校验规则：
  1. 路径必须在 workspace_root 下
  2. 不允许访问黑名单目录 (.git, node_modules, __pycache__ 等)
  3. 不允许操作敏感文件类型 (.key, .pem, .crt)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


class PathValidator:
    """路径安全校验器。

    Usage:
        validator = PathValidator("/path/to/project")
        is_safe, reason = validator.validate("src/main.py")
        if not is_safe:
            print(f"Blocked: {reason}")
    """

    # 系统关键路径（大写用于 Windows）
    _BLOCKED_PATH_FRAGMENTS = [
        ".git", "node_modules", "__pycache__", ".venv", "venv", "env",
        ".mypy_cache", ".pytest_cache", ".ruff_cache",
        ".idea", ".vscode",
        "dist", "build", "target", "out",
        # Linux 系统路径
        "/etc", "/sys", "/proc", "/dev",
        "/boot", "/usr/lib", "/usr/bin", "/bin", "/sbin",
        "C:\\Windows", "C:\\System32", "C:\\Program Files",
        "C:\\ProgramData", "C:\\Recovery",
    ]

    _BLOCKED_EXTENSIONS = {
        ".key", ".pem", ".crt", ".p12", ".pfx",
        ".kdb", ".kdbx",
    }

    def __init__(self, workspace_root: str) -> None:
        self.workspace_root = Path(workspace_root).resolve()

    def validate(self, file_path: str) -> tuple[bool, str]:
        """校验路径是否安全。

        Returns:
            (is_safe, reason): is_safe=True 表示安全，reason 为空字符串；
                               否则 reason 包含拒绝原因。
        """
        if not file_path or not file_path.strip():
            return False, "路径为空"

        path = Path(file_path)

        # 1. 检查路径能否解析
        try:
            resolved = path.resolve()
        except (OSError, RuntimeError) as e:
            return False, f"路径解析失败: {e}"

        # 2. 检查是否在 workspace 范围内（相对路径 → 拼接 workspace）
        if not path.is_absolute():
            resolved = (self.workspace_root / path).resolve()

        try:
            resolved.relative_to(self.workspace_root)
        except ValueError:
            return False, f"路径不在工作区内: {file_path}"

        # 3. 检查黑名单路径
        path_str = str(resolved).replace("\\", "/").lower()
        for blocked in self._BLOCKED_PATH_FRAGMENTS:
            if blocked.lower() in path_str:
                return False, f"路径包含禁止目录: {blocked}"

        # 4. 检查文件扩展名
        ext = Path(file_path).suffix.lower()
        if ext in self._BLOCKED_EXTENSIONS:
            return False, f"禁止操作的文件类型: {ext}"

        return True, ""

    def validate_all(self, file_paths: list[str]) -> list[tuple[str, bool, str]]:
        """批量校验多个路径。

        Returns:
            [(file_path, is_safe, reason), ...]
        """
        return [(fp, *self.validate(fp)) for fp in file_paths]

    def filter_safe(self, file_paths: list[str]) -> list[str]:
        """返回安全路径的列表。"""
        return [fp for fp in file_paths if self.validate(fp)[0]]
