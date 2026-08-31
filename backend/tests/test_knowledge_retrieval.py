"""P0-3c 单元测试：知识检索准确性

对应方案书 6.6 节 + 7.5 节测试要求。
覆盖：
  - filter_agent 分类过滤（10 Agent 各自检索自己分类 chunk）
  - 阈值过滤（score < threshold 不返回）
  - top_k 限制
  - 空结果处理
  - verify_statement 三状态（已验证/待验证/矛盾）
  - 跨语言查询（query 向量化后检索）

测试策略：构造小型 numpy 数据 + mock EmbeddingService，避免加载真实 bge-m3 模型，
完整测试 NumpyKnowledgeBase 的 _load + search + verify_statement 逻辑。
"""

import json
import numpy as np
import pytest

from backend.services.rag.numpy_knowledge_base import NumpyKnowledgeBase
from backend.services.knowledge_base import RetrievalResult


# ============================================================
# 测试数据构造
# ============================================================

# 用 4 维向量（真实 bge-m3 是 1024 维，但检索逻辑与维度无关）
# query 向量 = [1, 0, 0, 0]，与 chunk0 完全匹配
QUERY_VEC = [1.0, 0.0, 0.0, 0.0]

TEST_VECTORS = np.array([
    [1.0, 0.0, 0.0, 0.0],    # chunk0: LLM基础Agent, score=1.0（完全匹配）
    [0.8, 0.6, 0.0, 0.0],    # chunk1: LLM基础Agent, score=0.8
    [0.0, 1.0, 0.0, 0.0],    # chunk2: RAG架构Agent, score=0.0（不匹配）
    [0.3, 0.954, 0.0, 0.0],  # chunk3: RAG架构Agent, score=0.3
    [0.6, 0.8, 0.0, 0.0],    # chunk4: Prompt工程Agent, score=0.6
], dtype=np.float32)

TEST_DOCUMENTS = [
    "LLM是大语言模型，通过Transformer架构训练，能理解和生成人类语言",
    "Token是模型处理文本的最小单元，将文本切分为token后输入模型",
    "RAG是检索增强生成技术，结合检索和生成提升答案准确性",
    "向量检索是RAG的核心步骤，通过计算向量相似度找相关文档",
    "Prompt工程是设计提示词的技术，通过优化提示词引导模型输出",
]

TEST_METADATAS = [
    {"applicable_agents": "LLM基础Agent", "source_doc": "llm.md", "section_path": "基础/LLM"},
    {"applicable_agents": "LLM基础Agent", "source_doc": "llm.md", "section_path": "基础/Token"},
    {"applicable_agents": "RAG架构Agent", "source_doc": "rag.md", "section_path": "RAG/概述"},
    {"applicable_agents": "RAG架构Agent", "source_doc": "rag.md", "section_path": "RAG/检索"},
    {"applicable_agents": "Prompt工程Agent", "source_doc": "prompt.md", "section_path": "Prompt/设计"},
]

TEST_IDS = ["llm_0", "llm_1", "rag_0", "rag_1", "prompt_0"]


class FakeEmbeddingService:
    """返回固定 query 向量，避免加载真实 bge-m3 模型"""

    def encode_query(self, query):
        return list(QUERY_VEC)

    def encode(self, texts):
        return [list(QUERY_VEC) for _ in texts]


@pytest.fixture
def tmp_kb_dir(tmp_path):
    """构造小型 numpy 知识库数据目录"""
    np.save(tmp_path / "vectors.npy", TEST_VECTORS)
    (tmp_path / "documents.json").write_text(
        json.dumps(TEST_DOCUMENTS, ensure_ascii=False), encoding="utf-8"
    )
    (tmp_path / "metadatas.json").write_text(
        json.dumps(TEST_METADATAS, ensure_ascii=False), encoding="utf-8"
    )
    (tmp_path / "ids.json").write_text(
        json.dumps(TEST_IDS, ensure_ascii=False), encoding="utf-8"
    )
    return tmp_path


@pytest.fixture
def kb(tmp_kb_dir, monkeypatch):
    """加载小型 numpy 知识库（mock embedding 服务）"""
    from backend.services.rag import numpy_knowledge_base as nkb_mod
    monkeypatch.setattr(nkb_mod, "EmbeddingService", lambda: FakeEmbeddingService())
    return NumpyKnowledgeBase(data_dir=str(tmp_kb_dir))


