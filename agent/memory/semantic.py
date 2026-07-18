"""memory/semantic — 语义记忆（ChromaDB 向量存储 + SQLite 降级）。

跨会话的长期记忆，基于语义相似度检索。
自动检测 ChromaDB 是否可用，不可用时降级为 SQLite + 关键词搜索。
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from typing import Any


# ── 检测 ChromaDB 是否可用 ──

_CHROMADB_AVAILABLE = False
try:
    import chromadb
    _CHROMADB_AVAILABLE = True
except ImportError:
    pass


class SemanticMemory:
    """语义记忆——基于 ChromaDB 的向量存储（自动降级）。

    存储路径：{project_root}/.claudez/memory/
    引擎：ChromaDB（首选）→ SQLite + 关键词搜索（降级）
    """

    def __init__(self, storage_dir: str | None = None):
        self.storage_dir = storage_dir or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            ".claudez", "memory"
        )
        self._collection = None
        self._ready = False
        self._engine = "none"

    def _ensure(self) -> bool:
        """确保存储引擎可用。"""
        if self._ready:
            return True

        os.makedirs(self.storage_dir, exist_ok=True)

        # 方案 A：ChromaDB
        if _CHROMADB_AVAILABLE:
            try:
                import chromadb
                client = chromadb.PersistentClient(path=self.storage_dir)
                try:
                    self._collection = client.get_collection("claudez_memory")
                except Exception:
                    self._collection = client.create_collection("claudez_memory")
                self._ready = True
                self._engine = "chromadb"
                return True
            except Exception as e:
                print(f"[记忆] ChromaDB 初始化失败: {e}")

        # 方案 B：SQLite 降级
        try:
            self._sqlite_path = os.path.join(self.storage_dir, "memories.db")
            self._sql_conn = sqlite3.connect(self._sqlite_path)
            self._sql_conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    metadata TEXT DEFAULT '{}',
                    timestamp REAL NOT NULL,
                    embedding BLOB
                )
            """)
            self._sql_conn.commit()
            self._ready = True
            self._engine = "sqlite"
            return True
        except Exception as e:
            print(f"[记忆] SQLite 降级初始化失败: {e}")
            return False

    def store(self, content: str, metadata: dict | None = None,
              mem_id: str | None = None) -> bool:
        """存储一条记忆。

        Args:
            content: 记忆内容
            metadata: 元数据（如类型、时间等）
            mem_id: 记忆 ID（自动生成）

        Returns:
            是否成功
        """
        if not self._ensure():
            return False

        try:
            mid = mem_id or str(uuid.uuid4())
            meta = {
                "timestamp": time.time(),
                "type": "general",
                **(metadata or {}),
            }

            if self._engine == "chromadb":
                self._collection.add(
                    documents=[content],
                    metadatas=[meta],
                    ids=[mid],
                )
            else:
                self._sql_conn.execute(
                    "INSERT OR REPLACE INTO memories (id, content, metadata, timestamp) VALUES (?, ?, ?, ?)",
                    (mid, content, json.dumps(meta), meta["timestamp"])
                )
                self._sql_conn.commit()
            return True
        except Exception as e:
            print(f"[记忆] store 失败: {e}")
            return False

    def search(self, query: str, n_results: int = 5,
               filter_dict: dict | None = None,
               min_score: float = 0.0) -> list[dict]:
        """搜索记忆。

        Args:
            query: 搜索查询
            n_results: 返回结果数
            filter_dict: 过滤条件
            min_score: 最低相关性阈值（0.0=不过滤，建议 0.6）

        Returns:
            记忆列表 [{"id": str, "content": str, "metadata": dict, "distance": float, "score": float}]
        """
        if not self._ensure():
            return []

        try:
            if self._engine == "chromadb":
                kwargs = {
                    "query_texts": [query],
                    "n_results": min(n_results, 50),
                }
                if filter_dict:
                    kwargs["where"] = filter_dict

                results = self._collection.query(**kwargs)

                items = []
                for i in range(len(results["ids"][0])):
                    distance = results["distances"][0][i] if results.get("distances") else 0
                    score = max(0.0, 1.0 - distance)  # 距离→相似度
                    if score < min_score:
                        continue
                    items.append({
                        "id": results["ids"][0][i],
                        "content": results["documents"][0][i],
                        "metadata": results["metadatas"][0][i],
                        "distance": distance,
                        "score": score,
                    })
                return items[:n_results]
            else:
                # SQLite 降级：关键词搜索
                cursor = self._sql_conn.execute(
                    "SELECT id, content, metadata, timestamp FROM memories ORDER BY timestamp DESC"
                )
                rows = cursor.fetchall()
                query_lower = query.lower()
                query_words = query_lower.split()

                items = []
                for row in rows:
                    mid, content, meta_json, ts = row
                    content_lower = content.lower()
                    # 简单关键词匹配评分
                    match_count = sum(1 for w in query_words if w in content_lower)
                    if match_count > 0:
                        score = match_count / max(len(query_words), 1)
                        if score < min_score:
                            continue
                        items.append({
                            "id": mid,
                            "content": content,
                            "metadata": json.loads(meta_json),
                            "distance": 1.0 - score,
                            "score": score,
                        })

                items.sort(key=lambda x: x["score"], reverse=True)
                return items[:n_results]
        except Exception:
            return []

    def delete(self, mem_id: str) -> bool:
        """删除记忆。"""
        if not self._ensure():
            return False
        try:
            if self._engine == "chromadb":
                self._collection.delete(ids=[mem_id])
            else:
                self._sql_conn.execute("DELETE FROM memories WHERE id = ?", (mem_id,))
                self._sql_conn.commit()
            return True
        except Exception:
            return False

    def count(self) -> int:
        """记忆数量。"""
        if not self._ensure():
            return 0
        try:
            if self._engine == "chromadb":
                return self._collection.count()
            else:
                cursor = self._sql_conn.execute("SELECT COUNT(*) FROM memories")
                return cursor.fetchone()[0]
        except Exception:
            return 0

    def clear(self):
        """清空所有记忆。"""
        if not self._ensure():
            return
        try:
            if self._engine == "chromadb":
                all_ids = self._collection.get()["ids"]
                if all_ids:
                    self._collection.delete(ids=all_ids)
            else:
                self._sql_conn.execute("DELETE FROM memories")
                self._sql_conn.commit()
        except Exception:
            pass


# ── 全局实例 ──

_INSTANCE: SemanticMemory | None = None


def get_semantic_memory(storage_dir: str | None = None) -> SemanticMemory:
    """获取全局语义记忆实例。"""
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = SemanticMemory(storage_dir)
    return _INSTANCE
