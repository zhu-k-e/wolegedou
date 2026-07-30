"""Numpy 知识库实现 - 预计算向量直接检索

对接知识库同学的预计算产物（bge-m3 + numpy 四件套）：
  vectors.npy      —— (N, 1024) float32, 已 L2 归一化
  documents.json   —— List[str]      chunk 原文
  metadatas.json   —— List[dict]      元数据
  ids.json         —— List[str]       chunk ID

实现 KnowledgeBaseInterface，与 ChromaKnowledgeBase 互为替代。
所有 Agent 通过 get_knowledge_base() 透明访问，不感知后端差异。

检索逻辑：
  query 文本 → EmbeddingService.encode_query → L2 归一化 →
  点积（=cosine，因 doc 向量已归一化）→ filter_agent 过滤 →
  阈值过滤 → top_k → list[RetrievalResult]

优势：
  - 免 ChromaDB 依赖
  - 免运行时向量化（数据已预计算）
  - 3.4 万规模 numpy 点积几毫秒
  - 复用 EmbeddingService 保证 query/doc 向量空间一致（同一 bge-m3）

对应方案书 6.3-6.6 节。
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Optional

import numpy as np
from loguru import logger

from backend.config import get_settings
from backend.services.knowledge_base import (
    KnowledgeBaseInterface,
    RetrievalResult,
    resolve_source,
)
from backend.services.rag.bm25_retriever import BM25Retriever
from backend.services.rag.embedding_service import EmbeddingService
from backend.services.rag.query_expander import QueryExpander


class NumpyKnowledgeBase(KnowledgeBaseInterface):
    """Numpy 预计算向量知识库

    使用方式：
        kb = NumpyKnowledgeBase()                       # 从 config.kb_numpy_dir 加载
        kb = NumpyKnowledgeBase(data_dir="path/to/kb")  # 指定目录

    对接系统：
        from backend.services.knowledge_base import set_knowledge_base
        set_knowledge_base(NumpyKnowledgeBase())
        # 之后所有 Agent 通过 get_knowledge_base() 获取此实例
    """

    REQUIRED_FILES = ("vectors.npy", "documents.json", "metadatas.json", "ids.json")

    def __init__(self, data_dir: Optional[str | Path] = None):
        """初始化并加载预计算数据

        Args:
            data_dir: numpy 四件套目录。None 时用 config.kb_numpy_dir（相对项目根）。
        """
        self._settings = get_settings()
        self._embedding = EmbeddingService()

        if data_dir is None:
            data_dir = self._settings.project_root / self._settings.kb_numpy_dir
        self._data_dir = Path(data_dir)

        # 内存数据
        self._vectors: Optional[np.ndarray] = None  # (N, 1024) float32, 已归一化
        self._documents: list[str] = []
        self._metadatas: list[dict] = []
        self._ids: list[str] = []
        self._bm25: Optional[BM25Retriever] = None
        self._query_expander: Optional[QueryExpander] = None

        # BM25 稀疏检索器（混合检索用，方案书 6.6 节）
        self._bm25: Optional[BM25Retriever] = None

        self._load()

    # ------------------------------------------------------------------
    # 加载
    # ------------------------------------------------------------------
    def _load(self) -> None:
        """从磁盘加载四件套并校验一致性"""
        missing = [f for f in self.REQUIRED_FILES if not (self._data_dir / f).exists()]
        if missing:
            raise FileNotFoundError(
                f"numpy 知识库数据缺失: {missing}，期望目录: {self._data_dir}"
            )

        vectors = np.load(self._data_dir / "vectors.npy", allow_pickle=False)
        documents = _load_json(self._data_dir / "documents.json")
        metadatas = _load_json(self._data_dir / "metadatas.json")
        ids = _load_json(self._data_dir / "ids.json")

        # 校验长度一致
        n = vectors.shape[0]
        if not (len(documents) == len(metadatas) == len(ids) == n):
            raise ValueError(
                f"数据长度不一致: vectors={n}, documents={len(documents)}, "
                f"metadatas={len(metadatas)}, ids={len(ids)}"
            )

        # 确保是 float32 + C-contiguous（点积更快）
        vectors = np.ascontiguousarray(vectors, dtype=np.float32)
        if vectors.ndim != 2:
            raise ValueError(f"vectors 必须是 2D 矩阵，实际 ndim={vectors.ndim}")

        # ── 过滤非中英文语言 chunk ──
        # source_doc 含 _ar- / _ar_ 的是阿拉伯语翻译页（如 Prompt Engineering Guide_ar-pages_...
        # 或 Transformers 文档_ar_...），对中文查询是纯噪声。一并过滤日、韩等其他非中英文。
        keep_mask = [
            not _is_non_cn_source(m.get("source_doc", ""))
            for m in metadatas
        ]
        kept = sum(keep_mask)
        dropped = n - kept
        if dropped > 0:
            keep_mask = np.array(keep_mask, dtype=bool)
            vectors = vectors[keep_mask]
            documents = [documents[i] for i, k in enumerate(keep_mask) if k]
            metadatas = [metadatas[i] for i, k in enumerate(keep_mask) if k]
            ids = [ids[i] for i, k in enumerate(keep_mask) if k]
            logger.info(
                f"[NumpyKB] 过滤掉 {dropped} 个非中英文 chunk "
                f"(阿拉伯语/日语/韩语等主语言), 保留 {kept}"
            )

            # 重新校验
            n = vectors.shape[0]
            if not (len(documents) == len(metadatas) == len(ids) == n):
                raise ValueError(
                    f"过滤后数据长度不一致: vectors={n}, documents={len(documents)}, "
                    f"metadatas={len(metadatas)}, ids={len(ids)}"
                )

        # 确保是 float32 + C-contiguous（点积更快）
        vectors = np.ascontiguousarray(vectors, dtype=np.float32)
        if vectors.ndim != 2:
            raise ValueError(f"vectors 必须是 2D 矩阵，实际 ndim={vectors.ndim}")

        self._vectors = vectors
        self._documents = list(documents)
        self._metadatas = list(metadatas)
        self._ids = [str(i) for i in ids]

        logger.info(
            f"[NumpyKB] 加载完成: {n} chunks, dim={vectors.shape[1]}, "
            f"dir={self._data_dir}"
        )

        # 构建 BM25 索引（方案书 6.6 节：稠密+稀疏混合检索）
        if self._settings.kb_hybrid_search:
            try:
                self._bm25 = BM25Retriever(self._documents)
            except Exception as e:
                logger.warning(f"[NumpyKB] BM25 索引构建失败，降级为纯稠密: {e}")
                self._bm25 = None

        # 初始化查询扩展器（方案书 v7.0：查询扩展+术语映射表）
        if self._settings.kb_query_expansion:
            try:
                self._query_expander = QueryExpander()
                logger.info(
                    f"[NumpyKB] 查询扩展已启用: {self._query_expander.mapping_size} 条术语映射"
                )
            except Exception as e:
                logger.warning(f"[NumpyKB] 查询扩展器初始化失败，降级为无扩展: {e}")
                self._query_expander = None

    # ------------------------------------------------------------------
    # 查询扩展辅助方法（方案书 v7.0）
    # ------------------------------------------------------------------
    def _encode_query_expanded(self, query: str) -> np.ndarray:
        """查询扩展 + 编码 → 归一化向量

        策略（方案书 v7.0 查询扩展+术语映射表）：
          - 查询扩展关闭或无扩展时：直接编码原始 query
          - 查询扩展开启时：对多变体编码取平均，融合中英术语语义

        bge-m3 虽有跨语言能力，但术语替换变体能补充语义信号，
        对中英混合 query（如"大语言模型的LoRA微调"）效果更佳。
        """
        if not self._settings.kb_query_expansion or self._query_expander is None:
            return self._encode_single_query(query)

        variants = self._query_expander.expand_for_dense(query, max_variants=3)
        if len(variants) <= 1:
            return self._encode_single_query(query)

        # 多变体编码 + 平均 + 重新归一化
        vecs = [self._encode_single_query(v) for v in variants]
        avg_vec = np.mean(vecs, axis=0)
        norm = np.linalg.norm(avg_vec)
        if norm > 0:
            avg_vec = avg_vec / norm

        logger.debug(
            f"[NumpyKB] 查询扩展(dense): '{query[:30]}' → {len(variants)} 变体平均"
        )
        return avg_vec

    def _encode_single_query(self, query: str) -> np.ndarray:
        """编码单个 query → 归一化向量"""
        vec = self._embedding.encode_query(query)
        vec = np.asarray(vec, dtype=np.float32)
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec

    def _bm25_search_expanded(
        self,
        query: str,
        top_k: int,
        filter_indices: Optional[set[int]] = None,
    ) -> list[tuple[int, float, int]]:
        """BM25 查询扩展检索 → [(idx, score, rank), ...]

        对每个扩展变体做 BM25 检索，合并结果（同一 doc 取最高 BM25 分），
        然后按分数排序取 top_k。

        BM25 是精确关键词匹配，术语替换变体能直接命中不同语言的表达，
        这是查询扩展价值最大的环节。
        """
        if not self._settings.kb_query_expansion or self._query_expander is None:
            results = self._bm25.search(
                query, top_k=top_k, filter_indices=filter_indices
            )
            return [(idx, score, rank) for rank, (idx, score) in enumerate(results)]

        variants = self._query_expander.expand_for_bm25(query, max_variants=5)

        # 对每个变体做 BM25 检索，合并取最高分
        bm25_best: dict[int, float] = {}
        for v in variants:
            v_results = self._bm25.search(
                v, top_k=top_k, filter_indices=filter_indices
            )
            for idx, score in v_results:
                if idx not in bm25_best or score > bm25_best[idx]:
                    bm25_best[idx] = score

        # 按最高 BM25 分排序
        sorted_results = sorted(bm25_best.items(), key=lambda x: -x[1])[:top_k]
        return [(idx, score, rank) for rank, (idx, score) in enumerate(sorted_results)]

    # ------------------------------------------------------------------
    # search
    # ------------------------------------------------------------------
    async def search(
        self,
        query: str,
        top_k: int = 3,
        score_threshold: float = 0.6,
        filter_agent: Optional[str] = None,
    ) -> list[RetrievalResult]:
        """语义检索（对应方案书 6.6：检索触发时机）

        根据配置自动选择检索策略：
          - 混合检索（kb_hybrid_search=True）：dense(bge-m3) + sparse(BM25) → RRF 融合
          - 纯稠密检索（降级模式）：bge-m3 cosine

        Args:
            query: 查询文本
            top_k: 返回 Top-K 条结果
            score_threshold: 相似度阈值（混合模式下 dense 候选用此过滤，
                             sparse 候选不受限，RRF 融合后取 top_k）
            filter_agent: 仅返回适用于某 Agent 的文档
        """
        if self._vectors is None or len(self._ids) == 0:
            return []

        # 混合检索：BM25 索引就绪 + 配置启用
        if self._settings.kb_hybrid_search and self._bm25 is not None:
            return await self._hybrid_search(query, top_k, score_threshold, filter_agent)
        else:
            return await self._dense_search(query, top_k, score_threshold, filter_agent)

    async def _dense_search(
        self,
        query: str,
        top_k: int = 3,
        score_threshold: float = 0.6,
        filter_agent: Optional[str] = None,
    ) -> list[RetrievalResult]:
        """纯稠密检索（bge-m3 cosine）

        流程：query → bge-m3 编码 → L2 归一化 →
              点积(=cosine) → filter_agent 过滤 → 阈值过滤 → top_k
        """
        # 1. 编码 query（含查询扩展，方案书 v7.0）→ L2 归一化
        query_vec = self._encode_query_expanded(query)

        # 2. 点积 = cosine（双方都归一化）
        scores = self._vectors @ query_vec  # (N,)

        # 3. filter_agent 过滤：applicable_agents 逗号分隔串，精确匹配
        if filter_agent:
            mask = np.array(
                [
                    filter_agent in str(m.get("applicable_agents", "") or "").split(",")
                    for m in self._metadatas
                ],
                dtype=bool,
            )
            scores = np.where(mask, scores, -np.inf)

        # 4. 取 top_k 候选（多取一些以应对阈值过滤）
        fetch_k = min(max(top_k * 3, top_k), len(scores))
        if fetch_k <= 0:
            return []

        candidate_idx = np.argpartition(-scores, fetch_k - 1)[:fetch_k]
        candidate_idx = candidate_idx[np.argsort(-scores[candidate_idx])]

        # 5. 阈值过滤 + 构建 RetrievalResult
        results: list[RetrievalResult] = []
        for idx in candidate_idx:
            score = float(scores[idx])
            if score < score_threshold:
                continue

            metadata = dict(self._metadatas[idx])
            agents_str = metadata.get("applicable_agents", "")
            metadata["applicable_agents"] = (
                [a for a in str(agents_str).split(",") if a] if agents_str else []
            )

            results.append(
                RetrievalResult(
                    chunk_id=self._ids[idx],
                    content=self._documents[idx],
                    source=resolve_source(metadata),
                    score=score,
                    metadata=metadata,
                )
            )

            if len(results) >= top_k:
                break

        logger.debug(
            f"[NumpyKB] dense_search: query='{query[:30]}...', filter={filter_agent}, "
            f"返回 {len(results)} 条 (阈值={score_threshold})"
        )
        return results

    async def _hybrid_search(
        self,
        query: str,
        top_k: int = 3,
        score_threshold: float = 0.6,
        filter_agent: Optional[str] = None,
    ) -> list[RetrievalResult]:
        """混合检索：dense(bge-m3) + sparse(BM25) → RRF 融合

        对应方案书 6.6 节：稠密+稀疏混合模式，提升跨语言召回率。

        策略：
          1. Dense 检索 → 取 top fetch_k，过 score_threshold 的进入 RRF dense 排名
          2. Sparse(BM25) 检索 → 取 top fetch_k，BM25>0 的进入 RRF sparse 排名
          3. RRF 融合：score = 1/(k+rank_dense) + 1/(k+rank_sparse)
          4. 按 RRF score 取 top_k

        RetrievalResult.score 仍用 dense cosine（保持接口语义），
        metadata.hybrid 记录 RRF 详情供调试。
        """
        # 1. Dense 检索（含查询扩展，方案书 v7.0）
        query_vec = self._encode_query_expanded(query)
        dense_scores = self._vectors @ query_vec  # (N,)

        # 2. filter_agent 过滤（dense + sparse 共用）
        filter_indices = None
        if filter_agent:
            filter_indices = self._bm25.get_filter_indices(
                self._metadatas, filter_agent
            )
            mask = np.array(
                [idx in filter_indices for idx in range(len(self._metadatas))],
                dtype=bool,
            )
            dense_scores = np.where(mask, dense_scores, -np.inf)

        # 3. Dense top fetch_k（过 score_threshold 的进入 RRF）
        fetch_k = min(max(top_k * 5, top_k), len(dense_scores))
        if fetch_k <= 0:
            return []

        candidate_idx = np.argpartition(-dense_scores, fetch_k - 1)[:fetch_k]
        candidate_idx = candidate_idx[np.argsort(-dense_scores[candidate_idx])]

        dense_ranked: list[tuple[int, float, int]] = []  # (idx, score, rank)
        for rank, idx in enumerate(candidate_idx):
            score = float(dense_scores[idx])
            if score >= score_threshold:
                dense_ranked.append((int(idx), score, rank))

        # 4. Sparse (BM25) top fetch_k（含查询扩展，方案书 v7.0）
        sparse_ranked = self._bm25_search_expanded(
            query, top_k=fetch_k, filter_indices=filter_indices
        )

        # 5. RRF 融合
        rrf_k = self._settings.kb_rrf_k
        rrf_scores: dict[int, float] = {}

        for idx, _, rank in dense_ranked:
            rrf_scores[idx] = rrf_scores.get(idx, 0.0) + 1.0 / (rrf_k + rank + 1)
        for idx, _, rank in sparse_ranked:
            rrf_scores[idx] = rrf_scores.get(idx, 0.0) + 1.0 / (rrf_k + rank + 1)

        if not rrf_scores:
            logger.debug(
                f"[NumpyKB] hybrid_search: query='{query[:30]}...', "
                f"dense={len(dense_ranked)}, sparse={len(sparse_ranked)}, 返回 0 条"
            )
            return []

        # 6. 按 RRF score 排序，取 top_k
        sorted_results = sorted(rrf_scores.items(), key=lambda x: -x[1])[:top_k]

        # 7. 构建 RetrievalResult
        dense_rank_map = {idx: rank for idx, _, rank in dense_ranked}
        sparse_rank_map = {idx: rank for idx, _, rank in sparse_ranked}

        results: list[RetrievalResult] = []
        for idx, rrf_score in sorted_results:
            # display score 用 dense cosine（保持接口语义）
            display_score = float(dense_scores[idx])
            if display_score == -np.inf or display_score < 0:
                display_score = 0.0

            metadata = dict(self._metadatas[idx])
            agents_str = metadata.get("applicable_agents", "")
            metadata["applicable_agents"] = (
                [a for a in str(agents_str).split(",") if a] if agents_str else []
            )
            # 混合检索调试信息
            metadata["hybrid"] = {
                "rrf_score": round(rrf_score, 6),
                "dense_rank": dense_rank_map.get(idx),
                "sparse_rank": sparse_rank_map.get(idx),
                "dense_score": round(display_score, 4),
            }

            results.append(
                RetrievalResult(
                    chunk_id=self._ids[idx],
                    content=self._documents[idx],
                    source=resolve_source(metadata),
                    score=display_score,
                    metadata=metadata,
                )
            )

        logger.debug(
            f"[NumpyKB] hybrid_search: query='{query[:30]}...', filter={filter_agent}, "
            f"dense={len(dense_ranked)}, sparse={len(sparse_ranked)}, "
            f"返回 {len(results)} 条 (RRF k={rrf_k})"
        )
        return results

    # ------------------------------------------------------------------
    # verify_statement
    # ------------------------------------------------------------------
    async def verify_statement(
        self,
        statement: str,
        top_k: int = 3,
    ) -> dict:
        """验证知识陈述的正确性

        判断逻辑（与 ChromaKnowledgeBase 一致）：
          1. 无检索结果 → "待验证"
          2. 最高相似度 < 阈值 → "待验证"
          3. 高相似度 + 高文本重叠 → "已验证"
          4. 高相似度 + 低文本重叠 → "矛盾"
          5. 中等相似度 → "待验证"
        """
        # 取 score_threshold=0 获取所有结果（但仍会过滤 -inf，即 filter 排除项）
        results = await self.search(statement, top_k=top_k, score_threshold=0.0)

        if not results:
            return {
                "status": "待验证",
                "evidence": [],
                "source": "知识库无相关文档",
            }

        best = results[0]
        threshold = self._settings.kb_score_threshold

        # 转 dict 列表：RetrievalResult 是 dataclass，不能直接 JSON 序列化
        # （WebSocket 推送 / 日志 / model_dump 都会崩）
        evidence = [
            {
                "chunk_id": r.chunk_id,
                "content": r.content,
                "source": r.source,
                "score": r.score,
                "metadata": r.metadata,
            }
            for r in results
        ]

        if best.score < threshold:
            return {
                "status": "待验证",
                "evidence": evidence,
                "source": best.source,
            }

        # 高语义相似度（过了阈值）→ 进一步用文本重叠度辅助判断
        overlap = self._text_overlap(statement, best.content)

        # 判断逻辑（best_score 为主判据，overlap 仅用于识别"矛盾"）：
        # - best_score >= threshold（0.6）：bge-m3 语义相关，默认"已验证"
        # - 例外：best_score > 0.75 且 overlap < 0.02 → "矛盾"
        #   （语义高度相似但文本几乎不重叠，可能是 LLM 编造的看似相关内容）
        #
        # 原 logic 要求 overlap > 0.3 才判"已验证"，但 _text_overlap 用 Jaccard
        # 相似度（中文按单字集合），对"短陈述 vs 长 chunk"场景天然偏低
        # （陈述20字、chunk200字，Jaccard 必然小），导致几乎所有陈述都"待验证"。
        # 改为以 best_score 为主，避免 Jaccard 对长短文本对比的偏差。
        if best.score > 0.75 and overlap < 0.02:
            status = "矛盾"
        else:
            status = "已验证"

        logger.debug(
            f"[NumpyKB] verify: statement='{statement[:30]}...', "
            f"status={status}, best_score={best.score:.3f}, overlap={overlap:.3f}"
        )

        return {
            "status": status,
            "evidence": evidence,
            "source": best.source,
        }

    # ------------------------------------------------------------------
    # add_documents
    # ------------------------------------------------------------------
    async def add_documents(
        self,
        documents: list[dict],
        agent_ids: Optional[list[str]] = None,
    ) -> int:
        """添加文档到知识库

        编码后追加到内存。如需持久化，调用 persist()。

        Args:
            documents: [{"content": "...", "source": "...", "metadata": {...}}]
            agent_ids: 适用的 Agent ID 列表（覆盖 metadata 中的值）

        Returns:
            添加的 chunk 数量
        """
        return self._add_documents_sync(documents, agent_ids)

    def add_chunks(self, chunks: list) -> int:
        """同步批量导入 DocumentChunk 列表

        兼容 ChromaKnowledgeBase.add_chunks 接口，供 kb_manager.import_documents
        / import_file 调用。Agent 代码无需改动即可在两种后端间切换。

        Args:
            chunks: DocumentLoader 产出的分块列表（DocumentChunk）

        Returns:
            成功导入的 chunk 数量
        """
        documents = [
            {"content": c.content, "source": c.source, "metadata": c.metadata}
            for c in chunks
        ]
        return self._add_documents_sync(documents, agent_ids=None)

    def _add_documents_sync(
        self,
        documents: list[dict],
        agent_ids: Optional[list[str]] = None,
    ) -> int:
        """同步入库核心逻辑（编码 + 追加到内存）"""
        if not documents:
            return 0

        contents: list[str] = []
        metas: list[dict] = []
        ids: list[str] = []
        for i, doc in enumerate(documents):
            content = doc.get("content", "").strip()
            if not content:
                continue

            metadata = dict(doc.get("metadata", {}))
            source = doc.get("source", metadata.get("source_doc", f"doc_{i}"))

            effective_agents = (
                agent_ids
                if agent_ids is not None
                else metadata.get("applicable_agents", [])
            )
            if isinstance(effective_agents, list):
                agents_str = ",".join(effective_agents)
            else:
                agents_str = str(effective_agents or "")

            metadata.setdefault("source_doc", source)
            metadata.setdefault("section_path", source)
            metadata["applicable_agents"] = agents_str
            metadata.setdefault("chunk_index", i)

            # chunk_id：优先用 metadata 里的，否则用 content hash
            chunk_id = metadata.get("chunk_hash") or hashlib.md5(
                content.encode()
            ).hexdigest()[:16]

            contents.append(content)
            metas.append(metadata)
            ids.append(chunk_id)

        if not contents:
            return 0

        # 编码（EmbeddingService 懒加载 bge-m3）
        logger.info(f"[NumpyKB] 编码 {len(contents)} 个新 chunk...")
        embeddings = self._embedding.encode(contents)  # list[list[float]]
        new_vectors = np.asarray(embeddings, dtype=np.float32)

        # L2 归一化（保证跟现有向量空间一致）
        norms = np.linalg.norm(new_vectors, axis=1, keepdims=True)
        norms = np.where(norms > 0, norms, 1.0)
        new_vectors = new_vectors / norms

        # 维度校验
        if self._vectors is not None and new_vectors.shape[1] != self._vectors.shape[1]:
            raise ValueError(
                f"向量维度不一致: 现有 {self._vectors.shape[1]}, "
                f"新增 {new_vectors.shape[1]}"
            )

        # 追加
        if self._vectors is None:
            self._vectors = new_vectors
        else:
            self._vectors = np.vstack([self._vectors, new_vectors])
        self._documents.extend(contents)
        self._metadatas.extend(metas)
        self._ids.extend(ids)

        # 同步更新 BM25 索引（混合检索用）
        if self._bm25 is not None:
            self._bm25.add_documents(contents)

        logger.info(
            f"[NumpyKB] 追加 {len(contents)} 个 chunk, 总计 {len(self._ids)} 个"
        )
        return len(contents)

    def persist(self, target_dir: Optional[str | Path] = None) -> Path:
        """把当前内存数据写回磁盘（同 numpy 四件套格式）

        add_documents 后如需保留新增数据，调用此方法。

        Args:
            target_dir: 目标目录，None 时写回 self._data_dir
        """
        if self._vectors is None:
            raise RuntimeError("无数据可持久化")

        out = Path(target_dir) if target_dir else self._data_dir
        out.mkdir(parents=True, exist_ok=True)
        np.save(out / "vectors.npy", self._vectors.astype(np.float32))
        _dump_json(out / "documents.json", self._documents)
        _dump_json(out / "metadatas.json", self._metadatas)
        _dump_json(out / "ids.json", self._ids)
        logger.info(
            f"[NumpyKB] 持久化完成: {len(self._ids)} chunks → {out}"
        )
        return out

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------
    @staticmethod
    def _text_overlap(text_a: str, text_b: str) -> float:
        """计算两段文本的词汇重叠度（Jaccard 相似度）

        与 ChromaKnowledgeBase._text_overlap 实现一致，
        用于 verify_statement 判断陈述与检索内容是否一致。
        """
        def tokenize(text: str) -> set[str]:
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
        return len(self._ids)

    @property
    def data_dir(self) -> Path:
        """数据目录"""
        return self._data_dir

    @property
    def dimension(self) -> int:
        """向量维度"""
        if self._vectors is None or self._vectors.size == 0:
            return 0
        return int(self._vectors.shape[1])


# ------------------------------------------------------------------
# JSON 读写工具
# ------------------------------------------------------------------
def _is_non_cn_source(source_doc: str) -> bool:
    """判断 source_doc 是否为非中英文主语言文档

    过滤规则（可在 _load 中按需调整）：
      - source_doc 含 _ar-pages_ 或 _ar_ → 阿拉伯语翻译页
      - source_doc 含 _ja_ 或 _jp_ → 日语翻译页
      - source_doc 含 _ko_ → 韩语翻译页
      - source_doc 含 _ru_ → 俄语翻译页

    注意：英文 .ipynb.md（Jupyter notebook 转 md）**保留**——这些是英文 AI 教程
    （如 Google GenAI Best Practices 关于 RAG/语义检索），与领域强相关，对中文学生的
    跨语言检索也有价值，不应整批删除。
    """
    if not source_doc:
        return False
    source_lower = source_doc.lower()
    non_cn_patterns = (
        "_ar-pages_", "_ar_",
        "_ja_", "_jp_",
        "_ko_",
        "_ru_",
    )
    for pat in non_cn_patterns:
        if pat in source_lower:
            return True
    return False


def _load_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _dump_json(path: Path, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
