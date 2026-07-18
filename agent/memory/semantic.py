"""memory/semantic — 语义记忆（ChromaDB 向量存储）。

跨会话的长期记忆，基于语义相似度检索。
"""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any


class SemanticMemory:
    """语义记忆——基于 ChromaDB 的向量存储。

    存储路径：{project_root}/.claudez/memory/
    """

    def __init__(self, storage_dir: str | None = None):
        self.storage_dir = storage_dir or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            ".claudez", "memory"
        )
        self._collection = None
        self._ready = False

    def _ensure(self) -> bool:
        """确保 ChromaDB 可用。"""
        if self._ready:
            return True

        try:
            import chromadb
            os.makedirs(self.storage_dir, exist_ok=True)
            client = chromadb.PersistentClient(path=self.storage_dir)
            try:
                self._collection = client.get_collection("claudez_memory")
            except Exception:
                self._collection = client.create_collection("claudez_memory")
            self._ready = True
            return True
        except ImportError:
            return False
        except Exception as e:
            print(f"[记忆] ChromaDB 初始化失败: {e}")
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
            self._collection.add(
                documents=[content],
                metadatas=[meta],
                ids=[mid],
            )
            return True
        except Exception:
            return False

    def search(self, query: str, n_results: int = 5,
               filter_dict: dict | None = None) -> list[dict]:
        """搜索记忆。

        Args:
            query: 搜索查询
            n_results: 返回结果数
            filter_dict: 过滤条件

        Returns:
            记忆列表 [{"id": str, "content": str, "metadata": dict, "distance": float}]
        """
        if not self._ensure():
            return []

        try:
            kwargs = {
                "query_texts": [query],
                "n_results": min(n_results, 50),
            }
            if filter_dict:
                kwargs["where"] = filter_dict

            results = self._collection.query(**kwargs)

            items = []
            for i in range(len(results["ids"][0])):
                items.append({
                    "id": results["ids"][0][i],
                    "content": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i],
                    "distance": results["distances"][0][i] if results.get("distances") else 0,
                })
            return items
        except Exception:
            return []

    def delete(self, mem_id: str) -> bool:
        """删除记忆。"""
        if not self._ensure():
            return False
        try:
            self._collection.delete(ids=[mem_id])
            return True
        except Exception:
            return False

    def count(self) -> int:
        """记忆数量。"""
        if not self._ensure():
            return 0
        try:
            return self._collection.count()
        except Exception:
            return 0

    def get_recent(self, limit: int = 10) -> list[dict]:
        """获取最近的记忆列表。"""
        if not self._ensure():
            return []
        try:
            all_data = self._collection.get()
            ids = all_data.get("ids", [])
            docs = all_data.get("documents", [])
            metas = all_data.get("metadatas", [])
            recent = []
            for i in range(min(limit, len(ids))):
                idx = len(ids) - 1 - i
                if idx < 0:
                    break
                recent.append({
                    "id": ids[idx],
                    "content": docs[idx][:300] if idx < len(docs) else "",
                    "metadata": metas[idx] if idx < len(metas) else {},
                })
            return recent
        except Exception:
            return []

    def clear(self):
        """清空所有记忆。"""
        if not self._ensure():
            return
        try:
            all_ids = self._collection.get()["ids"]
            if all_ids:
                self._collection.delete(ids=all_ids)
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
