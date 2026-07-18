"""host_tools/plugin.py — 主机工具链深度探测 + 自动挂载。

设计原则：探明即挂载。
  - 每次加载时自动探测本机全部开发工具
  - 探测到的工具自动注册到 ToolRegistry，Agent 可直接调用
  - 用户可屏蔽单工具（屏蔽不注册，保留缓存，可恢复）
  - 重新探测时新发现的工具自动挂载
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path


class Plugin:
    def __init__(self):
        self._cache: dict[str, dict] = {}
        self._probe_rules: list[dict] = []
        self._probed = False
        self._masked: set[str] = set()
        self._mask_path = Path(__file__).parent / ".tool_mask.json"
        self._logs: list[dict] = []

    def get_debug_logs(self) -> list[dict]:
        return list(self._logs)

    def _log(self, event: str, msg: str, detail: dict | None = None):
        self._logs.append({
            "ts": time.strftime("%H:%M:%S"),
            "event": event,
            "msg": msg,
            "detail": detail or {},
        })
        print(f"[插件] {event}: {msg}", file=sys.stderr)

    def on_load(self, ctx) -> bool:
        self._load_mask()
        self._load_probe_rules()
        self._log("LOAD", f"plugin loaded, {len(self._probe_rules)} probe rules")
        if not self._probe_rules:
            self._log("WARN", "probe rules empty! check manifest.json")
        self.probe()
        return True

    def on_unload(self):
        self._cache.clear()
        self._probed = False
        self._save_mask()

    def _load_probe_rules(self):
        manifest_path = Path(__file__).parent / "manifest.json"
        if not manifest_path.exists():
            self._log("ERR", f"manifest.json not found: {manifest_path}")
            return
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            rules = manifest.get("probes", [])
            if not rules:
                rules = manifest.get("tools", [])
                self._log("WARN", "no probes field, using deprecated tools field")
            self._probe_rules = rules
            self._log("RULE", f"loaded {len(rules)} probe rules")
        except Exception as e:
            self._log("ERR", f"manifest parse failed: {e}")

    def probe(self, force: bool = False) -> list[dict]:
        self._log("PROBE", "starting probe" if force or not self._probed else "using cache")
        if self._probed and not force:
            return self._get_available_tools()

        self._cache = {}
        self._probed = True

        sdk_root = self._get_android_sdk_root()
        java_home = self._get_java_home()
        gradle_home = self._get_gradle_home()
        flutter_root = self._get_flutter_root()
        npm_prefix = self._get_npm_prefix()

        self._log("ENV", f"SDK={bool(sdk_root)} JAVA={bool(java_home)} GRADLE={bool(gradle_home)} FLUTTER={bool(flutter_root)}")

        for rule in self._probe_rules:
            name = rule["name"]
            result = self._probe_single(rule, sdk_root, java_home, gradle_home, flutter_root, npm_prefix)
            if result:
                self._cache[name] = result
                self._log("FOUND", f"{name} -> {result['exec_path']} v{result['version']}")
            else:
                self._log("SKIP", f"{name} not found")

        self._log("DONE", f"probe done: {len(self._cache)} tools ready, {len(self._masked)} masked")
        return self._get_available_tools()

    def _probe_single(self, rule, sdk_root, java_home, gradle_home, flutter_root, npm_prefix):
        name = rule["name"]
        exec_name = rule.get("exec_name", name)
        flags = list(rule.get("version_args", ["--version"]))
        regex = rule.get("version_regex", r"(\d+\.\d+\.\d+)")
        exec_path = self._resolve_exec_path(name, exec_name, sdk_root, java_home, gradle_home, flutter_root, npm_prefix)
        if not exec_path:
            return None
        version = self._get_version(exec_path, flags, regex) or "installed"
        return {"name": name, "exec_path": exec_path, "version": version, "available": True}

    def _resolve_exec_path(self, name, exec_name, sdk_root, java_home, gradle_home, flutter_root, npm_prefix):
        if name in ("adb",) and sdk_root:
            exe = self._find_exe(Path(sdk_root) / "platform-tools", exec_name)
            if exe: return exe
        if name in ("sdkmanager", "avdmanager") and sdk_root:
            cl = self._find_latest_dir(Path(sdk_root) / "cmdline-tools")
            exe = self._find_exe(cl / "bin", exec_name)
            if exe: return exe
        if name in ("aapt2", "apksigner", "zipalign") and sdk_root:
            bt = self._find_latest_dir(Path(sdk_root) / "build-tools")
            exe = self._find_exe(bt, exec_name)
            if exe: return exe
        if name in ("jarsigner", "keytool"):
            for home in ([java_home] if java_home else []) + (["D:\\Android\\Android Studio\\jbr"] if Path("D:\\Android\\Android Studio\\jbr").exists() else []):
                if not home: continue
                exe = self._find_exe(Path(home) / "bin", exec_name)
                if exe: return exe
        if name == "gradle":
            if gradle_home:
                exe = self._find_exe(Path(gradle_home) / "bin", exec_name)
                if exe: return exe
            for c in ["gradle.bat", "gradle"]:
                p = shutil.which(c)
                if p: return p
            for d in Path("C:\\gradle").glob("gradle*"):
                exe = self._find_exe(d / "bin", exec_name)
                if exe: return exe
            return None
        if name == "flutter":
            if flutter_root:
                exe = self._find_exe(Path(flutter_root) / "bin", exec_name)
                if exe: return exe
            path = shutil.which("flutter.bat") or shutil.which("flutter")
            if path: return path
            for p in [Path("D:/flutter"), Path("C:/flutter")]:
                if p.exists():
                    exe = self._find_exe(p / "bin", exec_name)
                    if exe: return exe
            return None
        if name == "dart":
            path = shutil.which("dart.exe") or shutil.which("dart")
            if path: return path
            fpath = self._resolve_exec_path("flutter", "flutter", sdk_root, java_home, gradle_home, flutter_root, npm_prefix)
            if fpath:
                return self._find_exe(Path(fpath).parent, "dart")
            return None
        if name == "cordova":
            for c in ["cordova.cmd", "cordova.bat", "cordova"]:
                p = shutil.which(c)
                if p:
                    ver = self._try_get_version(p, ["--version"])
                    if ver: return p
            if npm_prefix:
                exe = self._find_exe(Path(npm_prefix), "cordova") or self._find_exe(Path(npm_prefix) / "bin", "cordova")
                if exe: return exe
            for d in [Path("D:/npm-global"), Path(os.environ.get("APPDATA", "")) / "npm"]:
                if d.exists():
                    exe = self._find_exe(d, exec_name)
                    if exe: return exe
            return None
        if name == "node":
            path = shutil.which("node.exe") or shutil.which("node")
            if path: return path
            for d in [Path("C:/Program Files/nodejs"), Path(os.environ.get("ProgramFiles", "")) / "nodejs"]:
                if d.exists():
                    exe = self._find_exe(d, "node")
                    if exe: return exe
            return None
        if name == "npm":
            path = shutil.which("npm.cmd") or shutil.which("npm")
            if path: return path
            for d in [Path("C:/Program Files/nodejs"), Path(os.environ.get("ProgramFiles", "")) / "nodejs"]:
                if d.exists():
                    exe = self._find_exe(d, "npm")
                    if exe: return exe
            return None
        if name == "python":
            for c in ["python3", "python"]:
                p = shutil.which(c)
                if p: return p
            for p in [Path(sys.prefix) / "python.exe", Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python" / "python.exe"]:
                if p.exists(): return str(p)
            return None
        if name == "pip":
            for c in ["pip3", "pip"]:
                p = shutil.which(c)
                if p: return p
            py = self._resolve_exec_path("python", "python", sdk_root, java_home, gradle_home, flutter_root, npm_prefix)
            if py:
                return self._find_exe(Path(py).parent, "pip")
            return None
        if name == "git":
            path = shutil.which("git")
            if path: return path
            for p in [Path("C:/Program Files/Git"), Path("D:/Program Files/Git")]:
                exe = self._find_exe(p / "bin", "git")
                if exe: return exe
            return None
        if name == "curl":
            path = shutil.which("curl")
            if path: return path
            git = self._resolve_exec_path("git", "git", sdk_root, java_home, gradle_home, flutter_root, npm_prefix)
            if git:
                gd = Path(git).parent
                exe = self._find_exe(gd, "curl")
                if exe: return exe
                for d in [gd.parent / "mingw64" / "bin", gd.parent / "usr" / "bin"]:
                    exe = self._find_exe(d, "curl")
                    if exe: return exe
            return None
        path = shutil.which(exec_name)
        return path

    # ── 工具列表 ──

    def get_tools(self) -> list[dict]:
        self.probe()
        tools = []
        for name, info in self._cache.items():
            if not info.get("available") or name in self._masked:
                continue
            meta = self._get_tool_meta(name)
            tools.append({
                "name": name, "display_name": meta.get("display_name", name),
                "version": info.get("version", ""), "category": meta.get("category", "command"),
                "icon": meta.get("icon", "🔧"), "description": meta.get("description", ""),
                "exec_path": info.get("exec_path", ""), "source": "host",
            })
        self._log("GET_TOOLS", f"returning {len(tools)} tools ({len(self._masked)} masked)")
        return tools

    def get_all_probed(self) -> list[dict]:
        self.probe()
        result = []
        for name, info in self._cache.items():
            if not info.get("available"): continue
            meta = self._get_tool_meta(name)
            result.append({
                "name": name, "display_name": meta.get("display_name", name),
                "version": info.get("version", ""), "category": meta.get("category", "command"),
                "icon": meta.get("icon", "🔧"), "description": meta.get("description", ""),
                "exec_path": info.get("exec_path", ""), "source": "host",
                "plugin_id": "com.claudez.plugins.host-tools",
                "masked": name in self._masked,
            })
        return result

    def execute(self, tool_id, args, ctx):
        info = self._cache.get(tool_id)
        if not info or not info.get("available"):
            return {"error": f"tool {tool_id} not found"}
        if tool_id in self._masked:
            return {"error": f"tool {tool_id} is masked"}
        exec_path = info.get("exec_path", tool_id)
        cmd = [exec_path] + (args if args else [])
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, encoding="utf-8", errors="replace")
            out = result.stdout
            if result.stderr: out += "\n" + result.stderr
            return {"output": out.strip() or "(no output)", "returncode": result.returncode, "command": shlex.join(cmd)}
        except subprocess.TimeoutExpired:
            return {"error": f"timeout: {shlex.join(cmd)}"}
        except Exception as e:
            return {"error": str(e)}

    # ── 屏蔽/恢复 ──

    def mask_tool(self, tool_name: str) -> bool:
        if tool_name in self._cache:
            self._masked.add(tool_name)
            self._save_mask()
            self._log("MASK", f"masked {tool_name}")
            return True
        return False

    def unmask_tool(self, tool_name: str) -> bool:
        self._masked.discard(tool_name)
        self._save_mask()
        self._log("UNMASK", f"unmasked {tool_name}")
        return True

    def is_masked(self, tool_name: str) -> bool:
        return tool_name in self._masked

    # ── 辅助 ──

    def _get_available_tools(self):
        return [v for v in self._cache.values() if v.get("available")]

    def _get_version(self, exec_path, flags, regex):
        try:
            cmd = [exec_path] + flags
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10, encoding="utf-8", errors="replace")
            m = re.search(regex, (result.stdout + result.stderr).strip())
            return m.group(1) if m else None
        except Exception:
            return None

    def _try_get_version(self, exec_path, flags):
        for r in [r"(\d+\.\d+\.\d+)", r"(\d+\.\d+)", r"v(\d+\.\d+\.\d+)"]:
            v = self._get_version(exec_path, flags, r)
            if v: return v
        return "installed"

    def _get_android_sdk_root(self):
        for var in ["ANDROID_HOME", "ANDROID_SDK_ROOT"]:
            val = os.environ.get(var, "").strip()
            if val and Path(val).exists(): return val
        for p in [Path("D:/Android/Sdk"), Path("C:/Android/Sdk")]:
            if p.exists(): return str(p)
        return None

    def _get_java_home(self):
        val = os.environ.get("JAVA_HOME", "").strip()
        if val and Path(val).exists(): return val
        java = shutil.which("java")
        if java:
            try:
                jh = str(Path(java).resolve().parent.parent)
                if (Path(jh) / "bin" / "javac").exists(): return jh
                for jdk in Path(jh).parent.glob("jdk-*"):
                    if (jdk / "bin" / "javac").exists(): return str(jdk)
            except Exception: pass
        return None

    def _get_gradle_home(self):
        val = os.environ.get("GRADLE_HOME", "").strip()
        if val and Path(val).exists(): return val
        return None

    def _get_flutter_root(self):
        val = os.environ.get("FLUTTER_ROOT", "") or os.environ.get("FLUTTER_HOME", "")
        if val.strip() and Path(val.strip()).exists(): return val.strip()
        return None

    def _get_npm_prefix(self):
        try:
            npm = shutil.which("npm.cmd") or shutil.which("npm")
            if npm:
                r = subprocess.run([npm, "prefix", "-g"], capture_output=True, text=True, timeout=5)
                if r.stdout.strip() and Path(r.stdout.strip()).exists(): return r.stdout.strip()
            appdata = os.environ.get("APPDATA", "")
            if appdata:
                p = Path(appdata) / "npm"
                if p.exists(): return str(p)
        except Exception: pass
        return None

    def _find_exe(self, d, name):
        if not d or not d.exists(): return None
        # Windows: 优先 .exe / .bat / .cmd，最后才是无扩展名
        exts = [".exe", ".bat", ".cmd", ""]
        for ext in exts:
            if (d / (name + ext)).exists():
                return str(d / (name + ext))
        return None

    def _find_latest_dir(self, base):
        if not base.exists(): return base
        dirs = [d for d in base.iterdir() if d.is_dir()]
        return sorted(dirs, key=lambda d: d.name, reverse=True)[0] if dirs else base

    def _load_mask(self):
        try:
            if self._mask_path.exists():
                self._masked = set(json.loads(self._mask_path.read_text("utf-8")).get("masked", []))
                self._log("MASK", f"loaded mask list: {self._masked}")
        except Exception:
            self._masked = set()

    def _save_mask(self):
        try:
            self._mask_path.write_text(json.dumps({"masked": sorted(self._masked)}, ensure_ascii=False), encoding="utf-8")
        except IOError: pass

    def _get_tool_meta(self, name):
        for r in self._probe_rules:
            if r.get("name") == name:
                return r
        return {"display_name": name, "category": "command", "icon": "🔧"}
