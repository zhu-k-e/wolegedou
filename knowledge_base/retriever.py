"""
RAG检索器。
对外统一接口，屏蔽底层ChromaDB细节。
"""

from typing import List, Dict
from .vector_store import VectorStore
from loguru import logger


class KnowledgeRetriever:
    """
    知识检索器。
    供 AgentOrchestrator 调用，也供外部测试用。

    使用方式：
        retriever = KnowledgeRetriever()
        docs = retriever.retrieve("梯度下降")
    """

    def __init__(self):
        self.store = VectorStore()

    def retrieve(self, query: str, top_k: int = 5) -> List[Dict]:
        """
        检索相关知识。

        Args:
            query: 查询文本
            top_k: 返回条数

        Returns:
            [{"id": "...", "content": "...", "metadata": {...}}, ...]
        """
        return self.store.search(query, top_k=top_k)

    def get_doc_count(self) -> int:
        """获取已入库文档数量。"""
        return self.store.collection.count()
