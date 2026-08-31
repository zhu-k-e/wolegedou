"""BM25 稀疏检索器 - 混合检索的稀疏分量

对应方案书 6.6 节：稠密+稀疏混合检索。
方案书推荐 bge-m3 sparse，但预计算 34154 文档的 lexical weights 不现实
（运行时编码几十分钟 + 大缓存文件），改用 BM25 经典稀疏检索：
  - 从 documents.json 构建（几秒），无需额外模型/分词库
  - 字符级分词（中文单字 + 英文词），与 NumpyKnowledgeBase._text_overlap 一致
  - 倒排索引 + BM25 评分（k1=1.5, b=0.75，业界标准）

BM25 优势（补充 dense 检索）：
  - 关键词精确匹配（dense 偏语义，可能漏掉精确术语匹配）
  - 专有名词/缩写召回（如 "RAG", "LoRA", "BM25" 等术语）
  - 跨语言不依赖模型（中文字符级 + 英文词级天然支持）

与 dense 检索通过 RRF（Reciprocal Rank Fusion）融合，见 NumpyKnowledgeBase._hybrid_search。
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Optional

from loguru import logger


class BM25Retriever:
    """BM25 稀疏检索器

    使用方式：
        bm25 = BM25Retriever(documents)              # 构建（几秒）
        results = bm25.search("RAG 架构", top_k=10)  # [(doc_idx, score), ...]

    增量更新：
        bm25.add_documents(["新文档1", "新文档2"])    # 追加文档
    """

    # BM25 参数（业界标准：k1 控制词频饱和，b 控制文档长度归一化）
    K1 = 1.5
    B = 0.75

    def __init__(self, documents: Optional[list[str]] = None):
        """初始化并构建索引

        Args:
            documents: 文档文本列表（与 NumpyKnowledgeBase._documents 对齐）
        """
        # 倒排索引：token -> list of (doc_idx, tf)
        self._postings: dict[str, list[tuple[int, int]]] = {}

        # 文档长度（token 数）
        self._doc_lengths: list[int] = []

        # 统计
        self._num_docs: int = 0
        self._avg_doc_length: float = 0.0

        # IDF 缓存：token -> idf
        self._idf_cache: dict[str, float] = {}

        if documents:
            self._build_index(documents)

    # ------------------------------------------------------------------
    # 分词
    # ------------------------------------------------------------------
    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """字符级分词：中文按单字 + 英文按词（≥2 字符）

        与 NumpyKnowledgeBase._text_overlap 的 tokenize 逻辑一致，
        保证 dense/sparse 检索使用相同的分词口径。

        不依赖 jieba 等分词库，零额外依赖。
        """
        if not text:
            return []
        # 英文：连续字母（≥2 字符），转小写
        words = re.findall(r"[a-zA-Z]{2,}", text.lower())
        # 中文：单个汉字
        chars = re.findall(r"[\u4e00-\u9fff]", text)
        return words + chars

    # ------------------------------------------------------------------
    # 索引构建
    # ------------------------------------------------------------------
    def _build_index(self, documents: list[str]) -> None:
        """从文档列表构建倒排索引"""
        self._postings.clear()
        self._doc_lengths.clear()
        self._idf_cache.clear()
        self._num_docs = 0

        for doc_idx, doc in enumerate(documents):
            self._add_document_to_index(doc_idx, doc)

        self._avg_doc_length = (
            sum(self._doc_lengths) / len(self._doc_lengths)
            if self._doc_lengths
            else 0.0
        )

        # 预计算 IDF
        self._compute_idf()

        logger.info(
            f"[BM25] 索引构建完成: {self._num_docs} docs, "
            f"{len(self._postings)} unique tokens, "
            f"avg_doc_len={self._avg_doc_length:.1f}"
        )

    def _add_document_to_index(self, doc_idx: int, document: str) -> None:
        """将单个文档加入倒排索引"""
        tokens = self._tokenize(document)
        self._doc_lengths.append(len(tokens))
        self._num_docs += 1

        # 统计词频
        tf_counter = Counter(tokens)
        for token, tf in tf_counter.items():
            if token not in self._postings:
                self._postings[token] = []
            self._postings[token].append((doc_idx, tf))

    def _compute_idf(self) -> None:
        """计算每个 token 的 IDF（BM25 变体）

        IDF(token) = log((N - df + 0.5) / (df + 0.5) + 1)

        N = 总文档数，df = 包含该 token 的文档数
        """
        N = self._num_docs
        for token, posting_list in self._postings.items():
            df = len(posting_list)
            # BM25+ IDF（保证非负）
            self._idf_cache[token] = math.log((N - df + 0.5) / (df + 0.5) + 1)

    # ------------------------------------------------------------------
    # 增量更新
    # ------------------------------------------------------------------
    def add_documents(self, documents: list[str]) -> int:
        """追加文档到索引（增量更新 + 重算 IDF）

        Args:
            documents: 新文档文本列表

        Returns:
            添加的文档数
        """
        if not documents:
            return 0

        base_idx = self._num_docs
        for doc in documents:
            self._add_document_to_index(base_idx, doc)
            base_idx += 1

        self._avg_doc_length = (
            sum(self._doc_lengths) / len(self._doc_lengths)
            if self._doc_lengths
            else 0.0
        )
        self._compute_idf()  # N 变了，IDF 需要重算

        logger.debug(f"[BM25] 追加 {len(documents)} docs, 总计 {self._num_docs}")
        return len(documents)

    # ------------------------------------------------------------------
    # 检索
    # ------------------------------------------------------------------
    def search(
        self,
        query: str,
        top_k: int = 10,
        filter_indices: Optional[set[int]] = None,
    ) -> list[tuple[int, float]]:
        """BM25 检索

        Args:
            query: 查询文本
            top_k: 返回前 K 条结果
            filter_indices: 仅在此文档索引集合中检索（用于 filter_agent）

        Returns:
            [(doc_idx, bm25_score), ...] 按 score 降序
        """
        query_tokens = self._tokenize(query)
        if not query_tokens or self._num_docs == 0:
            return []

        # 候选文档：包含至少一个 query token 的文档
        # 统计每个候选文档的 BM25 分数
        candidate_scores: dict[int, float] = {}

        for token in query_tokens:
            posting_list = self._postings.get(token)
            if not posting_list:
                continue

            idf = self._idf_cache.get(token, 0.0)
            if idf <= 0:
                continue  # IDF 为 0 的 token 无贡献

            for doc_idx, tf in posting_list:
                # filter_agent 过滤
                if filter_indices is not None and doc_idx not in filter_indices:
                    continue

                doc_len = self._doc_lengths[doc_idx]
                # BM25 TF 归一化
                tf_norm = tf * (self.K1 + 1) / (
                    tf + self.K1 * (1 - self.B + self.B * doc_len / self._avg_doc_length)
                )
                candidate_scores[doc_idx] = candidate_scores.get(doc_idx, 0.0) + idf * tf_norm

        if not candidate_scores:
            return []

        # 排序取 top_k
        results = sorted(candidate_scores.items(), key=lambda x: -x[1])
        return results[:top_k]

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------
    @property
    def num_docs(self) -> int:
        """索引文档数"""
        return self._num_docs

    @property
    def vocab_size(self) -> int:
        """词表大小"""
        return len(self._postings)

    def get_filter_indices(self, metadatas: list[dict], filter_agent: str) -> set[int]:
        """构建 filter_agent 的文档索引集合

        与 NumpyKnowledgeBase 的 filter_agent 逻辑一致：
        applicable_agents 逗号分隔串，精确匹配。

        Args:
            metadatas: 所有文档的 metadata 列表
            filter_agent: Agent 名称

        Returns:
            符合条件的文档索引集合
        """
        return {
            idx
            for idx, m in enumerate(metadatas)
            if filter_agent in str(m.get("applicable_agents", "") or "").split(",")
        }