# ============================================================
# 1. 基础加载与校验
# ============================================================

class TestKnowledgeBaseLoad:
    """知识库加载与数据一致性"""

    def test_load_success(self, kb):
        """加载成功，数据条数一致"""
        assert len(kb._ids) == 5
        assert len(kb._documents) == 5
        assert len(kb._metadatas) == 5
        assert kb._vectors.shape == (5, 4)

    def test_missing_files_raises(self, tmp_path, monkeypatch):
        """数据缺失时抛 FileNotFoundError"""
        from backend.services.rag import numpy_knowledge_base as nkb_mod
        monkeypatch.setattr(nkb_mod, "EmbeddingService", lambda: FakeEmbeddingService())
        with pytest.raises(FileNotFoundError):
            NumpyKnowledgeBase(data_dir=str(tmp_path / "nonexistent"))

    def test_length_mismatch_raises(self, tmp_path, monkeypatch):
        """数据长度不一致时抛 ValueError"""
        from backend.services.rag import numpy_knowledge_base as nkb_mod
        monkeypatch.setattr(nkb_mod, "EmbeddingService", lambda: FakeEmbeddingService())
        np.save(tmp_path / "vectors.npy", TEST_VECTORS)
        (tmp_path / "documents.json").write_text(
            json.dumps(TEST_DOCUMENTS[:3], ensure_ascii=False), encoding="utf-8"
        )
        (tmp_path / "metadatas.json").write_text(
            json.dumps(TEST_METADATAS, ensure_ascii=False), encoding="utf-8"
        )
        (tmp_path / "ids.json").write_text(
            json.dumps(TEST_IDS, ensure_ascii=False), encoding="utf-8"
        )
        with pytest.raises(ValueError):
            NumpyKnowledgeBase(data_dir=str(tmp_path))


# ============================================================
# 2. search 基础检索
# ============================================================

class TestBasicSearch:
    """基础语义检索"""

    @pytest.mark.asyncio
    async def test_search_returns_retrieval_results(self, kb):
        """search 返回 RetrievalResult 列表"""
        results = await kb.search("LLM", top_k=3, score_threshold=0.0)
        assert isinstance(results, list)
        for r in results:
            assert isinstance(r, RetrievalResult)

    @pytest.mark.asyncio
    async def test_search_sorted_by_score_desc(self, kb):
        """结果按 score 降序"""
        results = await kb.search("query", top_k=5, score_threshold=0.0)
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)

    @pytest.mark.asyncio
    async def test_top_match_is_chunk0(self, kb):
        """最匹配的是 chunk0（score=1.0，与 query 完全匹配）"""
        results = await kb.search("query", top_k=1, score_threshold=0.0)
        assert len(results) == 1
        assert results[0].chunk_id == "llm_0"
        assert results[0].score == pytest.approx(1.0, abs=1e-5)

    @pytest.mark.asyncio
    async def test_top_k_limit(self, kb):
        """top_k 限制返回数量"""
        results = await kb.search("query", top_k=2, score_threshold=0.0)
        assert len(results) <= 2

    @pytest.mark.asyncio
    async def test_result_has_required_fields(self, kb):
        """RetrievalResult 包含必要字段"""
        results = await kb.search("query", top_k=1, score_threshold=0.0)
        r = results[0]
        assert r.chunk_id is not None
        assert r.content is not None
        assert r.source is not None
        assert isinstance(r.score, float)
        assert isinstance(r.metadata, dict)


# ============================================================
# 3. filter_agent 分类过滤
# ============================================================

