"""Skill Manager — 自动技能管理。

技能 = 工具调用序列的可重用模板。
存储为 JSON（模式 + 描述 + 参数），通过 SQLite 持久化。

Hermes 风格：
  - 渐进加载：系统提示中只有索引（name + 一句话描述）
  - 按需加载完整内容（skill_view）
  - 自动创建触发器（5+ 工具调用的复杂任务）
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

_log = logging.getLogger("claudez.self_evol")

# ── SQLite 建表 ──

_CREATE_SKILLS_TABLE = """
CREATE TABLE IF NOT EXISTS skills (
    id TEXT PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    description TEXT NOT NULL,
    category TEXT DEFAULT 'general',
    steps_json TEXT NOT NULL,
    trigger_pattern TEXT DEFAULT '',
    tags TEXT DEFAULT '',
    usage_count INTEGER DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    is_pinned INTEGER DEFAULT 0
);
"""

_DEFAULT_DB_PATH = os.path.join(
    os.environ.get("HOME") or os.environ.get("USERPROFILE") or ".",
    ".claudez", "skills", "skills.db",
)


@dataclass
class SkillStep:
    """技能中的单个步骤。"""
    action: str          # "read" | "write" | "edit" | "bash" | "web_search" | ...
    target: str          # 目标文件/URL/命令
    description: str     # 步骤描述
    args: dict = field(default_factory=dict)


@dataclass
class Skill:
    """一个完整的技能。"""
    id: str
    name: str
    description: str
    category: str = "general"
    steps: list[SkillStep] = field(default_factory=list)
    trigger_pattern: str = ""      # 触发关键词模式
    tags: list[str] = field(default_factory=list)
    usage_count: int = 0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    is_pinned: bool = False

    def to_index_entry(self) -> str:
        """生成系统提示中的索引条目（Hermes 渐进加载风格）。"""
        return f"- {self.name}: {self.description[:80]}"

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "description": self.description,
            "category": self.category,
            "steps": [{"action": s.action, "target": s.target, "description": s.description, "args": s.args} for s in self.steps],
            "trigger_pattern": self.trigger_pattern, "tags": self.tags,
            "usage_count": self.usage_count, "is_pinned": self.is_pinned,
            "created_at": self.created_at, "updated_at": self.updated_at,
        }


class SkillManager:
    """技能管理器 — CRUD + 搜索 + 自动创建触发。

    Usage:
        mgr = SkillManager()
        mgr.create("deploy-pwa", "Deploy PWA to Firebase", [...])
        skills = mgr.search("deploy")
        mgr.record_usage("deploy-pwa")
    """

    def __init__(self, db_path: str = ""):
        self._db_path = db_path or _DEFAULT_DB_PATH
        self._ensure_db()
        self._cache: dict[str, Skill] = {}
        self._load_cache()

    def _ensure_db(self) -> None:
        dirname = os.path.dirname(self._db_path)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(_CREATE_SKILLS_TABLE)

    def _load_cache(self) -> None:
        try:
            with sqlite3.connect(self._db_path) as conn:
                rows = conn.execute(
                    "SELECT id, name, description, category, steps_json, trigger_pattern, "
                    "tags, usage_count, created_at, updated_at, is_pinned FROM skills"
                ).fetchall()
                for row in rows:
                    steps_data = json.loads(row[4]) if row[4] else []
                    steps = [SkillStep(**s) for s in steps_data] if steps_data else []
                    self._cache[row[0]] = Skill(
                        id=row[0], name=row[1], description=row[2], category=row[3],
                        steps=steps, trigger_pattern=row[5] or "",
                        tags=row[6].split(",") if row[6] else [],
                        usage_count=row[7] or 0, created_at=row[8] or 0,
                        updated_at=row[9] or 0, is_pinned=bool(row[10]),
                    )
        except Exception as e:
            _log.warning("skill_cache_load_error: %s", e)

    def create(
        self, name: str, description: str,
        steps: list[SkillStep] | None = None,
        category: str = "general",
        trigger_pattern: str = "",
        tags: list[str] | None = None,
    ) -> Skill:
        """创建一个新技能。"""
        now = time.time()
        skill = Skill(
            id=str(uuid.uuid4())[:12],
            name=name, description=description, category=category,
            steps=steps or [], trigger_pattern=trigger_pattern,
            tags=tags or [], created_at=now, updated_at=now,
        )
        self._save(skill)
        self._cache[skill.id] = skill
        _log.info("skill_created name=%s id=%s steps=%d", name, skill.id, len(skill.steps))
        return skill

    def get(self, skill_id: str) -> Skill | None:
        return self._cache.get(skill_id)

    def get_by_name(self, name: str) -> Skill | None:
        for s in self._cache.values():
            if s.name == name:
                return s
        return None

    def search(self, query: str) -> list[Skill]:
        """搜索技能（名称/描述/标签）。"""
        q = query.lower()
        results = []
        for s in self._cache.values():
            if q in s.name.lower() or q in s.description.lower():
                results.append(s)
            elif any(q in tag.lower() for tag in s.tags):
                results.append(s)
        return results

    def update(self, skill_id: str, **kwargs) -> Skill | None:
        skill = self._cache.get(skill_id)
        if not skill:
            return None
        for k, v in kwargs.items():
            if hasattr(skill, k):
                setattr(skill, k, v)
        skill.updated_at = time.time()
        self._save(skill)
        return skill

    def delete(self, skill_id: str) -> bool:
        if skill_id not in self._cache:
            return False
        del self._cache[skill_id]
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute("DELETE FROM skills WHERE id = ?", (skill_id,))
            _log.info("skill_deleted id=%s", skill_id)
            return True
        except Exception as e:
            _log.warning("skill_delete_error id=%s %s", skill_id, e)
            return False

    def record_usage(self, skill_id: str) -> None:
        skill = self._cache.get(skill_id)
        if skill:
            skill.usage_count += 1
            skill.updated_at = time.time()
            self._save(skill)

    def _save(self, skill: Skill) -> None:
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO skills "
                    "(id, name, description, category, steps_json, trigger_pattern, "
                    "tags, usage_count, created_at, updated_at, is_pinned) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        skill.id, skill.name, skill.description, skill.category,
                        json.dumps([s.__dict__ for s in skill.steps], ensure_ascii=False),
                        skill.trigger_pattern, ",".join(skill.tags),
                        skill.usage_count, skill.created_at, skill.updated_at,
                        1 if skill.is_pinned else 0,
                    ),
                )
        except Exception as e:
            _log.warning("skill_save_error name=%s %s", skill.name, e)

    def get_index(self) -> list[str]:
        """获取系统提示索引（Hermes 风格渐进加载）。"""
        pinned = [s for s in self._cache.values() if s.is_pinned]
        others = [s for s in self._cache.values() if not s.is_pinned]
        entries = []
        if pinned:
            entries.append("--- 置顶技能 ---")
            entries.extend(s.to_index_entry() for s in pinned)
        if others:
            entries.append("--- 技能库 ---")
            entries.extend(s.to_index_entry() for s in sorted(others, key=lambda s: s.usage_count, reverse=True)[:10])
        return entries

    def should_create_skill(self, tool_call_count: int, errors: int, duration_ms: float) -> bool:
        """判断是否应该自动创建技能。

        条件：工具调用 > 5 且 错误 <= 1（成功完成的复杂任务）
        """
        return tool_call_count >= 5 and errors <= 1 and duration_ms > 10000

    def auto_create_from_trace(
        self, goal: str, tool_calls: list[dict],
    ) -> Skill | None:
        """从工具调用轨迹自动创建技能。"""
        if not tool_calls:
            return None
        steps = []
        seen = set()
        for tc in tool_calls:
            name = tc.get("name", "")
            args = tc.get("args", {})
            key = f"{name}:{json.dumps(args, sort_keys=True)}"
            if key in seen:
                continue
            seen.add(key)
            target = args.get("file_path") or args.get("command") or args.get("url") or ""
            steps.append(SkillStep(
                action=name, target=str(target),
                description=args.get("description", f"Run {name}")[:100],
                args=dict(args),
            ))
        name = goal.strip().replace(" ", "-").replace("/", "-")[:40].lower()
        if not name:
            name = f"auto-skill-{uuid.uuid4().hex[:8]}"
        return self.create(
            name=name,
            description=goal[:200],
            steps=steps,
            category="auto-generated",
            tags=["auto"],
        )

    @property
    def count(self) -> int:
        return len(self._cache)

    @property
    def all(self) -> list[Skill]:
        return list(self._cache.values())
