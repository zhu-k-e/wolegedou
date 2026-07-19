"""ChromaDB 知识库实现 - 真实 RAG 检索引擎

对应方案书 6.3-6.6 节：
  6.3 知识库来源（10个Agent对应约7000个chunk）
  6.4 跨语言检索（bge-m3，中文问题→英文文档）
  6.5 切分与入库流程
  6.6 检索策略（Top-K=3，Score阈值0.6）

实现 KnowledgeBaseInterface 的三个核心方法：
  - search:           语义检索（学生问题/Agent检索/RAG增强）
  - verify_statement: 知识验证（Verifier事实核查/裁判团溯源标注）
  - add_documents:    文档入库（知识库团队导入领域文档）

技术栈：
  - 向量数据库：ChromaDB（持久化存储，余弦相似度）
  - Embedding：bge-m3（1024维，多语言）
  - 过滤：支持按 applicable_agents 过滤（ChromaDB metadata where 查询）
"""

import hashlib
from typing import Optional

from loguru import logger

from backend.config import get_settings
from backend.services.knowledge_base import KnowledgeBaseInterface, RetrievalResult
from backend.services.rag.document_loader import DocumentChunk
from backend.services.rag.embedding_service import EmbeddingService


class ChromaKnowledgeBase(KnowledgeBaseInterface):
    """ChromaDB 知识库实现

    使用方式：
        kb = ChromaKnowledgeBase()
        await kb.add_documents([{"content": "...", "source": "..."}])
        results = await kb.search("什么是RAG?", top_k=3)

    对接现有系统：
        from backend.services.knowledge_base import set_knowledge_base
        set_knowledge_base(ChromaKnowledgeBase())
        # 之后所有 Agent 通过 get_knowledge_base() 获取此实例
    """

    def __init__(self, collection_name: str = "wolegedou_kb"):
        """初始化 ChromaDB 知识库

        Args:
            collection_name: ChromaDB collection 名称
        """
        self._settings = get_settings()
        self._embedding = EmbeddingService()
        self._collection_name = collection_name
        self._client = None
        self._collection = None
        self._init_chroma()

    def _init_chroma(self):
        """初始化 ChromaDB 客户端和 collection"""
        try:
            import chromadb
        except ImportError as e:
            raise ImportError(
                "ChromaDB 未安装。请执行: pip install chromadb\n"
                "在此之前，知识库将自动降级为 Stub 模式。"
            ) from e

        db_path = str(self._settings.project_root / self._settings.chroma_db_path)
        logger.info(f"初始化 ChromaDB: path={db_path}, collection={self._collection_name}")

        self._client = chromadb.PersistentClient(path=db_path)
        # 使用余弦相似度（bge-m3 向量适合 cosine）
        self._collection = self._client.get_or_create_collection(
            name=self._collection_name,
            metadata={"hnsw:space": "cosine"},
        )

        count = self._collection.count()
        logger.info(f"ChromaDB 就绪: collection={self._collection_name}, 已有 {count} 个 chunk")

    # ------------------------------------------------------------------
    # 接口实现：search
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        top_k: int = 3,
        score_threshold: float = 0.6,
        filter_agent: Optional[str] = None,
    ) -> list[RetrievalResult]:
        """语义检索

        对应方案书 6.6：检索触发时机
          1. Verifier 事实核查
          2. 裁判团溯源标注
          3. Agent RAG 增强（双低触发）

        流程：
          学生问题(中文) → bge-m3 编码 → ChromaDB 余弦检索 → 阈值过滤 → 返回结果
        """
        if self._collection.count() == 0:
            logger.debug("知识库为空，返回空结果")
            return []

        # 1. 编码查询
        query_embedding = self._embedding.encode_query(query)

        # 2. 构建 metadata 过滤条件
        where_clause = None
        if filter_agent:
            # applicable_agents 存为逗号分隔字符串，用 $contains 过滤
            where_clause = {"applicable_agents": {"$contains": filter_agent}}

        # 3. ChromaDB 查询（多取一些，过滤阈值后再截断）
        fetch_k = min(top_k * 3, 20)
        try:
            raw = self._collection.query(
                query_embeddings=[query_embedding],
                n_results=fetch_k,
                where=where_clause,
            )
        except Exception as e:
            logger.error(f"ChromaDB 查询失败: {e}")
            return []

        # 4. 解析结果
        results: list[RetrievalResult] = []
        ids = raw.get("ids", [[]])[0]
        documents = raw.get("documents", [[]])[0]
        metadatas = raw.get("metadatas", [[]])[0]
        distances = raw.get("distances", [[]])[0]

        for i, doc_id in enumerate(ids):
            # cosine space: distance = 1 - similarity → similarity = 1 - distance
            distance = distances[i] if i < len(distances) else 1.0
            score = max(0.0, 1.0 - distance)

            if score < score_threshold:
                continue

            metadata = metadatas[i] if i < len(metadatas) else {}
            # 还原 applicable_agents 为列表
            agents_str = metadata.get("applicable_agents", "")
            metadata["applicable_agents"] = [
                a for a in agents_str.split(",") if a
            ] if agents_str else []

            results.append(
                RetrievalResult(
                    chunk_id=doc_id,
                    content=documents[i] if i < len(documents) else "",
                    source=metadata.get("section_path", metadata.get("source_doc", "未知")),
                    score=score,
                    metadata=metadata,
                )
            )

            if len(results) >= top_k:
                break

        logger.debug(
            f"知识库检索: query='{query[:30]}...', "
            f"filter={filter_agent}, 返回 {len(results)} 条 (阈值={score_threshold})"
        )
        return results

    # ------------------------------------------------------------------
    # 接口实现：verify_statement
    # ------------------------------------------------------------------

    async def verify_statement(
        self,
        statement: str,
        top_k: int = 3,
    ) -> dict:
        """验证知识陈述的正确性

        对应方案书 6.6：
          Verifier 事实核查时对每个 knowledge_refs 条目验证
          裁判团溯源标注时对最终输出逐条标注

        判断逻辑（基于检索结果 + 文本重叠度）：
          1. 无检索结果 → "待验证"
          2. 最高相似度 < 阈值 → "待验证"（知识库中找不到对应内容）
          3. 高相似度 + 高文本重叠 → "已验证"
          4. 高相似度 + 低文本重叠 → "矛盾"（检索到相关但不同的内容）
          5. 中等相似度 → "待验证"

        Returns:
            {
                "status": "已验证" | "待验证" | "矛盾",
                "evidence": [RetrievalResult...],
                "source": "来源文档"
            }
        """
        # 检索相关片段（取 score_threshold=0 以获取所有结果）
        results = await self.search(
            statement, top_k=top_k, score_threshold=0.0
        )

        if not results:
            return {
                "status": "待验证",
                "evidence": [],
                "source": "知识库无相关文档",
            }

        best = results[0]
        threshold = self._settings.kb_score_threshold

        if best.score < threshold:
            # 最高分都低于阈值 → 知识库中找不到对应内容
            return {
                "status": "待验证",
                "evidence": results,
                "source": best.source,
            }

        # 高相似度 → 进一步用文本重叠度判断
        overlap = self._text_overlap(statement, best.content)

        if overlap > 0.3:
            status = "已验证"
        elif overlap < 0.1 and best.score > 0.75:
            # 高相似度但低文本重叠 → 可能矛盾
            # （检索到了高度相关但内容不同的片段，可能是反面论述）
            status = "矛盾"
        else:
            status = "待验证"

        logger.debug(
            f"知识验证: statement='{statement[:30]}...', "
            f"status={status}, best_score={best.score:.3f}, overlap={overlap:.3f}"
        )

        return {
            "status": status,
            "evidence": results,
            "source": best.source,
        }

    # ------------------------------------------------------------------
    # 接口实现：add_documents
    # ------------------------------------------------------------------

    async def add_documents(
        self,
        documents: list[dict],
        agent_ids: Optional[list[str]] = None,
    ) -> int:
        """添加文档到知识库

        Args:
            documents: [{"content": "...", "source": "...", "metadata": {...}}]
            agent_ids: 适用的 Agent ID 列表（覆盖 metadata 中的值）

        Returns:
            添加的 chunk 数量
        """
        if not documents:
            return 0

        chunks: list[DocumentChunk] = []
        for i, doc in enumerate(documents):
            content = doc.get("content", "").strip()
            if not content:
                continue

            metadata = dict(doc.get("metadata", {}))
            source = doc.get("source", metadata.get("source_doc", f"doc_{i}"))

            effective_agents = agent_ids if agent_ids is not None else metadata.get(
                "applicable_agents", []
            )

            chunks.append(
                DocumentChunk(
                    content=content,
                    source=source,
                    metadata={
                        "source_doc": metadata.get("source_doc", source),
                        "section_path": metadata.get("section_path", source),
                        "applicable_agents": effective_agents,
                        "chunk_index": metadata.get("chunk_index", i),
                        "file_type": metadata.get("file_type", "dict"),
                    },
                )
            )

        return self._add_chunks_sync(chunks)

    # ------------------------------------------------------------------
    # 便捷方法：从 DocumentLoader 输出直接导入
    # ------------------------------------------------------------------

    def add_chunks(self, chunks: list[DocumentChunk]) -> int:
        """批量导入 DocumentChunk 列表

        典型用法：
            loader = DocumentLoader()
            chunks = loader.load_from_directory("data/raw_docs")
            kb = ChromaKnowledgeBase()
            count = kb.add_chunks(chunks)

        Args:
            chunks: DocumentLoader 产出的分块列表

        Returns:
            成功导入的 chunk 数量
        """
        return self._add_chunks_sync(chunks)

    def _add_chunks_sync(self, chunks: list[DocumentChunk]) -> int:
        """同步批量入库（内部方法）"""
        if not chunks:
            return 0

        # 1. 批量编码
        contents = [c.content for c in chunks]
        logger.info(f"正在编码 {len(contents)} 个 chunk...")
        embeddings = self._embedding.encode(contents)

        # 2. 构建 ChromaDB 入库数据
        ids = []
        metadatas = []
        for chunk, content in zip(chunks, contents):
            # 用 content hash 作为 ID，避免重复导入
            chunk_id = hashlib.md5(content.encode()).hexdigest()[:16]
            ids.append(chunk_id)

            agents = chunk.metadata.get("applicable_agents", [])
            metadatas.append(
                {
                    "source_doc": chunk.metadata.get("source_doc", ""),
                    "section_path": chunk.metadata.get("section_path", ""),
                    # ChromaDB metadata 不支持 list，存为逗号分隔字符串
                    "applicable_agents": ",".join(agents) if agents else "",
                    "chunk_index": chunk.metadata.get("chunk_index", 0),
                    "file_type": chunk.metadata.get("file_type", ""),
                }
            )

        # 3. 批量入库（ChromaDB upsert，重复 ID 会覆盖）
        batch_size = 100
        total = 0
        for start in range(0, len(ids), batch_size):
            end = start + batch_size
            try:
                self._collection.upsert(
                    ids=ids[start:end],
                    documents=contents[start:end],
                    embeddings=embeddings[start:end],
                    metadatas=metadatas[start:end],
                )
                total += end - start
            except Exception as e:
                logger.error(f"ChromaDB 入库失败 (batch {start}-{end}): {e}")

        logger.info(f"知识库导入完成: {total}/{len(chunks)} 个 chunk")
        return total

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _text_overlap(text_a: str, text_b: str) -> float:
        """计算两段文本的词汇重叠度（Jaccard 相似度）

        用于 verify_statement 判断陈述与检索内容是否一致。
        Jaccard = |A ∩ B| / |A ∪ B|

        Returns:
            0.0-1.0 的重叠度分数
        """
        # 简单分词：中文按字，英文按空格
        import re

        def tokenize(text: str) -> set[str]:
            # 提取英文单词（>=2字符）和中文字符
            words = set(re.findall(r"[a-zA-Z]{2,}", text.lower()))
            chars = set(re.findall(r"[\u4e00-\u9fff]", text))
            return words | chars

        set_a = tokenize(text_a)
        set_b = tokenize(text_b)

        if not set_a or not set_b:
            return 0.0

        intersection = set_a & set_b
        union = set_a | set_b
        return len(intersection) / len(union) if union else 0.0

    @property
    def chunk_count(self) -> int:
        """当前知识库中的 chunk 总数"""
        if self._collection:
            return self._collection.count()
        return 0

    def clear(self):
        """清空知识库（谨慎使用）"""
        if self._client and self._collection:
            self._client.delete_collection(self._collection_name)
            self._collection = self._client.get_or_create_collection(
                name=self._collection_name,
                metadata={"hnsw:space": "cosine"},
            )
            logger.warning(f"知识库已清空: collection={self._collection_name}")
