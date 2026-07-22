"""
workspace_scanner.py - ForgeX 工作区扫描器

职责：扫描代码库，提供文件树、项目类型推断、关键文件识别。
采用惰性初始化，避免启动时IO阻塞。
"""

import os
import time
import json
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from pathlib import Path
from datetime import datetime


@dataclass
class WorkspaceInfo:
    """工作区信息快照"""
    root_path: str
    file_count: int
    dir_count: int
    project_type: Optional[str]  # "python", "node", "java", "rust", "go", "unknown"
    key_files: List[str] = field(default_factory=list)
    languages: List[str] = field(default_factory=list)
    scanned_at: float = field(default_factory=time.time)
    file_tree: Dict[str, Any] = field(default_factory=dict)


class WorkspaceScanner:
    """
    工作区扫描器 - 惰性扫描
    在第一次调用 get_info() 或 get_file_tree() 时才执行扫描
    """

    # 项目类型识别规则
    PROJECT_TYPE_RULES = {
        "python": ["requirements.txt", "pyproject.toml", "setup.py", "Pipfile"],
        "node": ["package.json", "yarn.lock", "pnpm-lock.yaml"],
        "java": ["pom.xml", "build.gradle", ".java"],
        "rust": ["Cargo.toml"],
        "go": ["go.mod", "go.sum"],
    }

    # 关键文件识别规则（按项目类型）
    KEY_FILE_RULES = {
        "python": ["main.py", "app.py", "wsgi.py", "settings.py", "manage.py"],
        "node": ["index.js", "app.js", "server.js", "main.js"],
        "java": ["Main.java", "Application.java", "pom.xml"],
        "rust": ["main.rs", "lib.rs"],
        "go": ["main.go"],
    }

    # 默认忽略的目录
    IGNORE_DIRS = {
        ".git", "node_modules", "__pycache__", "venv", "env",
        ".venv", "dist", "build", "target", "out", ".idea",
        ".vscode", ".mypy_cache", ".pytest_cache", ".ruff_cache",
        "coverage", ".tox", ".eggs", "*.egg-info"
    }

    def __init__(self, root_path: str):
        self.root_path = Path(root_path).resolve()
        self._info: Optional[WorkspaceInfo] = None
        self._file_tree: Optional[Dict[str, Any]] = None
        self._scanned = False

    def _should_ignore(self, path: Path) -> bool:
        """检查路径是否应被忽略"""
        # 检查路径中的每个部分
        for part in path.parts:
            if part in self.IGNORE_DIRS:
                return True
            # 检查是否匹配通配符模式
            if part.endswith(".egg-info"):
                return True
        return False

    def _detect_project_type(self, files: List[str]) -> str:
        """根据文件列表推断项目类型"""
        file_names = set(files)
        for proj_type, indicators in self.PROJECT_TYPE_RULES.items():
            for indicator in indicators:
                if indicator in file_names:
                    return proj_type
                # 对于.java文件，检查是否有任何.java文件
                if indicator == ".java" and any(f.endswith(".java") for f in files):
                    return "java"
                if indicator == ".py" and any(f.endswith(".py") for f in files):
                    # 但如果已经有python特征文件，已经返回了
                    pass
        return "unknown"

    def _detect_languages(self, files: List[str]) -> List[str]:
        """检测使用的编程语言"""
        extensions = set()
        for f in files:
            ext = Path(f).suffix
            if ext:
                extensions.add(ext)

        lang_map = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".jsx": "javascript",
            ".tsx": "typescript",
            ".java": "java",
            ".go": "go",
            ".rs": "rust",
            ".c": "c",
            ".cpp": "cpp",
            ".h": "c",
            ".hpp": "cpp",
            ".cs": "csharp",
            ".rb": "ruby",
            ".php": "php",
            ".swift": "swift",
            ".kt": "kotlin",
            ".scala": "scala",
            ".lua": "lua",
            ".r": "r",
            ".sh": "shell",
            ".bash": "shell",
            ".sql": "sql",
            ".html": "html",
            ".css": "css",
            ".json": "json",
            ".yaml": "yaml",
            ".yml": "yaml",
            ".toml": "toml",
            ".xml": "xml",
            ".md": "markdown",
        }

        languages = set()
        for ext in extensions:
            if ext in lang_map:
                languages.add(lang_map[ext])
        return sorted(languages)

    def _find_key_files(self, files: List[str], project_type: str) -> List[str]:
        """查找关键文件"""
        file_names = set(Path(f).name for f in files)
        key_files = []

        # 根据项目类型查找关键文件
        rules = self.KEY_FILE_RULES.get(project_type, [])
        for rule in rules:
            for f in files:
                if Path(f).name == rule:
                    key_files.append(f)
                    break

        # 额外查找：README, LICENSE, .gitignore
        for f in files:
            name = Path(f).name
            if name.upper() in ["README.MD", "README", "LICENSE", "LICENSE.MD"]:
                if f not in key_files:
                    key_files.append(f)
            if name in [".gitignore", ".dockerignore"]:
                if f not in key_files:
                    key_files.append(f)

        # 如果有 agent/core.py 或类似的入口文件，确保它被包含
        entry_candidates = ["agent/core.py", "core.py", "main.py", "app.py"]
        for candidate in entry_candidates:
            if candidate in files and candidate not in key_files:
                key_files.append(candidate)
                break

        return key_files[:10]  # 最多返回10个

    def _build_file_tree(self, files: List[str], max_depth: int = 3) -> Dict[str, Any]:
        """构建文件树结构"""
        tree = {}

        for file_path in files:
            rel_path = Path(file_path)
            parts = rel_path.parts

            # 限制深度
            if len(parts) > max_depth:
                continue

            # 构建树
            current = tree
            for i, part in enumerate(parts):
                if i == len(parts) - 1:
                    # 文件节点（叶子）
                    current[part] = None
                else:
                    # 目录节点
                    if part not in current:
                        current[part] = {}
                    current = current[part]

        return tree

    def _scan(self):
        """执行实际扫描（惰性）"""
        if self._scanned:
            return

        files = []
        dirs = []
        file_names = []

        # 遍历目录
        for root, dirnames, filenames in os.walk(self.root_path):
            root_path = Path(root)

            # 检查是否忽略当前目录
            if self._should_ignore(root_path):
                continue

            # 过滤被忽略的子目录
            dirnames[:] = [d for d in dirnames if not self._should_ignore(root_path / d)]

            for filename in filenames:
                file_path = root_path / filename
                rel_path = file_path.relative_to(self.root_path)
                files.append(str(rel_path))
                file_names.append(filename)

            for dirname in dirnames:
                dirs.append(str(root_path / dirname))

        # 推断项目类型
        project_type = self._detect_project_type(file_names)
        languages = self._detect_languages(files)
        key_files = self._find_key_files(files, project_type)

        # 构建文件树（限制深度2用于快速展示）
        file_tree = self._build_file_tree(files, max_depth=2)

        self._info = WorkspaceInfo(
            root_path=str(self.root_path),
            file_count=len(files),
            dir_count=len(dirs),
            project_type=project_type,
            key_files=key_files,
            languages=languages,
            file_tree=file_tree
        )

        self._file_tree = file_tree
        self._scanned = True

    def get_info(self) -> WorkspaceInfo:
        """获取工作区信息（触发扫描如果尚未扫描）"""
        if not self._scanned:
            self._scan()
        return self._info

    def get_file_tree(self, max_depth: int = 2) -> Dict[str, Any]:
        """获取文件树"""
        if not self._scanned:
            self._scan()
        # 根据深度重新构建
        if max_depth != 2:
            files = self._collect_all_files()
            return self._build_file_tree(files, max_depth=max_depth)
        return self._file_tree

    def _collect_all_files(self) -> List[str]:
        """收集所有文件路径（用于重建树）"""
        if not self._info:
            self._scan()
        # 需要从文件系统中重新收集，或者从_info中恢复
        files = []
        for root, dirnames, filenames in os.walk(self.root_path):
            root_path = Path(root)
            if self._should_ignore(root_path):
                continue
            dirnames[:] = [d for d in dirnames if not self._should_ignore(root_path / d)]
            for filename in filenames:
                file_path = root_path / filename
                rel_path = file_path.relative_to(self.root_path)
                files.append(str(rel_path))
        return files

    # 属性访问器（兼容旧接口）
    @property
    def info(self) -> WorkspaceInfo:
        return self.get_info()

    @property
    def file_tree(self) -> Dict[str, Any]:
        return self.get_file_tree()
