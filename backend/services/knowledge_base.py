"""知识库接口 - 与知识库团队的对接边界

知识库由其他团队负责实现（ChromaDB + bge-m3）。
后端通过此接口与知识库交互，不关心具体实现。

知识库团队需实现此接口并注入到DI容器中。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class RetrievalResult:
    """知识库检索结果"""
    chunk_id: str
    content: str
    source: str                    # 来源文档名称+章节
    score: float                   # 相似度分数
    metadata: dict                 # 元数据


# 来源解析时跳过的占位符（知识库同学预处理时未填的字段统一标为"未分类"）
_SOURCE_PLACEHOLDERS = {"", "未分类", "unknown", "None", "null"}


def resolve_source(metadata: dict) -> str:
    """从 chunk metadata 解析展示给学生的来源文档名

    优先级：source_doc（具体文档名）> section_path（章节路径）> source_dir（分类目录）

    知识库同学的预计算数据中 section_path 全为"未分类"占位符，
    直接取会导致溯源标注全显示"未分类"，故遇到占位符时回退到下一优先级字段。
    """
    for key in ("source_doc", "section_path", "source_dir"):
        val = str(metadata.get(key) or "").strip()
        if val and val.lower() not in _SOURCE_PLACEHOLDERS:
            return val
    return "未知"


class KnowledgeBaseInterface(ABC):
    """知识库抽象接口

    知识库团队需继承此类并实现所有抽象方法。
    后端所有Agent通过此接口访问知识库。
    """

    @abstractmethod
    async def search(
        self,
        query: str,
        top_k: int = 3,
        score_threshold: float = 0.6,
        filter_agent: Optional[str] = None,
    ) -> list[RetrievalResult]:
        """语义检索

        Args:
            query: 查询文本（可能是中文，知识库可能是英文，需跨语言检索）
            top_k: 返回Top-K条结果
            score_threshold: 相似度阈值，低于此值的结果不返回
            filter_agent: 仅返回适用于某Agent的文档（基于metadata.applicable_agents）

        Returns:
            检索结果列表，按相似度降序
        """
        ...

    @abstractmethod
    async def verify_statement(
        self,
        statement: str,
        top_k: int = 3,
    ) -> dict:
        """验证某条知识陈述的正确性

        用于Verifier事实核查和裁判团溯源标注。

        Args:
            statement: 待验证的知识陈述
            top_k: 检索Top-K条相关片段

        Returns:
            {
                "status": "已验证" | "待验证" | "矛盾",
                "evidence": [RetrievalResult...],
                "source": "来源文档"
            }
        """
        ...

    @abstractmethod
    async def add_documents(
        self,
        documents: list[dict],
        agent_ids: Optional[list[str]] = None,
    ) -> int:
        """添加文档到知识库

        Args:
            documents: [{"content": "...", "source": "...", "metadata": {...}}]
            agent_ids: 适用的Agent ID列表

        Returns:
            添加的chunk数量
        """
        ...

    @abstractmethod
    def add_chunks(self, chunks: list) -> int:
        """批量导入已分块的文档（DocumentChunk 列表）

        供 kb_manager.import_documents / import_file 调用，与 add_documents 互补：
        add_documents 接收原始文档 dict，add_chunks 接收已切分（DocumentChunk）的列表。
        NumpyKB / ChromaKB 均已实现此方法；新增实现须同时实现两者。
        """
        ...


class StubKnowledgeBase(KnowledgeBaseInterface):
    """知识库Stub实现 - 知识库团队未接入前的占位

    所有检索返回空结果，不报错，确保后端可以独立开发测试。
    """

    async def search(
        self,
        query: str,
        top_k: int = 3,
        score_threshold: float = 0.6,
        filter_agent: Optional[str] = None,
    ) -> list[RetrievalResult]:
        return []

    async def verify_statement(
        self,
        statement: str,
        top_k: int = 3,
    ) -> dict:
        return {
            "status": "待验证",
            "evidence": [],
            "source": "知识库未接入",
        }

    async def add_documents(
        self,
        documents: list[dict],
        agent_ids: Optional[list[str]] = None,
    ) -> int:
        return 0

    def add_chunks(self, chunks: list) -> int:
        # Stub 模式不持久化，导入在 import_documents/import_file 中已提前返回
        return 0


# 全局知识库实例（默认为Stub，知识库团队接入后替换）
_kb_instance: Optional[KnowledgeBaseInterface] = None


def get_knowledge_base() -> KnowledgeBaseInterface:
    """获取知识库实例"""
    global _kb_instance
    if _kb_instance is None:
        _kb_instance = StubKnowledgeBase()
    return _kb_instance


def set_knowledge_base(kb: KnowledgeBaseInterface):
    """注入知识库实现（知识库团队调用此方法接入）"""
    global _kb_instance
    _kb_instance = kb
