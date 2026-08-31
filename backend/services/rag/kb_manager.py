"""知识库管理器 - 初始化、降级、导入、健康检查

这是知识库团队与后端的对接入口。

核心功能：
  1. init_knowledge_base() - 启动时初始化（自动降级）
  2. import_documents()    - 批量导入文档（文档来了直接调用）
  3. import_file()         - 导入单个文件
  4. health_check()        - 健康检查（状态/模式/chunk数）

后端选择（config.kb_backend）：
  - auto:  优先 numpy 预计算数据（若 data/numpy_kb 存在），否则 chroma
  - numpy: 强制用预计算向量（知识库同学已向量化好的四件套）
  - chroma: 强制用 ChromaDB（运行时向量化 + 持久化）

降级策略（保证后端始终可运行）：
  - 选定后端 + embedding 依赖可用 → 真实知识库（NumpyKB 或 ChromaKB）
  - 任一依赖缺失 / 数据缺失 / 初始化异常 → StubKnowledgeBase（返回空结果）
"""

import importlib
from pathlib import Path
from typing import Optional

from loguru import logger

from backend.config import get_settings
from backend.services.knowledge_base import (
    StubKnowledgeBase,
    get_knowledge_base,
    set_knowledge_base,
)


# ------------------------------------------------------------------
# 依赖检查
# ------------------------------------------------------------------


def _check_chromadb_available() -> bool:
    """检查 ChromaDB 是否安装"""
    try:
        importlib.import_module("chromadb")
        return True
    except ImportError:
        return False


def _check_embedding_available() -> bool:
    """检查 Embedding 依赖是否可用（FlagEmbedding 或 sentence-transformers）"""
    try:
        importlib.import_module("FlagEmbedding")
        return True
    except ImportError:
        pass
    try:
        importlib.import_module("sentence_transformers")
        return True
    except ImportError:
        return False


def _check_numpy_data_available() -> bool:
    """检查 numpy 预计算数据（四件套）是否存在于 config.kb_numpy_dir"""
    settings = get_settings()
    data_dir = settings.project_root / settings.kb_numpy_dir
    required = ("vectors.npy", "documents.json", "metadatas.json", "ids.json")
    return all((data_dir / f).exists() for f in required)


# ------------------------------------------------------------------
# 初始化（启动时调用）
# ------------------------------------------------------------------


def init_knowledge_base():
    """初始化知识库 - 启动时调用

    根据 config.kb_backend 选择后端：
      auto:  优先 numpy（数据存在），否则 chroma
      numpy: 强制 numpy 预计算数据
      chroma: 强制 ChromaDB

    降级链：
      选定后端 → 不可用 → 另一个后端 → 不可用 → Stub

    此函数不会抛出异常，最差情况就是 Stub 模式。
    """
    settings = get_settings()
    backend = (settings.kb_backend or "auto").lower()
    embedding_ok = _check_embedding_available()

    # 决定后端优先级
    if backend == "numpy":
        backends_to_try = ["numpy"]
    elif backend == "chroma":
        backends_to_try = ["chroma"]
    else:  # auto
        backends_to_try = ["numpy", "chroma"]

    for b in backends_to_try:
        if b == "numpy":
            if _try_init_numpy():
                if not embedding_ok:
                    logger.warning(
                        "[知识库] Embedding 依赖未安装，search/verify 在首次调用时会失败。"
                        " 安装方式: pip install FlagEmbedding (推荐) 或 pip install sentence-transformers"
                    )
                return
        elif b == "chroma":
            if _try_init_chroma():
                if not embedding_ok:
                    logger.warning(
                        "[知识库] Embedding 依赖未安装，search/verify 在首次调用时会失败。"
                        " 安装方式: pip install FlagEmbedding (推荐) 或 pip install sentence-transformers"
                    )
                return

    # 全部失败 → Stub
    logger.warning(
        f"[知识库] 所有后端初始化失败 (尝试过: {backends_to_try}) → 降级为 Stub 模式"
    )
    set_knowledge_base(StubKnowledgeBase())


