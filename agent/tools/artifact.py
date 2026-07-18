"""tools/artifact — 制品发布工具。

支持：
  - 创建制品（HTML/JS/CSS/图片/文本等）
  - 本地 HTTP 预览服务器
  - 制品列表/管理
  - 自动打开浏览器预览
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Any

from .registry import tool


# ── 制品存储 ──

ARTIFACT_DIR = Path(".artifacts")


@dataclass
class Artifact:
    """一个制品。"""
    id: str
    name: str
    type: str  # html | js | css | json | text | image | svg
    content: str
    created_at: float = 0.0
    size: int = 0

    def __post_init__(self):
        if not self.created_at:
            self.created_at = time.time()
        if not self.size:
            self.size = len(self.content)

    def save(self) -> Path:
        """保存制品到磁盘。"""
        ext_map = {
            "html": ".html", "js": ".js", "css": ".css",
            "json": ".json", "text": ".txt", "svg": ".svg",
            "image": ".png", "markdown": ".md",
        }
        ext = ext_map.get(self.type, ".txt")
        filepath = ARTIFACT_DIR / f"{self.id}{ext}"
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

        if self.type == "image":
            # 二进制写入
            import base64
            filepath.write_bytes(base64.b64decode(self.content))
        else:
            filepath.write_text(self.content, encoding="utf-8")

        return filepath

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "size": self.size,
            "created_at": self.created_at,
        }


class ArtifactManager:
    """制品管理器。"""

    def __init__(self):
        self._artifacts: dict[str, Artifact] = {}
        self._lock = threading.Lock()

    def create(self, name: str, type: str, content: str) -> Artifact:
        """创建制品。"""
        artifact_id = str(uuid.uuid4())[:8]
        artifact = Artifact(
            id=artifact_id,
            name=name,
            type=type,
            content=content,
        )
        with self._lock:
            self._artifacts[artifact_id] = artifact
        return artifact

    def get(self, artifact_id: str) -> Artifact | None:
        """获取制品。"""
        with self._lock:
            return self._artifacts.get(artifact_id)

    def list(self) -> list[dict]:
        """列出所有制品。"""
        with self._lock:
            return [a.to_dict() for a in self._artifacts.values()]

    def delete(self, artifact_id: str) -> bool:
        """删除制品。"""
        with self._lock:
            if artifact_id in self._artifacts:
                del self._artifacts[artifact_id]
                return True
            return False

    def clear(self):
        """清空所有制品。"""
        with self._lock:
            self._artifacts.clear()


_manager = ArtifactManager()


# ── HTTP 预览服务器 ──

_preview_server: HTTPServer | None = None
_preview_thread: threading.Thread | None = None
_preview_port: int = 0


class ArtifactHandler(SimpleHTTPRequestHandler):
    """制品预览 HTTP 处理器。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ARTIFACT_DIR), **kwargs)

    def log_message(self, format, *args):
        pass  # 静默日志


def _start_preview_server(port: int = 0) -> int:
    """启动预览服务器（后台线程）。"""
    global _preview_server, _preview_thread, _preview_port

    if _preview_server:
        return _preview_port

    if port == 0:
        # 找可用端口
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("", 0))
        port = s.getsockname()[1]
        s.close()

    _preview_server = HTTPServer(("127.0.0.1", port), ArtifactHandler)
    _preview_port = port

    _preview_thread = threading.Thread(
        target=_preview_server.serve_forever,
        daemon=True,
    )
    _preview_thread.start()

    return port


def _stop_preview_server():
    """停止预览服务器。"""
    global _preview_server, _preview_thread
    if _preview_server:
        _preview_server.shutdown()
        _preview_server = None
        _preview_thread = None


# ═══════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════

@tool(category="artifact", timeout=30)
def artifact(action: str = "create", name: str = "",
             type: str = "html", content: str = "",
             artifact_id: str = "", port: int = 0) -> str:
    """制品发布 — 创建、管理、预览制品。

    制品可以是 HTML/JS/CSS/JSON/Markdown 等。
    支持本地 HTTP 预览服务器。

    Args:
        action: 操作类型
            create — 创建制品（需 name + type + content）
            list — 列出所有制品
            show — 查看制品内容
            delete — 删除制品
            preview — 启动本地预览服务器
            stop — 停止预览服务器
            save — 保存制品到磁盘
        name: 制品名称（create 时使用）
        type: 制品类型（html | js | css | json | text | markdown | svg）
        content: 制品内容（create 时使用）
        artifact_id: 制品 ID
        port: 预览服务器端口（0 = 自动分配）
    """
    # ── 创建制品 ──
    if action == "create":
        if not name or not content:
            return "[错误] 创建需要 name 和 content 参数"

        valid_types = {"html", "js", "css", "json", "text", "markdown", "svg", "image"}
        if type not in valid_types:
            return f"[错误] 不支持的制品类型: {type}，支持: {', '.join(sorted(valid_types))}"

        artifact = _manager.create(name, type, content)
        filepath = artifact.save()

        return json.dumps({
            "artifact_id": artifact.id,
            "name": artifact.name,
            "type": artifact.type,
            "size": artifact.size,
            "file": str(filepath),
            "message": f"制品已创建: {artifact.name} ({artifact.type}, {artifact.size} 字节)",
        }, ensure_ascii=False)

    # ── 列出制品 ──
    if action == "list":
        artifacts = _manager.list()
        if not artifacts:
            return "(无制品)"

        lines = ["制品列表:"]
        for a in artifacts:
            created = datetime.fromtimestamp(a["created_at"]).strftime("%H:%M:%S")
            lines.append(f"  [{a['type']}] {a['id']}: {a['name']} ({a['size']}B, {created})")
        return "\n".join(lines)

    # ── 查看制品 ──
    if action == "show":
        if not artifact_id:
            return "[错误] 需要 artifact_id"
        artifact = _manager.get(artifact_id)
        if not artifact:
            return f"[错误] 未找到制品: {artifact_id}"

        preview = artifact.content[:2000]
        if len(artifact.content) > 2000:
            preview += f"\n... (共 {len(artifact.content)} 字符，仅显示前 2000)"

        return f"名称: {artifact.name}\n类型: {artifact.type}\n大小: {artifact.size} 字节\n\n{preview}"

    # ── 删除制品 ──
    if action == "delete":
        if not artifact_id:
            return "[错误] 需要 artifact_id"
        if _manager.delete(artifact_id):
            return f"[完成] 已删除制品: {artifact_id}"
        return f"[错误] 未找到制品: {artifact_id}"

    # ── 启动预览服务器 ──
    if action == "preview":
        actual_port = _start_preview_server(port)
        url = f"http://127.0.0.1:{actual_port}"

        # 尝试打开浏览器
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass

        return json.dumps({
            "url": url,
            "port": actual_port,
            "message": f"预览服务器已启动: {url}",
        }, ensure_ascii=False)

    # ── 停止预览服务器 ──
    if action == "stop":
        _stop_preview_server()
        return "[完成] 预览服务器已停止"

    # ── 保存到磁盘 ──
    if action == "save":
        if not artifact_id:
            return "[错误] 需要 artifact_id"
        artifact = _manager.get(artifact_id)
        if not artifact:
            return f"[错误] 未找到制品: {artifact_id}"
        filepath = artifact.save()
        return f"[完成] 已保存 → {filepath}"

    return f"[错误] 未知操作: {action}"