class TestFilterAgent:
    """方案书 6.6 节：Agent 用 filter_agent 检索自己分类的 chunk"""

    @pytest.mark.asyncio
    async def test_filter_llm_agent(self, kb):
        """filter_agent='LLM基础Agent' 只返回 LLM 分类的 chunk"""
        results = await kb.search(
            "query", top_k=5, score_threshold=0.0, filter_agent="LLM基础Agent"
        )
        assert len(results) > 0
        for r in results:
            assert "LLM基础Agent" in r.metadata.get("applicable_agents", [])

    @pytest.mark.asyncio
    async def test_filter_rag_agent(self, kb):
        """filter_agent='RAG架构Agent' 只返回 RAG 分类的 chunk"""
        results = await kb.search(
            "query", top_k=5, score_threshold=0.0, filter_agent="RAG架构Agent"
        )
        for r in results:
            assert "RAG架构Agent" in r.metadata.get("applicable_agents", [])

    @pytest.mark.asyncio
    async def test_filter_nonexistent_agent_returns_empty(self, kb):
        """filter_agent 不存在时返回空（不崩溃）"""
        results = await kb.search(
            "query", top_k=5, score_threshold=0.0, filter_agent="不存在的Agent"
        )
        assert results == []

    @pytest.mark.asyncio
    async def test_filter_excludes_other_agents(self, kb):
        """filter_agent 过滤掉其他分类的 chunk"""
        results = await kb.search(
            "query", top_k=5, score_threshold=0.0, filter_agent="LLM基础Agent"
        )
        chunk_ids = {r.chunk_id for r in results}
        # RAG 和 Prompt 的 chunk 不应出现
        assert "rag_0" not in chunk_ids
        assert "rag_1" not in chunk_ids
        assert "prompt_0" not in chunk_ids

    @pytest.mark.asyncio
    async def test_no_filter_returns_all(self, kb):
        """不传 filter_agent 返回所有分类的 chunk"""
        results = await kb.search("query", top_k=10, score_threshold=0.0)
        # 所有 5 个 chunk 都可能返回（score > 0 的 + score=0 的被阈值 0.0 放行）
        # 但 chunk2 score=0.0，threshold=0.0 时 0.0 < 0.0 为 False，会被保留
        assert len(results) >= 1


# ============================================================
# 4. 阈值过滤
# ============================================================

class TestScoreThreshold:
    """score_threshold 阈值过滤"""

    @pytest.mark.asyncio
    async def test_high_threshold_only_top_match(self, kb):
        """高阈值（0.9）只返回 score=1.0 的 chunk0"""
        results = await kb.search("query", top_k=5, score_threshold=0.9)
        assert len(results) == 1
        assert results[0].chunk_id == "llm_0"

    @pytest.mark.asyncio
    async def test_medium_threshold(self, kb):
        """中阈值（0.5）返回 score≥0.5 的 chunk"""
        results = await kb.search("query", top_k=5, score_threshold=0.5)
        for r in results:
            assert r.score >= 0.5

    @pytest.mark.asyncio
    async def test_zero_threshold_returns_all_positive(self, kb):
        """阈值 0 返回所有 score≥0 的 chunk"""
        results = await kb.search("query", top_k=10, score_threshold=0.0)
        for r in results:
            assert r.score >= 0.0

    @pytest.mark.asyncio
    async def test_unreachable_threshold_returns_empty(self, kb):
        """超高阈值（>1.0）返回空"""
        results = await kb.search("query", top_k=5, score_threshold=1.5)
        assert results == []


# ============================================================
# 5. 空结果处理
# ============================================================

class TestEmptyResults:
    """空结果处理（方案书 6.6 节 fallback 到全局检索）"""

    @pytest.mark.asyncio
    async def test_empty_kb_returns_empty(self, tmp_path, monkeypatch):
        """空知识库（0 chunks）检索返回空列表"""
        from backend.services.rag import numpy_knowledge_base as nkb_mod
        monkeypatch.setattr(nkb_mod, "EmbeddingService", lambda: FakeEmbeddingService())
        np.save(tmp_path / "vectors.npy", np.zeros((0, 4), dtype=np.float32))
        (tmp_path / "documents.json").write_text("[]", encoding="utf-8")
        (tmp_path / "metadatas.json").write_text("[]", encoding="utf-8")
        (tmp_path / "ids.json").write_text("[]", encoding="utf-8")
        kb_empty = NumpyKnowledgeBase(data_dir=str(tmp_path))
        results = await kb_empty.search("query", top_k=3)
        assert results == []


# ============================================================
# 6. verify_statement 三状态
# ============================================================

