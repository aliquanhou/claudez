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
    默认中文嵌入模型：shibing624/text2vec-base-chinese（384 维，中文优化）
    可通过 embedding_model 参数或 CLAUDEZ_EMBEDDING_MODEL 环境变量覆盖。
    """

    def __init__(self, storage_dir: str | None = None,
                 embedding_model: str | None = None):
        self.storage_dir = storage_dir or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            ".claudez", "memory"
        )
        # 嵌入模型配置：环境变量 > 构造参数 > 默认中文模型
        self._embedding_model_name = (
            embedding_model
            or os.environ.get("CLAUDEZ_EMBEDDING_MODEL")
            or "shibing624/text2vec-base-chinese"
        )
        self._embedding_fn = None
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

            # 初始化嵌入函数（懒加载）
            if self._embedding_fn is None:
                self._embedding_fn = self._init_embedding()

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

    @staticmethod
    def _init_embedding(model_name: str = "shibing624/text2vec-base-chinese"):
        """初始化嵌入函数。

        优先使用 sentence-transformers，回退到 ChromaDB 默认嵌入。
        """
        try:
            from sentence_transformers import SentenceTransformer
            model = SentenceTransformer(model_name)
            def embed_fn(texts):
                if isinstance(texts, str):
                    texts = [texts]
                embeddings = model.encode(texts, show_progress_bar=False)
                return embeddings.tolist()
            print(f"[记忆] 已加载中文嵌入模型: {model_name}")
            return embed_fn
        except ImportError:
            print(f"[记忆] sentence-transformers 未安装，使用 ChromaDB 默认嵌入")
            return None
        except Exception as e:
            print(f"[记忆] 嵌入模型加载失败 {model_name}: {e}，使用 ChromaDB 默认嵌入")
            return None

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
            kwargs = {
                "documents": [content],
                "metadatas": [meta],
                "ids": [mid],
            }
            # 显式传入嵌入向量（若使用自定义嵌入模型）
            if self._embedding_fn:
                kwargs["embeddings"] = [self._embedding_fn(content)]
            self._collection.add(**kwargs)
            return True
        except Exception as e:
            print(f"[记忆] store 失败: {e}")
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
                "n_results": min(n_results, 50),
            }
            if filter_dict:
                kwargs["where"] = filter_dict
            # 显式传入查询向量（若使用自定义嵌入模型）
            if self._embedding_fn:
                kwargs["query_embeddings"] = [self._embedding_fn(query)]
            else:
                kwargs["query_texts"] = [query]

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
        except Exception as e:
            print(f"[记忆] search 失败: {e}")
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
