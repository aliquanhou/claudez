"""plugin_manager — ClaudeZ 插件管理系统（安全增强版）。

支持从多个目录发现、加载、卸载插件。
每个插件是一个目录，包含 manifest.json 和 plugin.py。

安全设计：
  - 三档信任等级：BUILTIN（全信任）> USER（中等）> COMMUNITY（受限）
  - Manifest 必填字段校验（id/name/version）
  - 路径穿越防护
  - Community 插件导入白名单（防止恶意代码执行）
  - 临时模块导入隔离（避免污染 sys.modules）

目录结构:
  ~/.claudez/plugins/
    ├── builtin/       # 内置插件（随 Agent 发布，全信任）
    ├── community/     # 社区插件（用户安装，受限模式）
    └── user/          # 用户自定义插件（中等信任）
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import logging
import os
import re
import sys
import threading
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable

_log = logging.getLogger("claudez.plugins")

# 默认插件搜索路径
DEFAULT_PLUGIN_DIRS = [
    # 内置插件路径（项目内）
    os.path.join(os.path.dirname(__file__), "plugins"),
    # 用户插件路径（~/.claudez/plugins/）
    os.path.expanduser("~/.claudez/plugins/builtin"),
    os.path.expanduser("~/.claudez/plugins/community"),
    os.path.expanduser("~/.claudez/plugins/user"),
]

# ── 信任等级 ──

class PluginTrustLevel(str, Enum):
    """插件信任等级。"""
    BUILTIN = "builtin"       # 随 Agent 发布，全信任
    USER = "user"             # 用户自定义，中等信任
    COMMUNITY = "community"   # 社区插件，受限模式

# ── Manifest 必填字段 ──

REQUIRED_MANIFEST_FIELDS = {"id", "name", "version"}
COMMUNITY_ALLOWED_IMPORTS = {
    # Python 标准库
    "json", "os", "pathlib", "subprocess", "sys", "re", "time",
    "math", "random", "collections", "itertools", "functools",
    "typing", "dataclasses", "enum", "hashlib", "uuid", "tempfile",
    "shutil", "platform", "textwrap",
    # ClaudeZ 公共接口
    "agent.plugins", "agent.tools",
}
"""Community 插件允许导入的模块白名单。