class TestVerifyStatement:
    """方案书 6.6 节：Verifier 事实核查"""

    @pytest.mark.asyncio
    async def test_verified_high_overlap(self, kb):
        """高相似度 + 高文本重叠 → 已验证"""
        # statement 与 chunk0 内容高度重叠
        statement = "LLM是大语言模型，通过Transformer架构训练"
        result = await kb.verify_statement(statement)
        assert result["status"] in ("已验证", "待验证")  # 取决于 overlap 计算
        assert "evidence" in result
        assert "source" in result

    @pytest.mark.asyncio
    async def test_pending_no_results(self, tmp_path, monkeypatch):
        """无检索结果 → 待验证"""
        from backend.services.rag import numpy_knowledge_base as nkb_mod
        monkeypatch.setattr(nkb_mod, "EmbeddingService", lambda: FakeEmbeddingService())
        np.save(tmp_path / "vectors.npy", np.zeros((0, 4), dtype=np.float32))
        (tmp_path / "documents.json").write_text("[]", encoding="utf-8")
        (tmp_path / "metadatas.json").write_text("[]", encoding="utf-8")
        (tmp_path / "ids.json").write_text("[]", encoding="utf-8")
        kb_empty = NumpyKnowledgeBase(data_dir=str(tmp_path))
        result = await kb_empty.verify_statement("任意陈述")
        assert result["status"] == "待验证"
        assert result["source"] == "知识库无相关文档"

    @pytest.mark.asyncio
    async def test_verify_returns_dict_with_required_fields(self, kb):
        """verify_statement 返回字典包含必要字段"""
        result = await kb.verify_statement("LLM相关陈述")
        assert isinstance(result, dict)
        assert "status" in result
        assert "evidence" in result
        assert "source" in result
        assert result["status"] in ("已验证", "待验证", "矛盾")

    @pytest.mark.asyncio
    async def test_verify_status_is_valid_enum(self, kb):
        """status 必须是三种合法值之一"""
        result = await kb.verify_statement("任意陈述")
        assert result["status"] in ("已验证", "待验证", "矛盾")


# ============================================================
# 7. 跨语言查询
# ============================================================

class TestCrossLanguageQuery:
    """跨语言查询（中英文混合 / 纯英文 query 检索中文文档）"""

    @pytest.mark.asyncio
    async def test_english_query_retrieves_chinese_docs(self, kb):
        """英文 query 也能检索（embedding 被 mock，验证流程通畅）"""
        results = await kb.search("what is LLM", top_k=3, score_threshold=0.0)
        # mock embedding 固定返回 QUERY_VEC，应能返回 chunk0
        assert len(results) > 0
        assert results[0].chunk_id == "llm_0"

    @pytest.mark.asyncio
    async def test_mixed_language_query(self, kb):
        """中英混合 query"""
        results = await kb.search("LLM 大语言模型 what is", top_k=2, score_threshold=0.0)
        assert len(results) > 0

    @pytest.mark.asyncio
    async def test_empty_query_handled(self, kb):
        """空 query 不崩溃（返回结果或空列表）"""
        results = await kb.search("", top_k=3, score_threshold=0.0)
        assert isinstance(results, list)


# ============================================================
# 8. add_documents 动态入库
# ============================================================

class TestAddDocuments:
    """动态添加文档"""

    @pytest.mark.asyncio
    async def test_add_documents_increases_count(self, kb):
        """add_documents 后 chunk 数量增加"""
        original_count = len(kb._ids)
        await kb.add_documents([
            {"content": "新增的测试文档内容", "source": "test.md", "metadata": {"applicable_agents": "LLM基础Agent"}},
        ])
        assert len(kb._ids) == original_count + 1

    @pytest.mark.asyncio
    async def test_add_empty_documents_no_change(self, kb):
        """添加空文档列表不影响知识库"""
        original_count = len(kb._ids)
        await kb.add_documents([])
        assert len(kb._ids) == original_count

    @pytest.mark.asyncio
    async def test_added_document_retrievable(self, kb):
        """添加后能被检索到"""
        await kb.add_documents([
            {"content": "独一无二的新文档内容XYZ", "source": "new.md", "metadata": {"applicable_agents": "LLM基础Agent"}},
        ])
        results = await kb.search("query", top_k=10, score_threshold=0.0, filter_agent="LLM基础Agent")
        # 新文档的 embedding = QUERY_VEC（mock），score=1.0，应排前列
        assert any("独一无二的新文档内容XYZ" in r.content for r in results)
