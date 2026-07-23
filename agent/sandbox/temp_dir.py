"""TempDirSandbox — 临时目录执行沙箱。

在随机临时目录中执行文件操作，完成后自动销毁。
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

_log = logging.getLogger("claudez.sandbox")


class TempDirSandbox:
    """临时目录沙箱。

    所有文件操作被重定向到独立的临时目录中。
    上下文管理器自动清理。

    Usage:
        with TempDirSandbox() as sandbox:
            sandbox_path = sandbox.root
            # 所有文件操作都在 sandbox.root 内
        # 退出后自动删除
    """

    def __init__(self, prefix: str = "claudez_sandbox_"):
        self._prefix = prefix
        self._root: str | None = None

    @property
    def root(self) -> str:
        """获取沙箱根目录路径。"""
        if self._root is None:
            self._root = tempfile.mkdtemp(prefix=self._prefix)
        return self._root

    def resolve(self, path: str) -> str:
        """将相对路径解析为沙箱内绝对路径。"""
        full = os.path.normpath(os.path.join(self.root, path))
        if not full.startswith(os.path.normpath(self.root)):
            raise PermissionError(f"路径逃离沙箱边界: {path}")
        return full

    def cleanup(self) -> None:
        """手动清理沙箱（不等待 GC）。"""
        if self._root and os.path.exists(self._root):
            shutil.rmtree(self._root, ignore_errors=True)
            self._root = None
            _log.debug("sandbox_cleanup done")

    def __enter__(self) -> "TempDirSandbox":
        self.root  # 触发创建
        return self

    def __exit__(self, *args) -> None:
        self.cleanup()
