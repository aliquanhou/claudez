"""请求链路追踪 — 每个桥接点写文件日志，永不丢失、永不缓冲。"""
import os, time, threading

_TRACE_FILE = os.environ.get("FORGEX_TRACE", r"D:\claude\claudez\_trace.log")
_lock = threading.Lock()
# 每次启动清空
with _lock:
    try:
        with open(_TRACE_FILE, "w", encoding="utf-8") as f:
            f.write(f"=== ForgeX Trace Started at {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
    except Exception:
        pass

def T(label: str, detail: str = ""):
    """写一行追踪日志到文件（线程安全、即时 flush）。"""
    ts = time.time()
    tid = threading.get_ident()
    try:
        with _lock:
            with open(_TRACE_FILE, "a", encoding="utf-8") as f:
                f.write(f"[{ts:.3f}] [T:{tid}] {label} {detail}\n")
    except Exception:
        pass
