"""
向量存储。
封装ChromaDB操作：创建、嵌入、查询。
"""

import chromadb
from chromadb.utils import embedding_functions
from typing import List, Dict
from config import KB_CONFIG
from loguru import logger


class VectorStore:
    """
    ChromaDB向量数据库封装。

    使用方式：
        store = VectorStore()
        store.add_documents(chunks)       # 导入文档
        results = store.search("查询")    # 检索
    """

    def __init__(self):
        persist_dir = KB_CONFIG["persist_dir"]
        model_name = KB_CONFIG["embedding_model"]

        # 如果persist_dir不存在会自动创建
        self.client = chromadb.PersistentClient(path=persist_dir)

        # 中文向量模型
        self.embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=model_name
        )

        self.collection_name = KB_CONFIG["collection_name"]
        self._init_collection()

    def _init_collection(self):
        """获取或创建集合。"""
        try:
            self.collection = self.client.get_collection(
                name=self.collection_name,
                embedding_function=self.embedding_fn,
            )
            count = self.collection.count()
            logger.info(f"向量库已存在，共 {count} 条记录")
        except Exception:
            self.collection = self.client.create_collection(
                name=self.collection_name,
                embedding_function=self.embedding_fn,
                metadata={"hnsw:space": "cosine"},
            )
            logger.info("创建新的向量库")

    def add_documents(self, chunks: List[Dict]):
        """批量导入文档块到向量库。"""
        if not chunks:
            return

        ids = [f"doc_{i}" for i in range(self.collection.count(), self.collection.count() + len(chunks))]
        documents = [c["content"] for c in chunks]
        metadatas = [{k: v for k, v in c.items() if k != "content"} for c in chunks]

        batch_size = 100
        for i in range(0, len(chunks), batch_size):
            batch_end = min(i + batch_size, len(chunks))
            self.collection.add(
                ids=ids[i:batch_end],
                documents=documents[i:batch_end],
                metadatas=metadatas[i:batch_end],
            )

        logger.info(f"已导入 {len(chunks)} 条文档")

    def search(self, query: str, top_k: int = None) -> List[Dict]:
        """
        语义检索。
        """
        k = top_k or KB_CONFIG["top_k"]
        results = self.collection.query(query_texts=[query], n_results=k)

        docs = []
        if results["ids"] and results["ids"][0]:
            for i in range(len(results["ids"][0])):
                docs.append({
                    "id": results["ids"][0][i],
                    "content": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                    "distance": results["distances"][0][i] if results["distances"] else None,
                })

        logger.debug(f"检索 '{query[:30]}...' 返回 {len(docs)} 条")
        return docs

    def clear(self):
        """清空向量库（重新构建时使用）。"""
        self.client.delete_collection(self.collection_name)
        self._init_collection()
        logger.info("向量库已清空并重建")