def _try_init_numpy() -> bool:
    """尝试初始化 NumpyKnowledgeBase，成功返回 True"""
    if not _check_numpy_data_available():
        logger.debug(
            "[知识库] numpy 预计算数据不存在，跳过 numpy 后端"
        )
        return False
    try:
        from backend.services.rag.numpy_knowledge_base import NumpyKnowledgeBase

        kb = NumpyKnowledgeBase()
        set_knowledge_base(kb)
        logger.info(
            f"[知识库] 初始化成功 (Numpy 模式), 当前 chunk 数: {kb.chunk_count}"
        )
        return True
    except Exception as e:
        logger.error(f"[知识库] Numpy 后端初始化失败: {e}")
        return False


def _try_init_chroma() -> bool:
    """尝试初始化 ChromaKnowledgeBase，成功返回 True"""
    if not _check_chromadb_available():
        logger.debug("[知识库] ChromaDB 未安装，跳过 chroma 后端")
        return False
    try:
        from backend.services.rag.chroma_knowledge_base import ChromaKnowledgeBase

        kb = ChromaKnowledgeBase()
        set_knowledge_base(kb)
        logger.info(
            f"[知识库] 初始化成功 (ChromaDB 模式), 当前 chunk 数: {kb.chunk_count}"
        )
        return True
    except Exception as e:
        logger.error(f"[知识库] ChromaDB 初始化失败: {e}")
        return False


# ------------------------------------------------------------------
# 文档导入（文档来了直接调用）
# ------------------------------------------------------------------


def _resolve_safe_path(path: str | Path) -> Path:
    """将导入路径解析为绝对路径，并约束在项目根目录内，防止路径遍历任意文件读取。

    允许项目根目录内的相对/绝对路径；一旦解析结果逃出项目根目录（如 ``../`` 上级目录、
    或绝对路径指向系统目录），抛出 ValueError，调用方据此拒绝导入，loader 不会读取任何文件。
    """
    settings = get_settings()
    root = settings.project_root.resolve()
    p = Path(path)
    resolved = p.resolve() if p.is_absolute() else (root / p).resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError(
            f"导入路径越界：'{path}' 解析为 '{resolved}'，必须在项目目录内"
        )
    return resolved


def import_documents(
    dir_path: str | Path,
    agent_ids: Optional[list[str]] = None,
) -> dict:
    """批量导入目录下所有文档到知识库

    知识库团队准备好领域文档后，调用此函数一键导入。
    支持 Markdown / TXT / PDF。

    Args:
        dir_path: 文档目录路径（如 "data/raw_docs"）
        agent_ids: 手动指定适用的 Agent ID（不传则自动匹配）

    Returns:
        {"success": bool, "imported_count": int, "total_chunks": int, "message": str}
    """
    kb = get_knowledge_base()

    if isinstance(kb, StubKnowledgeBase):
        return {
            "success": False,
            "imported_count": 0,
            "total_chunks": 0,
            "message": "知识库为 Stub 模式，请先安装 chromadb + FlagEmbedding 并重启服务",
        }

    from backend.services.rag.document_loader import DocumentLoader

    try:
        safe_path = _resolve_safe_path(dir_path)
    except ValueError as e:
        return {
            "success": False,
            "imported_count": 0,
            "total_chunks": kb.chunk_count,
            "message": str(e),
        }

    loader = DocumentLoader()
    chunks = loader.load_from_directory(safe_path, agent_ids=agent_ids)

    if not chunks:
        return {
            "success": False,
            "imported_count": 0,
            "total_chunks": kb.chunk_count,
            "message": f"目录 {dir_path} 中没有找到可导入的文档",
        }

    count = kb.add_chunks(chunks)

    return {
        "success": True,
        "imported_count": count,
        "total_chunks": kb.chunk_count,
        "message": f"成功导入 {count} 个 chunk，知识库总计 {kb.chunk_count} 个 chunk",
    }