BUILTIN 和 USER 插件不受此限制。"""


# ── 插件信息 ──

@dataclass
class PluginInfo:
    """插件元数据。"""
    id: str                          # 唯一标识，如 "com.claudez.plugins.nodejs"
    name: str                        # 显示名称
    version: str                     # 版本号
    author: str = "Unknown"          # 作者
    description: str = ""            # 描述
    path: Path | None = None         # 插件目录路径
    manifest: dict = field(default_factory=dict)  # manifest.json 原始内容
    category: str = "general"        # 工具分类（file/command/network/system 等）
    icon: str = "🧩"                  # 图标
    enabled: bool = False            # 是否已启用
    tools: list[dict] = field(default_factory=list)  # 本插件提供的工具列表
    instance: Any = None             # 插件实例（plugin.py 导出的 Plugin 类实例）
    source: str = "builtin"          # 来源: builtin | community | user

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "author": self.author,
            "description": self.description,
            "category": self.category,
            "icon": self.icon,
            "enabled": self.enabled,
            "source": self.source,
            "tools": self.tools,
        }


# ── 插件基类 ──

class PluginBase:
    """所有插件必须继承的基类。

    子类需实现:
      - on_load(ctx) -> bool   : 插件加载时的初始化（返回 False 表示加载失败）
      - get_tools() -> list    : 返回本插件提供的工具列表
      - execute(tool_id, args, ctx) -> dict : 执行指定工具
    可选实现:
      - on_unload()            : 插件卸载时的清理
      - get_config_schema()    : 插件配置 JSON Schema
    """

    def on_load(self, ctx: "PluginContext") -> bool:
        """插件加载时调用。返回 False 表示加载失败。"""
        return True

    def on_unload(self):
        """插件卸载时调用。"""
        pass

    def get_tools(self) -> list[dict]:
        """返回本插件提供的工具列表。

        每个工具格式:
        {
            "name": "node",
            "display_name": "Node.js",
            "version": "v20.11.0",
            "category": "command",
            "icon": "🔵",
            "description": "Node.js 运行时",
        }
        """
        return []

    def execute(self, tool_id: str, args: list[str], ctx: "PluginContext") -> dict:
        """执行指定工具。"""
        return {"error": f"not implemented: {tool_id}"}

    def get_config_schema(self) -> dict | None:
        """插件配置 Schema（JSON Schema 格式）。"""
        return None


@dataclass
class PluginContext:
    """插件执行上下文。"""
    working_dir: str = ""
    env: dict = field(default_factory=dict)


# ── 插件加载器 ──

class PluginLoader:
    """从目录加载插件模块（安全校验版）。"""

    @staticmethod
    def _source_from_path(plugin_dir: Path) -> str:
        """从路径推断插件来源。"""
        path_str = str(plugin_dir).lower().replace("\\", "/")
        if "builtin" in path_str:
            return "builtin"
        if "community" in path_str:
            return "community"
        return "user"

    @staticmethod
    def _validate_manifest(manifest: dict, plugin_dir: Path) -> tuple[bool, str]:
        """校验 manifest.json 必填字段。"""
        missing = REQUIRED_MANIFEST_FIELDS - set(manifest.keys())
        if missing:
            return False, f"manifest.json 缺少必填字段: {', '.join(missing)}"

        # 字段类型校验
        if not isinstance(manifest["id"], str) or not manifest["id"].strip():
            return False, "manifest.json id 必须是非空字符串"
        if not isinstance(manifest["name"], str) or not manifest["name"].strip():
            return False, "manifest.json name 必须是非空字符串"
        if not isinstance(manifest["version"], str):
            return False, "manifest.json version 必须是字符串"

        # id 格式校验：只允许字母、数字、点和短横
        if not re.match(r'^[a-zA-Z0-9._-]+$', manifest["id"]):
            return False, f"manifest.json id 格式非法: {manifest['id']}"

        return True, ""

    @staticmethod
    def _validate_path(plugin_dir: Path) -> bool:
        """路径穿越防护：确保插件路径在允许的目录内。"""
        try:
            resolved = plugin_dir.resolve()
            allowed = [Path(d).resolve() for d in DEFAULT_PLUGIN_DIRS]
            # 允许的父目录列表
            allowed_parents = [p for p in allowed if p.exists()]
            if not allowed_parents:
                return True  # 无法判断时放行（不阻塞运行）
            for parent in allowed_parents:
                if parent in resolved.parents or resolved == parent:
                    return True
            _log.warning("路径穿越拒绝: %s 不在允许目录内", resolved)
            return False
        except Exception:
            return False

    @staticmethod
    def load_from_dir(plugin_dir: Path) -> tuple[Any, PluginInfo] | None:
        """从插件目录加载插件。

        期望目录结构:
          plugin_dir/
            manifest.json    # 必须（含 id/name/version）
            plugin.py        # 必须，导出 Plugin 类

        安全校验：
          - Manifest 必填字段检查
          - 路径穿越防护
          - Community 插件导入白名单

        返回 (plugin_instance, plugin_info) 或 None。
        """
        manifest_path = plugin_dir / "manifest.json"
        plugin_py_path = plugin_dir / "plugin.py"

        if not manifest_path.exists():
            return None
        if not plugin_py_path.exists():
            return None

        # 路径穿越防护
        if not PluginLoader._validate_path(plugin_dir):
            _log.warning("路径穿越拒绝: %s", plugin_dir)
            return None

        # 读取 manifest
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            _log.warning("manifest.json 解析失败 %s: %s", plugin_dir, e)
            return None

        # 校验 manifest 必填字段
        valid, msg = PluginLoader._validate_manifest(manifest, plugin_dir)
        if not valid:
            _log.warning("manifest 校验失败 %s: %s", plugin_dir, msg)
            return None

        plugin_id = manifest["id"]
        plugin_name = manifest["name"]
        plugin_version = manifest["version"]
        plugin_author = manifest.get("author", "Unknown")
        plugin_desc = manifest.get("description", "")
        plugin_category = manifest.get("category", "general")
        plugin_icon = manifest.get("icon", "🧩")

        source = PluginLoader._source_from_path(plugin_dir)
        trust = PluginTrustLevel.BUILTIN if source == "builtin" else (
            PluginTrustLevel.USER if source == "user" else PluginTrustLevel.COMMUNITY
        )

        # 动态导入 plugin.py
        try:
            module_name = f"_claudez_plugin_{re.sub(r'[^a-zA-Z0-9]', '_', plugin_id)}"

            # Community 插件：注入导入白名单
            if trust == PluginTrustLevel.COMMUNITY:
                _install_import_hook(plugin_id)

            spec = importlib.util.spec_from_file_location(
                module_name,
                str(plugin_py_path),
            )
            if spec is None or spec.loader is None:
                _log.warning("无法加载插件模块 %s", plugin_py_path)
                return None

            mod = importlib.util.module_from_spec(spec)
            # 临时注册（避免后续同名冲突，但名字加了随机后缀不会冲突）
            sys.modules[spec.name] = mod
            spec.loader.exec_module(mod)

            if not hasattr(mod, "Plugin"):
                _log.warning("插件 %s 未导出 Plugin 类", plugin_dir)
                _cleanup_module(spec.name)
                return None

            plugin_class = getattr(mod, "Plugin")
            instance = plugin_class()

            info = PluginInfo(
                id=plugin_id,
                name=plugin_name,
                version=plugin_version,
                author=plugin_author,
                description=plugin_desc,
                path=plugin_dir,
                manifest=manifest,
                category=plugin_category,
                icon=plugin_icon,
                tools=manifest.get("tools", []),
                instance=instance,
                source=source,
            )

            _log.info("插件加载成功 [%s] %s v%s (信任等级: %s)",
                      trust.value, plugin_id, plugin_version, trust.value)
            return instance, info

        except Exception as e:
            _log.error("加载插件 %s 失败: %s", plugin_dir, e)
            import traceback
            _log.debug(traceback.format_exc())
            return None


# ── 导入白名单机制（Community 插件） ──

_IMPORT_HOOK_ACTIVE = False
"""是否启用了导入白名单钩子。"""

class _RestrictedImporter:
    """Community 插件的导入白名单钩子。

    只允许导入 COMMUNITY_ALLOWED_IMPORTS 中的模块，
    其他 import 抛出 ImportError。
    """

    def __init__(self, plugin_id: str):
        self.plugin_id = plugin_id

    def find_spec(self, fullname, path, target=None):
        module_name = fullname.split(".")[0]
        if module_name in COMMUNITY_ALLOWED_IMPORTS:
            return None  # 放行，交给默认导入器
        # 拒绝未授权的导入
        _log.warning("Community 插件 %s 被禁止导入: %s", self.plugin_id, fullname)
        raise ImportError(
            f"Community 插件 '{self.plugin_id}' 禁止导入 '{fullname}'。"
            f"允许的模块: {', '.join(sorted(COMMUNITY_ALLOWED_IMPORTS))}"
        )


def _install_import_hook(plugin_id: str):
    """安装 Community 插件导入白名单钩子。"""
    global _IMPORT_HOOK_ACTIVE
    if not _IMPORT_HOOK_ACTIVE:
        sys.meta_path.insert(0, _RestrictedImporter(plugin_id))
        _IMPORT_HOOK_ACTIVE = True


def _cleanup_module(name: str):
    """清理临时模块注册。"""
    sys.modules.pop(name, None)


# ── 插件管理器 ──

class PluginManager:
    """插件管理器 — 发现、加载、卸载、执行插件。"""

    def __init__(self, plugin_dirs: list[str] | None = None):
        self._plugin_dirs = [Path(d) for d in (plugin_dirs or DEFAULT_PLUGIN_DIRS)]
        self._plugins: dict[str, PluginInfo] = {}  # plugin_id -> PluginInfo
        self._lock = threading.Lock()
        self._tool_registry_ref = None  # 持有 ToolRegistry 引用
        self._on_plugins_changed: Callable | None = None  # 插件变化时回调

    def set_tool_registry(self, registry):
        """设置 ToolRegistry 引用（用于注册/注销工具）。"""
        self._tool_registry_ref = registry

    def on_changed(self, callback: Callable):
        """设置插件状态变化回调。"""
        self._on_plugins_changed = callback

    # ── 发现 ──

    def discover(self) -> list[PluginInfo]:
        """重新扫描所有目录，发现可用插件。

        返回新发现的插件列表。
        """
        discovered = []
        for plugin_dir in self._plugin_dirs:
            if not plugin_dir.exists():
                continue
            for item in sorted(plugin_dir.iterdir()):
                if not item.is_dir():
                    continue
                # 跳过已加载的
                existing = [p for p in self._plugins.values()
                           if p.path and p.path.resolve() == item.resolve()]
                if existing:
                    continue

                result = PluginLoader.load_from_dir(item)
                if result is None:
                    continue

                instance, info = result
                with self._lock:
                    self._plugins[info.id] = info
                    discovered.append(info)

        return discovered

    def discover_one(self, plugin_dir: str) -> PluginInfo | None:
        """发现并加载单个插件目录。"""
        path = Path(plugin_dir)
        if not path.exists() or not path.is_dir():
            return None

        result = PluginLoader.load_from_dir(path)
        if result is None:
            return None

        instance, info = result
        with self._lock:
            self._plugins[info.id] = info
        return info

    # ── 加载/卸载 ──

    def load(self, plugin_id: str) -> bool:
        """加载（启用）一个插件。

        流程:
          1. 校验信任等级（Community 插件受限）
          2. 调用 plugin.on_load()
          3. 将 plugin.tools 注册到 ToolRegistry
          4. 标记为 enabled
        """
        with self._lock:
            info = self._plugins.get(plugin_id)
            if info is None:
                _log.warning("插件 %s 未找到", plugin_id)
                return False
            if info.enabled:
                return True
            if info.instance is None:
                _log.warning("插件 %s 没有实例", plugin_id)
                return False

        # ── 信任等级校验 ──
        trust = PluginTrustLevel(info.source)
        if trust == PluginTrustLevel.COMMUNITY:
            _log.info("Community 插件受限加载: %s (导入白名单 %d 个模块)",
                      plugin_id, len(COMMUNITY_ALLOWED_IMPORTS))

        ctx = PluginContext()

        try:
            success = info.instance.on_load(ctx)
            if not success:
                _log.warning("插件 %s on_load 返回 False", plugin_id)
                return False
        except Exception as e:
            _log.error("插件 %s on_load 异常: %s", plugin_id, e)
            return False

        # 获取工具列表
        try:
            tools = info.instance.get_tools()
            info.tools = tools
        except Exception as e:
            _log.error("插件 %s get_tools 异常: %s", plugin_id, e)
            tools = []
            info.tools = []

        # 注册到 ToolRegistry
        if self._tool_registry_ref and tools:
            for tool_def in tools:
                name = tool_def.get("name", "")
                if name:
                    self._tool_registry_ref.register_host_tool(name, tool_def, info)

        info.enabled = True
        _log.info("插件已加载: %s v%s (%d 工具)", info.name, info.version, len(tools))

        if self._on_plugins_changed:
            try:
                self._on_plugins_changed()
            except Exception:
                pass

        return True

    def unload(self, plugin_id: str) -> bool:
        """卸载（禁用）一个插件。"""
        with self._lock:
            info = self._plugins.get(plugin_id)
            if info is None:
                return False
            if not info.enabled:
                return True

        try:
            if info.instance:
                info.instance.on_unload()
        except Exception as e:
            _log.error("插件 %s on_unload 异常: %s", plugin_id, e)

        # 从 ToolRegistry 注销
        if self._tool_registry_ref and info.tools:
            for tool_def in info.tools:
                name = tool_def.get("name", "")
                if name:
                    self._tool_registry_ref.unregister_host_tool(name)

        info.enabled = False
        _log.info("插件已卸载: %s v%s", info.name, info.version)

        if self._on_plugins_changed:
            try:
                self._on_plugins_changed()
            except Exception:
                pass

        return True

    def load_all(self) -> int:
        """加载所有已发现的插件。返回成功加载数。"""
        count = 0
        for plugin_id in list(self._plugins.keys()):
            if self.load(plugin_id):
                count += 1
        return count

    def unload_all(self):
        """卸载所有插件。"""
        for plugin_id in list(self._plugins.keys()):
            self.unload(plugin_id)

    def reload(self, plugin_id: str) -> bool:
        """重新加载插件：清空旧工具注册，重新获取并注册。

        用于重新探测（re-probe）后刷新工具列表到 ToolRegistry。
        """
        info = self._plugins.get(plugin_id)
        if not info:
            return False
        if not info.enabled:
            # 未启用的直接调用 load
            return self.load(plugin_id)

        # 清空旧工具注册
        if self._tool_registry_ref and info.tools:
            for tool_def in info.tools:
                name = tool_def.get("name", "")
                if name:
                    self._tool_registry_ref.unregister_host_tool(name)

        # 重新获取工具列表（get_tools 已自动过滤被屏蔽的）
        try:
            tools = info.instance.get_tools() if info.instance else []
            info.tools = tools
        except Exception as e:
            _log.error("插件 %s reload get_tools 异常: %s", plugin_id, e)
            tools = []
            info.tools = []

        # 重新注册
        if self._tool_registry_ref and tools:
            for tool_def in tools:
                name = tool_def.get("name", "")
                if name:
                    self._tool_registry_ref.register_host_tool(name, tool_def, info)

        _log.info("插件已重载: %s v%s (%d 工具)", info.name, info.version, len(tools))

        if self._on_plugins_changed:
            try:
                self._on_plugins_changed()
            except Exception:
                pass

        return True

    # ── 查询 ──

    def get_plugin(self, plugin_id: str) -> PluginInfo | None:
        return self._plugins.get(plugin_id)

    def get_all_plugins(self) -> list[PluginInfo]:
        return list(self._plugins.values())

    def get_enabled_plugins(self) -> list[PluginInfo]:
        return [p for p in self._plugins.values() if p.enabled]

    def get_all_tools(self) -> list[dict]:
        """获取所有已启用插件的工具列表。"""
        tools = []
        for info in self._plugins.values():
            if info.enabled:
                tools.extend(info.tools)
        return tools

    def get_tools_by_category(self) -> dict[str, list[dict]]:
        """按类别分组的工具列表。"""
        groups: dict[str, list[dict]] = {}
        for info in self._plugins.values():
            if not info.enabled:
                continue
            for tool in info.tools:
                cat = tool.get("category", info.category)
                if cat not in groups:
                    groups[cat] = []
                groups[cat].append({
                    **tool,
                    "plugin_id": info.id,
                    "plugin_name": info.name,
                    "source": "host",
                })
        return groups

    def execute(self, plugin_id: str, tool_id: str, args: list[str]) -> dict:
        """执行插件工具。"""
        info = self._plugins.get(plugin_id)
        if info is None:
            return {"error": f"插件 {plugin_id} 未找到"}
        if not info.enabled:
            return {"error": f"插件 {plugin_id} 未启用"}
        if info.instance is None:
            return {"error": f"插件 {plugin_id} 无实例"}

        ctx = PluginContext()
        try:
            return info.instance.execute(tool_id, args, ctx)
        except Exception as e:
            _log.error("执行插件工具 %s/%s 失败: %s", plugin_id, tool_id, e)
            return {"error": str(e)}


# ── 全局实例 ──

_global_manager: PluginManager | None = None
_manager_lock = threading.Lock()


def get_plugin_manager() -> PluginManager:
    """获取全局插件管理器实例。"""
    global _global_manager
    if _global_manager is None:
        with _manager_lock:
            if _global_manager is None:
                _global_manager = PluginManager()
    return _global_manager


def reset_plugin_manager():
    """重置全局插件管理器（主要用于测试）。"""
    global _global_manager
    with _manager_lock:
        if _global_manager:
            _global_manager.unload_all()
        _global_manager = None
