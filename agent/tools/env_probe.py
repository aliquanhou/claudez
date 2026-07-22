"""env_probe — 主机工具链探测。

探测本机安装的开发工具链（Python/Node/Java/Docker/Git 等），
让 Agent 能感知用户环境中有哪些工具可用。

使用 `where` (Windows) / `which` (Unix) + `--version` 组合命令。
结果缓存 60 秒，避免每次对话重扫。
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any


# ── 工具探测规则 ──

TOOL_PROBES: list[dict] = [
    {"name": "python", "ver_flag": "--version", "check": "python --version"},
    {"name": "pip", "ver_flag": "--version", "check": "pip --version"},
    {"name": "node", "ver_flag": "--version", "check": "node --version"},
    {"name": "npm", "ver_flag": "--version", "check": "npm --version"},
    {"name": "git", "ver_flag": "--version", "check": "git --version"},
    {"name": "docker", "ver_flag": "--version", "check": "docker --version"},
    {"name": "java", "ver_flag": "-version", "check": "java -version"},
    {"name": "go", "ver_flag": "version", "check": "go version"},
    {"name": "rustc", "ver_flag": "--version", "check": "rustc --version"},
    {"name": "cargo", "ver_flag": "--version", "check": "cargo --version"},
    {"name": "gcc", "ver_flag": "--version", "check": "gcc --version"},
    {"name": "cmake", "ver_flag": "--version", "check": "cmake --version"},
    {"name": "make", "ver_flag": "--version", "check": "make --version"},
    {"name": "curl", "ver_flag": "--version", "check": "curl --version"},
    {"name": "ssh", "ver_flag": "-V", "check": "ssh -V"},
    {"name": "dotnet", "ver_flag": "--version", "check": "dotnet --version"},
    {"name": "php", "ver_flag": "--version", "check": "php --version"},
    {"name": "ruby", "ver_flag": "--version", "check": "ruby --version"},
    {"name": "perl", "ver_flag": "--version", "check": "perl --version"},
    {"name": "latex", "ver_flag": "--version", "check": "latex --version"},
]


def _run(cmd: str) -> str:
    """执行命令并返回 stdout+stderr。"""
    try:
        proc = subprocess.run(
            cmd.split(),
            capture_output=True,
            text=True,
            timeout=10,
            errors="replace",
        )
        return (proc.stdout or "") + (proc.stderr or "")
    except (subprocess.TimeoutExpired, FileNotFoundError, PermissionError, OSError):
        return ""
    except Exception:
        return ""


def _extract_version(output: str) -> str:
    """从命令输出中提取版本号。"""
    output = output.strip().split("\n")[0] if output.strip() else ""
    # 去掉常见前缀
    for prefix in ["Python ", "Node.js ", "nodejs ", "v"]:
        if output.lower().startswith(prefix.lower()):
            output = output[len(prefix):]
    return output[:60]


@dataclass
class ProbeResult:
    """探测结果快照。"""
    tools: dict[str, dict] = field(default_factory=dict)
    scanned_at: float = 0.0
    os: str = ""
    total_available: int = 0


class EnvProbe:
    """主机工具链探测（缓存 60 秒）。"""

    CACHE_SECONDS = 60

    def __init__(self):
        self._cache: ProbeResult | None = None

    def probe(self, force: bool = False) -> ProbeResult:
        """执行探测（带缓存）。"""
        now = time.time()
        if not force and self._cache and (now - self._cache.scanned_at) < self.CACHE_SECONDS:
            return self._cache

        os_name = platform.system()
        results: dict[str, dict] = {}

        for probe in TOOL_PROBES:
            name = probe["name"]
            ver_flag = probe["ver_flag"]
            cmd = probe["check"]

            output = _run(cmd)
            available = bool(output.strip())

            version = ""
            if available:
                version = _extract_version(output)

            # 获取路径
            tool_path = ""
            if available:
                # Use where/which to find path
                try:
                    which_cmd = "where" if os_name == "Windows" else "which"
                    path_result = subprocess.run(
                        [which_cmd, name] if which_cmd == "which" else [which_cmd, f"{name}.exe", name],
                        capture_output=True, text=True, timeout=5, errors="replace",
                    )
                    if path_result.returncode == 0:
                        tool_path = path_result.stdout.strip().split("\n")[0]
                except Exception:
                    pass

            results[name] = {
                "name": name,
                "version": version,
                "path": tool_path,
                "available": available,
            }

        total_available = sum(1 for t in results.values() if t["available"])

        self._cache = ProbeResult(
            tools=results,
            scanned_at=now,
            os=os_name,
            total_available=total_available,
        )
        return self._cache

    def get_summary(self) -> str:
        """生成摘要文本（用于注入 system prompt）。"""
        result = self.probe()
        available = [t for t in result.tools.values() if t["available"]]
        if not available:
            return ""
        lines = ["\n[宿主环境] 本机已安装的工具链："]
        for t in available:
            version = f" {t['version']}" if t["version"] else ""
            path = f" ({t['path']})" if t["path"] else ""
            lines.append(f"  - {t['name']}{version}{path}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        """序列化为字典（用于 API 响应）。"""
        result = self.probe()
        return {
            "os": result.os,
            "total_available": result.total_available,
            "scanned_at": result.scanned_at,
            "tools": result.tools,
            "summary": self.get_summary(),
        }


# ── 全局实例 ──

_INSTANCE: EnvProbe | None = None


def get_env_probe() -> EnvProbe:
    """获取全局环境探测实例。"""
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = EnvProbe()
    return _INSTANCE
