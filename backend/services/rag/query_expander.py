"""查询扩展器 - 方案书 v7.0 查询扩展

基于术语映射表（term_mapping.py）对用户 query 做扩展，生成多变体：
  1. 原始 query（始终包含）
  2. 中文术语 → 英文替换变体
  3. 英文术语 → 中文替换变体

用于 NumpyKnowledgeBase 的混合检索：
  - BM25 稀疏检索：对每个变体都做检索，合并取最高分（关键词精确匹配）
  - Dense 稠密检索：对多变体编码后取平均向量（语义融合）

核心价值：
  - 中英跨语言检索：用户用中文提问（"大语言模型"），文档中用英文（"LLM"）
  - 缩写展开：用户用缩写（"LoRA"），文档中用全称（"低秩适配"）
  - bge-m3 虽有跨语言能力，但精确术语替换能显著提升 BM25 召回率
"""

from __future__ import annotations

from typing import Optional

from loguru import logger

from backend.services.rag.term_mapping import TermMapping


class QueryExpander:
    """查询扩展器

    用法：
        expander = QueryExpander()
        variants = expander.expand("大语言模型的LoRA微调")
        # → ["大语言模型的LoRA微调",                    # 原始
        #    "LLM的LoRA微调",                          # 大语言模型→LLM
        #    "大语言模型的低秩适配微调",                  # LoRA→低秩适配
        #    "LLM的低秩适配微调"]                        # 两个都替换
    """

    def __init__(self, term_mapping: Optional[TermMapping] = None):
        self._term_mapping = term_mapping or TermMapping()

    @property
    def mapping_size(self) -> int:
        return self._term_mapping.size

    def expand(self, query: str, max_variants: int = 5) -> list[str]:
        """扩展查询，生成变体列表

        策略：
          1. 原始 query（始终第一个）
          2. 逐个术语替换：对 query 中出现的每个术语，生成替换变体
          3. 组合替换：如果有多个术语命中，生成全替换版本

        Args:
            query: 原始查询文本
            max_variants: 最大变体数（含原始），默认 5

        Returns:
            变体列表，第一个始终是原始 query。去重保序。
        """
        if not query or not query.strip():
            return [query] if query else []

        variants: list[str] = [query]
        seen: set[str] = {query}

        # 查找 query 中的术语命中
        hits = self._term_mapping.find_in_query(query)

        if not hits:
            return variants

        # 策略1：逐个术语替换（生成 N 个单替换变体）
        for direction, original, replacement in hits:
            if len(variants) >= max_variants:
                break
            replaced = self._replace_term(query, original, replacement, direction)
            if replaced and replaced not in seen:
                variants.append(replaced)
                seen.add(replaced)

        # 策略2：全替换变体（所有命中术语同时替换）
        if len(hits) > 1 and len(variants) < max_variants:
            full_replaced = query
            for direction, original, replacement in hits:
                full_replaced = self._replace_term(
                    full_replaced, original, replacement, direction
                )
            if full_replaced and full_replaced != query and full_replaced not in seen:
                variants.append(full_replaced)
                seen.add(full_replaced)

        logger.debug(
            f"[QueryExpander] '{query[:40]}' → {len(variants)} 变体: {variants}"
        )
        return variants[:max_variants]

    @staticmethod
    def _replace_term(
        query: str, original: str, replacement: str, direction: str
    ) -> str:
        """在 query 中替换术语

        Args:
            query: 原始查询
            original: 被替换的术语（中文或英文小写）
            replacement: 替换为的术语
            direction: "cn→en" 或 "en→cn"
        """
        if direction == "cn→en":
            # 中文→英文：直接替换（中文无大小写问题）
            return query.replace(original, replacement)
        else:
            # 英文→中文：需要处理大小写
            # 先尝试精确匹配（原始大小写），再尝试小写匹配
            if original in query:
                return query.replace(original, replacement)
            # 小写匹配（query 中的术语可能是大写开头或其他大小写）
            query_lower = query.lower()
            idx = query_lower.find(original)
            if idx >= 0:
                return query[:idx] + replacement + query[idx + len(original):]
            return query

    def expand_for_bm25(self, query: str, max_variants: int = 5) -> list[str]:
        """为 BM25 检索生成扩展变体

        BM25 是精确关键词匹配，术语替换变体能直接命中不同语言的表达。
        与 expand() 相同，但语义上明确用途。
        """
        return self.expand(query, max_variants)

    def expand_for_dense(self, query: str, max_variants: int = 3) -> list[str]:
        """为 Dense 检索生成扩展变体

        Dense 检索（bge-m3）本身有跨语言能力，变体数限制更小（默认 3），
        避免过多变体稀释向量语义。
        """
        return self.expand(query, max_variants)
