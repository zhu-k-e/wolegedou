"""/kb 接口 - 知识库管理

知识库团队和运维人员使用，用于：
  - 查看知识库状态（Stub / ChromaDB 模式、chunk 数）
  - 导入领域文档（Markdown / TXT / PDF）
  - 测试检索效果（调试用，不经过 LLM）

对接流程（知识库团队）：
  1. 将领域文档放到 data/raw_docs/ 目录
  2. 调用 POST /api/kb/import 导入
  3. 调用 GET /api/kb/search?query=xxx 测试检索效果
  4. 后端所有 Agent 自动通过 get_knowledge_base() 获取真实检索结果
"""

from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from backend.services.knowledge_base import get_knowledge_base
from backend.services.rag.kb_manager import health_check, import_documents, import_file

router = APIRouter()


# ------------------------------------------------------------------
# 请求/响应模型
# ------------------------------------------------------------------


class ImportRequest(BaseModel):
    """导入文档请求"""

    path: str = Field(..., description="文档目录或文件路径（如 data/raw_docs）")
    agent_ids: Optional[list[str]] = Field(
        None, description="手动指定适用的 Agent ID 列表（不传则自动匹配）"
    )


class ImportResponse(BaseModel):
    """导入文档响应"""

    success: bool
    imported_count: int = Field(0, description="本次导入的 chunk 数")
    total_chunks: int = Field(0, description="知识库当前 chunk 总数")
    message: str


class SearchResponse(BaseModel):
    """检索测试响应"""

    query: str
    results: list[dict]
    count: int


# ------------------------------------------------------------------
# 接口
# ------------------------------------------------------------------


@router.get("/kb/health")
async def kb_health():
    """知识库健康检查

    返回当前知识库模式（stub/chromadb）、chunk 数、依赖安装状态。
    用于排查知识库是否正常接入。
    """
    return health_check()


@router.post("/kb/import", response_model=ImportResponse)
async def kb_import(request: ImportRequest) -> ImportResponse:
    """导入文档目录 - 知识库团队准备好领域文档后调用

    递归导入目录下所有 .md / .txt / .pdf 文件。
    每个文档自动切分为 chunk，用 bge-m3 编码后存入 ChromaDB。

    典型用法：
        POST /api/kb/import  {"path": "data/raw_docs"}

    如果知识库为 Stub 模式（依赖未装），会返回 success=false 和提示信息。
    """
    result = import_documents(request.path, request.agent_ids)
    return ImportResponse(**result)


@router.post("/kb/import-file", response_model=ImportResponse)
async def kb_import_file(request: ImportRequest) -> ImportResponse:
    """导入单个文件到知识库

    典型用法：
        POST /api/kb/import-file  {"path": "data/raw_docs/rag_tutorial.md"}
    """
    result = import_file(request.path, request.agent_ids)
    return ImportResponse(**result)


@router.get("/kb/search", response_model=SearchResponse)
async def kb_search(
    query: str = Query(..., description="检索查询文本（如：什么是RAG检索？）"),
    top_k: int = Query(3, ge=1, le=20, description="返回 Top-K 条结果"),
    score_threshold: float = Query(0.6, ge=0.0, le=1.0, description="相似度阈值"),
    filter_agent: Optional[str] = Query(None, description="按 Agent ID 过滤（如 agent_004）"),
) -> SearchResponse:
    """检索测试 - 调试用，不经过 LLM，直接看知识库返回什么

    用于验证：
      1. 知识库是否正常工作
      2. 检索结果是否相关
      3. 跨语言检索效果（中文问题 → 英文文档）

    典型用法：
        GET /api/kb/search?query=什么是RAG&top_k=5
    """
    kb = get_knowledge_base()
    results = await kb.search(
        query,
        top_k=top_k,
        score_threshold=score_threshold,
        filter_agent=filter_agent,
    )

    return SearchResponse(
        query=query,
        results=[
            {
                "chunk_id": r.chunk_id,
                "content": (
                    r.content[:200] + "..." if len(r.content) > 200 else r.content
                ),
                "source": r.source,
                "score": round(r.score, 4),
                "metadata": r.metadata,
            }
            for r in results
        ],
        count=len(results),
    )