def import_file(
    file_path: str | Path,
    agent_ids: Optional[list[str]] = None,
) -> dict:
    """导入单个文件到知识库

    Args:
        file_path: 文件路径
        agent_ids: 手动指定适用的 Agent ID

    Returns:
        {"success": bool, "imported_count": int, "total_chunks": int, "message": str}
    """
    kb = get_knowledge_base()

    if isinstance(kb, StubKnowledgeBase):
        return {
            "success": False,
            "imported_count": 0,
            "total_chunks": 0,
            "message": "知识库为 Stub 模式，请先安装依赖并重启服务",
        }

    from backend.services.rag.document_loader import DocumentLoader

    try:
        safe_path = _resolve_safe_path(file_path)
    except ValueError as e:
        return {
            "success": False,
            "imported_count": 0,
            "total_chunks": kb.chunk_count,
            "message": str(e),
        }

    loader = DocumentLoader()
    chunks = loader.load_from_file(safe_path, agent_ids=agent_ids)

    if not chunks:
        return {
            "success": False,
            "imported_count": 0,
            "total_chunks": kb.chunk_count,
            "message": f"文件 {file_path} 没有可导入的内容",
        }

    count = kb.add_chunks(chunks)

    return {
        "success": True,
        "imported_count": count,
        "total_chunks": kb.chunk_count,
        "message": f"成功导入 {count} 个 chunk，知识库总计 {kb.chunk_count} 个 chunk",
    }


# ------------------------------------------------------------------
# 健康检查
# ------------------------------------------------------------------


def health_check() -> dict:
    """知识库健康检查

    Returns:
        {
            "mode": "chromadb" | "stub",
            "chunk_count": int,
            "embedding_backend": "flag" | "st" | null,
            "chromadb_available": bool,
            "embedding_available": bool,
            "message": str,
        }
    """
    kb = get_knowledge_base()
    chromadb_ok = _check_chromadb_available()
    embedding_ok = _check_embedding_available()

    if isinstance(kb, StubKnowledgeBase):
        missing = []
        if not chromadb_ok:
            missing.append("chromadb")
        if not embedding_ok:
            missing.append("FlagEmbedding/sentence-transformers")

        return {
            "mode": "stub",
            "chunk_count": 0,
            "embedding_backend": None,
            "chromadb_available": chromadb_ok,
            "embedding_available": embedding_ok,
            "message": (
                f"Stub 模式（返回空结果）。缺少依赖: {', '.join(missing)}"
                if missing
                else "Stub 模式（初始化异常导致降级）"
            ),
        }

    # 真实后端：区分 numpy / chromadb
    from backend.services.rag.embedding_service import EmbeddingService
    from backend.services.rag.numpy_knowledge_base import NumpyKnowledgeBase

    numpy_data_ok = _check_numpy_data_available()
    chromadb_ok = _check_chromadb_available()

    if isinstance(kb, NumpyKnowledgeBase):
        return {
            "mode": "numpy",
            "chunk_count": kb.chunk_count,
            "embedding_backend": EmbeddingService().backend,
            "numpy_data_available": True,
            "chromadb_available": chromadb_ok,
            "embedding_available": True,
            "data_dir": str(kb.data_dir),
            "message": f"Numpy 模式正常运行，当前 {kb.chunk_count} 个 chunk",
        }

    # ChromaDB 模式
    return {
        "mode": "chromadb",
        "chunk_count": kb.chunk_count,
        "embedding_backend": EmbeddingService().backend,
        "numpy_data_available": numpy_data_ok,
        "chromadb_available": True,
        "embedding_available": True,
        "message": f"ChromaDB 模式正常运行，当前 {kb.chunk_count} 个 chunk",
    }
