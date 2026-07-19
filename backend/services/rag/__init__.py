"""知识库 RAG 实现包

基于 ChromaDB + BAAI/bge-m3 的知识库实现。
对应方案书第六部分 6.3-6.6 节。

架构概览：
  embedding_service.py    - bge-m3 多语言向量编码（懒加载，双后端）
  document_loader.py      - 文档加载与切分（Markdown/TXT/PDF）
  chroma_knowledge_base.py - ChromaDB 实现 KnowledgeBaseInterface
  kb_manager.py           - 知识库管理（初始化/导入/降级/健康检查）

使用方式：
    # 启动时初始化（自动降级到 Stub 如果依赖未装）
    from backend.services.rag.kb_manager import init_knowledge_base
    init_knowledge_base()

    # 文档来了后批量导入
    from backend.services.rag.kb_manager import import_documents
    count = import_documents("data/raw_docs")
"""
