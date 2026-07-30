"""pytest 配置和共享fixtures"""

import pytest
import tempfile
import os
from pathlib import Path

from backend.config import get_settings

# 手动运行的联调脚本不被 pytest 收集
collect_ignore = ["test_llm_connectivity.py", "test_real_e2e.py", "debug_candidate.py"]


@pytest.fixture(scope="session", autouse=True)
def setup_test_env():
    """测试环境设置：使用临时数据库"""
    # 使用临时数据库
    tmp_dir = tempfile.mkdtemp(prefix="wolegedou_test_")
    db_path = os.path.join(tmp_dir, "test.db")

    # 覆盖配置
    settings = get_settings()
    settings.db_path = db_path

    # 初始化数据库
    from backend.db.init_db import init_database
    init_database()

    yield

    # 清理
    import shutil
    shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest.fixture
def sample_profile_data():
    """测试用学情画像数据"""
    return {
        "knowledge_level": "中级",
        "background": "有Python基础",
        "current_goal": "项目落地",
        "question_type": "操作步骤",
        "domain_hint": ["RAG", "LangChain"],
        "complexity_estimate": "跨领域",
        "intent_type": "generation",
        "domain_confidence": {"RAG": "high", "LangChain": "low"},
        "test_results": [],
    }


@pytest.fixture
def sample_focused_output_data():
    """测试用聚焦输出数据"""
    return {
        "conclusion": "RAG查询效果优化需要从检索策略和Prompt设计双维度入手",
        "reasoning_steps": [
            "检查当前检索参数配置，特别是top_k和chunk_size",
            "优化Prompt模板，增加上下文引导",
            "使用reranker对检索结果重排序",
        ],
        "knowledge_refs": [
            {"source": "LangChain官方文档 - RAG章节", "content_summary": "RAG检索参数调优指南"}
        ],
        "applicable_conditions": "适用于基于LangChain的RAG系统，需要Python基础",
        "code_example": "retriever = vectorstore.as_retriever(search_kwargs={'k': 5})",
        "difficulty_note": "中级适配，需要理解向量检索基础概念",
    }
