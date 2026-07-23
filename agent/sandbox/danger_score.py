"""DangerScore — 命令危险性评分引擎。

Hermes 风格威胁模式检测：
  - 文件系统破坏 (rm -rf, dd, mkfs, format)
  - 权限提升 (sudo, chmod 777, su)
  - 数据泄露 (curl/post to external, netcat)
  - 资源耗尽 (fork bomb, infinite loop)
  - 系统篡改 (passwd, /etc, /sys, /proc)

评分: 0-100, > 70 高风险
"""

from __future__ import annotations

import logging
import shlex
from typing import Any

_log = logging.getLogger("claudez.sandbox")

# 威胁模式: (pattern, weight, category)
_THREAT_PATTERNS: list[tuple[str, int, str]] = [
    # ── 文件系统破坏 ──
    ("rm -rf /", 100, "fs_destroy"),
    ("rm -rf --no-preserve-root", 100, "fs_destroy"),
    ("dd if=/dev/zero of=", 90, "fs_destroy"),
    ("mkfs.", 90, "fs_destroy"),
    ("format", 85, "fs_destroy"),
    (":(){ :|:& };:", 100, "fork_bomb"),

    # ── 权限提升 ──
    ("sudo ", 40, "privilege_escalation"),
    ("chmod 777", 50, "permission_abuse"),
    ("chown ", 30, "permission_change"),
    ("passwd", 60, "system_tamper"),
    ("su ", 50, "privilege_escalation"),

    # ── 数据泄露 ──
    ("curl -X POST", 40, "data_exfil"),
    ("nc -e", 80, "data_exfil"),
    ("netcat -e", 80, "data_exfil"),
    ("telnet", 30, "data_exfil"),
    ("ncat", 40, "data_exfil"),

    # ── 系统篡改 ──
    (">/etc/", 80, "system_tamper"),
    (">/sys/", 80, "system_tamper"),
    (">/proc/", 80, "system_tamper"),
    ("/dev/", 30, "device_access"),
    ("dd if=/dev/sda", 90, "device_access"),
    ("mount", 40, "system_tamper"),
    ("fdisk", 60, "system_tamper"),

    # ── 资源滥用 ──
    ("while true", 20, "resource_abuse"),
    (":(){", 100, "fork_bomb"),
    ("fork", 30, "resource_abuse"),
    ("wget ", 20, "network_egress"),
    ("iptables", 50, "network_tamper"),
]


class DangerScore:
    """命令危险性评分器。

    Usage:
        score = DangerScore.score("rm -rf /")
        if score > 70:
            print("High risk!")
    """

    @staticmethod
    def score(command: str) -> int:
        """评分一条命令。返回 0-100 的分数。"""
        lower = command.lower()
        max_weight = 0

        for pattern, weight, category in _THREAT_PATTERNS:
            if pattern in lower:
                max_weight = max(max_weight, weight)
                _log.debug("danger_match pattern=%s weight=%d cmd=%s", category, weight, command[:80])

        return max_weight

    @staticmethod
    def get_risk_level(score: int) -> str:
        if score >= 80:
            return "CRITICAL"
        if score >= 50:
            return "HIGH"
        if score >= 20:
            return "MEDIUM"
        return "LOW"

    @staticmethod
    def get_risk_advice(score: int, command: str) -> str:
        level = DangerScore.get_risk_level(score)
        if level == "CRITICAL":
            return f"危险命令被拦截: `{command[:100]}` — 此操作可能导致系统损坏!"
        if level == "HIGH":
            return f"高风险命令: `{command[:100]}` — 确认此操作是否必要。"
        if level == "MEDIUM":
            return f"注意: `{command[:100]}` — 可能有潜在风险。"
        return ""


def score_command(command: str) -> int:
    """便捷函数：返回命令危险性评分。"""
    return DangerScore.score(command)
