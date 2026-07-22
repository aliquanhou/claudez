"""tools/builtin — ClaudeZ 内置工具集。

包含文件操作、命令执行、网络请求等基础工具。
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

from .registry import tool


# ═══════════════════════════════════════════
# 文件操作
# ═══════════════════════════════════════════

@tool(category="file", timeout=30, is_readonly=True, is_concurrency_safe=True)
def read(file_path: str, head: int = 0, tail: int = 0) -> str:
    """读取文件内容。

    Args:
        file_path: 文件路径
        head: 只读取前 N 行（0 = 全部）
        tail: 只读取后 N 行（0 = 全部）
    """
    if not os.path.exists(file_path):
        return f"[错误] 文件不存在: {file_path}"

    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    if head > 0:
        lines = lines[:head]
    elif tail > 0:
        lines = lines[-tail:]

    return "".join(lines)


@tool(category="file", timeout=30, require_confirmation=True)
def write(file_path: str, content: str) -> str:
    """写入文件（自动创建目录）。

    Args:
        file_path: 文件路径
        content: 文件内容
    """
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return f"[完成] 已写入 {len(content)} 字节 → {file_path}"


@tool(category="file", timeout=30)
def edit(file_path: str, old_string: str, new_string: str) -> str:
    """编辑文件（替换文本，带 diff 预览）。

    Args:
        file_path: 文件路径
        old_string: 要替换的旧文本
        new_string: 新文本
    """
    if not os.path.exists(file_path):
        return f"[错误] 文件不存在: {file_path}"

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    if old_string not in content:
        return f"[错误] 未找到要替换的文本"

    # 计算行号用于预览
    lines = content.split("\n")
    old_lines = old_string.split("\n")
    line_num = 0
    for i, line in enumerate(lines):
        if old_string in line or (i < len(lines) - len(old_lines) + 1 and
                                   "\n".join(lines[i:i+len(old_lines)]) == old_string):
            line_num = i + 1
            break

    # 流式推送 diff 预览
    try:
        from .registry import get_stream_callback
        cb = get_stream_callback()
        if cb:
            cb(f"[diff] {file_path}:{line_num}")
            for ol in old_string.split("\n"):
                cb(f"  - {ol}")
            for nl in new_string.split("\n"):
                cb(f"  + {nl}")
    except Exception:
        pass

    content = content.replace(old_string, new_string, 1)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)

    return f"[完成] 已替换文本 → {file_path} (第 {line_num} 行)"


@tool(category="file", timeout=30, is_readonly=True, is_concurrency_safe=True)
def glob(pattern: str) -> str:
    """搜索文件（通配符模式）。

    Args:
        pattern: 通配符模式，如 **/*.py
    """
    import glob as glob_module
    matches = glob_module.glob(pattern, recursive=True)
    if not matches:
        return "(无匹配)"
    return "\n".join(sorted(matches)[:100])


@tool(category="file", timeout=30, is_readonly=True, is_concurrency_safe=True)
def grep(pattern: str, path: str = ".", glob_pattern: str = "*.py") -> str:
    """搜索文件内容。

    Args:
        pattern: 搜索模式（正则表达式）
        path: 搜索路径
        glob_pattern: 文件匹配模式
    """
    import re
    matches = []
    for f in Path(path).rglob(glob_pattern):
        if not f.is_file():
            continue
        try:
            content = f.read_text(encoding="utf-8", errors="replace")
            for i, line in enumerate(content.split("\n"), 1):
                if re.search(pattern, line):
                    matches.append(f"{f}:{i}: {line.strip()[:200]}")
        except Exception:
            pass

    if not matches:
        return "(无匹配)"
    return "\n".join(matches[:50])


# ═══════════════════════════════════════════
# 命令执行
# ═══════════════════════════════════════════

@tool(category="shell", timeout=60, require_confirmation=True)
def bash(command: str, timeout: int = 30) -> str:
    """执行 shell 命令（Windows CMD，支持流式输出）。

    如果当前线程注册了流式输出回调，会逐行推送 stdout/stderr。

    Args:
        command: 要执行的命令
        timeout: 超时秒数
    """
    import threading
    stream_cb = None
    try:
        from .registry import get_stream_callback
        stream_cb = get_stream_callback()
    except Exception:
        pass

    try:
        process = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        output_lines = []
        timer = threading.Timer(timeout, lambda: process.kill() if process.poll() is None else None)
        timer.start()

        def read_stream(stream, label):
            for line in iter(stream.readline, ""):
                if not line:
                    break
                output_lines.append(line)
                if stream_cb:
                    stream_cb(line.rstrip())
            stream.close()

        stdout_thread = threading.Thread(target=read_stream, args=(process.stdout, "stdout"), daemon=True)
        stderr_thread = threading.Thread(target=read_stream, args=(process.stderr, "stderr"), daemon=True)
        stdout_thread.start()
        stderr_thread.start()
        stdout_thread.join()
        stderr_thread.join()

        process.wait()
        timer.cancel()

        output = "".join(output_lines) if output_lines else "(无输出)"
        if process.returncode != 0:
            output += f"\n退出码: {process.returncode}"
        return output

    except subprocess.TimeoutExpired:
        return f"[超时] 命令执行超过 {timeout} 秒"
    except Exception as e:
        return f"[错误] {e}"


# ═══════════════════════════════════════════
# 网络请求
# ═══════════════════════════════════════════

@tool(category="web", timeout=30, is_readonly=True, is_concurrency_safe=True)
def web(url: str, method: str = "GET", data: str = "", headers: str = "") -> str:
    """发送 HTTP 请求。

    Args:
        url: 请求 URL
        method: HTTP 方法（GET/POST/PUT/DELETE）
        data: POST 数据（JSON 字符串）
        headers: 请求头（JSON 字符串）
    """
    import urllib.request
    import urllib.error

    req_headers = {}
    if headers:
        try:
            req_headers = json.loads(headers)
        except json.JSONDecodeError:
            return f"[错误] headers 格式错误，需要 JSON"

    req_data = None
    if data and method in ("POST", "PUT"):
        req_data = data.encode("utf-8")
        if "Content-Type" not in req_headers:
            req_headers["Content-Type"] = "application/json"

    try:
        req = urllib.request.Request(url, data=req_data, headers=req_headers, method=method)
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return f"状态: {resp.status}\n\n{body[:3000]}"
    except urllib.error.HTTPError as e:
        return f"HTTP 错误: {e.code} {e.reason}"
    except urllib.error.URLError as e:
        return f"URL 错误: {e.reason}"
    except Exception as e:
        return f"[错误] {e}"


@tool(category="web", timeout=30, is_readonly=True, is_concurrency_safe=True)
def web_search(query: str, max_results: int = 5) -> str:
    """搜索网络信息（使用 DuckDuckGo）。

    适合查找文档、错误信息、技术方案等。返回标题+链接+摘要。

    Args:
        query: 搜索关键词
        max_results: 最大结果数（1-10）
    """
    try:
        # duckduckgo_search >= 7.0 已改名为 ddgs
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS
    except ImportError:
        return "[错误] 需要安装: pip install duckduckgo_search"

    effective_max = max(1, min(max_results, 10))

    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=effective_max))

        if not results:
            return "(无搜索结果)"

        lines = []
        for i, r in enumerate(results, 1):
            title = r.get("title", "").strip()
            href = r.get("href", "").strip()
            body = r.get("body", "").strip()
            if not title:
                continue
            lines.append(f"{i}. {title}")
            lines.append(f"   {href}")
            if body:
                lines.append(f"   {body[:200]}")

        return "\n".join(lines) if lines else "(无搜索结果)"

    except Exception as e:
        return f"[搜索失败] {e}"


# ═══════════════════════════════════════════
# 系统信息
# ═══════════════════════════════════════════

@tool(category="system", timeout=10, is_readonly=True, is_concurrency_safe=True)
def process(action: str = "list", name: str = "") -> str:
    """进程管理（列出/查找进程）。

    Args:
        action: list（列出所有）| find（查找）
        name: 进程名（find 时使用）
    """
    import psutil

    if action == "list":
        processes = []
        for proc in psutil.process_iter(["pid", "name", "memory_info"]):
            try:
                mem = proc.info["memory_info"].rss / 1024 / 1024
                processes.append(f"{proc.info['pid']:>6}  {proc.info['name']:<30}  {mem:>6.1f} MB")
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return "\n".join(sorted(processes)[:50])

    elif action == "find":
        matches = []
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                if name.lower() in proc.info["name"].lower():
                    matches.append(f"{proc.info['pid']}  {proc.info['name']}")
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return "\n".join(matches) if matches else f"(未找到: {name})"

    return f"[错误] 未知操作: {action}"


@tool(category="system", timeout=10)
def monitor(action: str = "info", interval: int = 5, count: int = 10,
            name: str = "", path: str = "") -> str:
    """系统监控（CPU/内存/磁盘/进程/文件）。

    Args:
        action: info（基本信息）| watch（持续监控）| process（监控进程）| file（监控文件）
        interval: 监控间隔（秒，watch 时使用）
        count: 采样次数（watch 时使用）
        name: 进程名（process 时使用）
        path: 文件路径（file 时使用）
    """
    import psutil
    import time

    # ── 基本信息 ──
    if action == "info":
        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")

        # 负载
        load = psutil.getloadavg() if hasattr(psutil, 'getloadavg') else (0, 0, 0)

        # 网络
        net = psutil.net_io_counters()
        net_sent = net.bytes_sent / 1024 / 1024
        net_recv = net.bytes_recv / 1024 / 1024

        return (
            f"CPU: {cpu}% (负载: {load[0]:.1f}, {load[1]:.1f}, {load[2]:.1f})\n"
            f"内存: {mem.used/1024**3:.1f}GB / {mem.total/1024**3:.1f}GB ({mem.percent}%)\n"
            f"磁盘: {disk.used/1024**3:.1f}GB / {disk.total/1024**3:.1f}GB ({disk.percent}%)\n"
            f"网络: ↑{net_sent:.1f}MB ↓{net_recv:.1f}MB"
        )

    # ── 持续监控 ──
    if action == "watch":
        lines = [f"系统监控 (每 {interval} 秒, 共 {count} 次):"]
        lines.append(f"{'时间':>8}  {'CPU':>5}  {'内存':>6}  {'磁盘':>5}")

        for i in range(count):
            cpu = psutil.cpu_percent(interval=interval)
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage("/")
            timestamp = time.strftime("%H:%M:%S")
            lines.append(f"{timestamp}  {cpu:>4.1f}%  {mem.percent:>4.0f}%  {disk.percent:>4.0f}%")

        return "\n".join(lines)

    # ── 监控进程 ──
    if action == "process":
        if not name:
            return "[错误] 监控进程需要 name 参数"

        lines = [f"进程监控: {name} (每 {interval} 秒, 共 {count} 次):"]
        lines.append(f"{'时间':>8}  {'PID':>6}  {'CPU%':>6}  {'内存(MB)':>9}")

        for i in range(count):
            found = False
            for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info"]):
                try:
                    if name.lower() in proc.info["name"].lower():
                        mem_mb = proc.info["memory_info"].rss / 1024 / 1024
                        timestamp = time.strftime("%H:%M:%S")
                        lines.append(f"{timestamp}  {proc.info['pid']:>6}  {proc.info['cpu_percent'] or 0:>5.1f}%  {mem_mb:>8.1f}")
                        found = True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            if not found:
                lines.append(f"{time.strftime('%H:%M:%S')}  (进程未运行)")

            if i < count - 1:
                time.sleep(interval)

        return "\n".join(lines)

    # ── 监控文件 ──
    if action == "file":
        if not path:
            return "[错误] 监控文件需要 path 参数"
        if not os.path.exists(path):
            return f"[错误] 文件不存在: {path}"

        import hashlib

        lines = [f"文件监控: {path} (每 {interval} 秒, 共 {count} 次):"]
        lines.append(f"{'时间':>8}  {'大小':>8}  {'MD5':>32}")

        prev_hash = ""
        for i in range(count):
            try:
                size = os.path.getsize(path)
                with open(path, "rb") as f:
                    file_hash = hashlib.md5(f.read()).hexdigest()

                timestamp = time.strftime("%H:%M:%S")
                changed = " ← 已变更!" if prev_hash and file_hash != prev_hash else ""
                lines.append(f"{timestamp}  {size:>7}B  {file_hash}{changed}")
                prev_hash = file_hash
            except Exception as e:
                lines.append(f"{time.strftime('%H:%M:%S')}  [错误: {e}]")

            if i < count - 1:
                time.sleep(interval)

        return "\n".join(lines)

    return f"[错误] 未知操作: {action}"
