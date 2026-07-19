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
from backend.services.knowledge_base import KnowledgeBaseInterface, RetrievalResult
from backend.services.rag.embedding_service import EmbeddingService


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

        self._vectors = vectors
        self._documents = list(documents)
        self._metadatas = list(metadatas)
        self._ids = [str(i) for i in ids]

        logger.info(
            f"[NumpyKB] 加载完成: {n} chunks, dim={vectors.shape[1]}, "
            f"dir={self._data_dir}"
        )

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
        """语义检索

        对应方案书 6.6：检索触发时机
          1. Verifier 事实核查
          2. 裁判团溯源标注
          3. Agent RAG 增强（双低触发）

        流程：
          query(中文) → bge-m3 编码 → L2 归一化 →
          点积(=cosine) → filter_agent 过滤 → 阈值过滤 → top_k
        """
        if self._vectors is None or len(self._ids) == 0:
            return []

        # 1. 编码 query → L2 归一化（doc 向量已归一化，归一化后点积=cosine）
        query_vec = self._embedding.encode_query(query)  # list[float]
        query_vec = np.asarray(query_vec, dtype=np.float32)
        norm = np.linalg.norm(query_vec)
        if norm > 0:
            query_vec = query_vec / norm

        # 2. 点积 = cosine（双方都归一化）
        scores = self._vectors @ query_vec  # (N,)

        # 3. filter_agent 过滤：applicable_agents 逗号分隔串，精确匹配
        #    （跟 ChromaKB 的 $contains 在实际数据上等价，但更准确——
        #     避免 agent id 互为子串时误匹配）
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

        # argpartition 快速取前 fetch_k（O(N)），再排序
        candidate_idx = np.argpartition(-scores, fetch_k - 1)[:fetch_k]
        candidate_idx = candidate_idx[np.argsort(-scores[candidate_idx])]

        # 5. 阈值过滤 + 构建 RetrievalResult
        results: list[RetrievalResult] = []
        for idx in candidate_idx:
            score = float(scores[idx])
            if score < score_threshold:
                continue  # 低于阈值或被 filter 排除（-inf）

            metadata = dict(self._metadatas[idx])
            # 还原 applicable_agents 为 list（跟 ChromaKB 一致）
            agents_str = metadata.get("applicable_agents", "")
            metadata["applicable_agents"] = (
                [a for a in str(agents_str).split(",") if a] if agents_str else []
            )

            results.append(
                RetrievalResult(
                    chunk_id=self._ids[idx],
                    content=self._documents[idx],
                    source=metadata.get(
                        "section_path", metadata.get("source_doc", "未知")
                    ),
                    score=score,
                    metadata=metadata,
                )
            )

            if len(results) >= top_k:
                break

        logger.debug(
            f"[NumpyKB] search: query='{query[:30]}...', filter={filter_agent}, "
            f"返回 {len(results)} 条 (阈值={score_threshold})"
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

        if best.score < threshold:
            return {
                "status": "待验证",
                "evidence": results,
                "source": best.source,
            }

        overlap = self._text_overlap(statement, best.content)

        if overlap > 0.3:
            status = "已验证"
        elif overlap < 0.1 and best.score > 0.75:
            status = "矛盾"
        else:
            status = "待验证"

        logger.debug(
            f"[NumpyKB] verify: statement='{statement[:30]}...', "
            f"status={status}, best_score={best.score:.3f}, overlap={overlap:.3f}"
        )

        return {
            "status": status,
            "evidence": results,
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
def _load_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _dump_json(path: Path, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
