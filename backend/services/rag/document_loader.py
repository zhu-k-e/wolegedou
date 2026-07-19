"""文档加载与切分模块

对应方案书 6.5 节：切分与入库流程

流程：
  Step 1: 获取原始文档（Markdown / TXT / PDF）
  Step 2: 按章节切分（保留结构信息）
  Step 3: 每个 chunk 补充元数据（source_doc / section_path / applicable_agents）
  Step 4: （入库由 ChromaKnowledgeBase.add_documents 完成）

切分策略：
  - Markdown：按标题切分（# / ## / ###），保留标题路径作为 section_path
  - TXT：按段落切分，每块默认 800 字符
  - PDF：逐页提取文本，再按段落切分（需 pypdf）

元数据（方案书 6.5 Step 3）：
  - source_doc: 来源文档名
  - section_path: 标题路径（如 "RAG Tutorial > Retrieval > Dense Retrieval"）
  - applicable_agents: 适用的 Agent ID 列表（基于 domain_tags 自动匹配）
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from loguru import logger


@dataclass
class DocumentChunk:
    """文档分块

    一个 chunk 是知识库的最小检索单元。
    """

    content: str  # chunk 文本内容
    source: str  # 来源文档名+章节（如 "LangChain RAG Tutorial > 3. Retrieval"）
    metadata: dict = field(default_factory=dict)
    # metadata 包含：
    #   source_doc: 来源文档名
    #   section_path: 标题路径
    #   applicable_agents: 适用的 Agent ID 列表
    #   chunk_index: 在文档中的序号
    #   file_type: 文件类型


class DocumentLoader:
    """文档加载与切分器

    使用方式：
        loader = DocumentLoader()
        chunks = loader.load_from_file("docs/rag_tutorial.md")
        # 或批量加载目录
        chunks = loader.load_from_directory("data/raw_docs")
    """

    # 默认 chunk 大小（字符数），方案书预计约 7000 个 chunk
    DEFAULT_CHUNK_SIZE = 800
    DEFAULT_CHUNK_OVERLAP = 100

    def __init__(
        self,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    ):
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def load_from_file(
        self,
        path: str | Path,
        agent_ids: Optional[list[str]] = None,
    ) -> list[DocumentChunk]:
        """加载单个文件

        Args:
            path: 文件路径
            agent_ids: 手动指定适用的 Agent ID 列表（不传则自动匹配）

        Returns:
            文档分块列表
        """
        path = Path(path)
        if not path.exists():
            logger.warning(f"文件不存在: {path}")
            return []

        suffix = path.suffix.lower()
        file_type_map = {
            ".md": "markdown",
            ".markdown": "markdown",
            ".txt": "text",
            ".pdf": "pdf",
        }
        file_type = file_type_map.get(suffix)

        if file_type is None:
            logger.warning(f"不支持的文件类型: {suffix} (文件: {path.name})")
            return []

        if file_type == "markdown":
            chunks = self._load_markdown(path, agent_ids)
        elif file_type == "text":
            chunks = self._load_text(path, agent_ids)
        else:
            chunks = self._load_pdf(path, agent_ids)

        logger.info(f"加载文件: {path.name} -> {len(chunks)} 个 chunk")
        return chunks

    def load_from_directory(
        self,
        dir_path: str | Path,
        agent_ids: Optional[list[str]] = None,
        recursive: bool = True,
    ) -> list[DocumentChunk]:
        """批量加载目录下所有支持的文档

        Args:
            dir_path: 目录路径
            agent_ids: 手动指定适用的 Agent ID 列表
            recursive: 是否递归子目录

        Returns:
            所有文档的分块列表（合并）
        """
        dir_path = Path(dir_path)
        if not dir_path.exists():
            logger.warning(f"目录不存在: {dir_path}")
            return []

        supported_exts = {".md", ".markdown", ".txt", ".pdf"}
        all_chunks: list[DocumentChunk] = []

        glob_pattern = "**/*" if recursive else "*"
        for path in sorted(dir_path.glob(glob_pattern)):
            if path.is_file() and path.suffix.lower() in supported_exts:
                chunks = self.load_from_file(path, agent_ids)
                all_chunks.extend(chunks)

        logger.info(f"目录加载完成: {dir_path} -> {len(all_chunks)} 个 chunk")
        return all_chunks

    # ------------------------------------------------------------------
    # 各文件类型加载器
    # ------------------------------------------------------------------

    def _load_markdown(
        self, path: Path, agent_ids: Optional[list[str]]
    ) -> list[DocumentChunk]:
        """加载 Markdown 文件 - 按标题切分

        对应方案书 6.5：使用 MarkdownHeaderTextSplitter 的等效实现
        （不依赖 langchain，自行实现标题切分逻辑）
        """
        text = path.read_text(encoding="utf-8", errors="ignore")
        doc_name = path.stem

        chunks: list[DocumentChunk] = []
        current_section_path: list[str] = []
        current_content: list[str] = []

        chunk_index = 0

        def flush_content():
            nonlocal chunk_index
            content = "\n".join(current_content).strip()
            if not content:
                return

            # 过长的内容按段落二次切分
            sub_chunks = self._split_by_paragraph(content, self._chunk_size)
            section_str = " > ".join(current_section_path) if current_section_path else doc_name

            for sub in sub_chunks:
                effective_agents = agent_ids if agent_ids is not None else self._guess_applicable_agents(
                    doc_name, sub
                )
                chunks.append(
                    DocumentChunk(
                        content=sub,
                        source=f"{doc_name} > {section_str}" if current_section_path else doc_name,
                        metadata={
                            "source_doc": doc_name,
                            "section_path": section_str,
                            "applicable_agents": effective_agents,
                            "chunk_index": chunk_index,
                            "file_type": "markdown",
                        },
                    )
                )
                chunk_index += 1

        for line in text.splitlines():
            # 检测 Markdown 标题行
            header_match = re.match(r"^(#{1,6})\s+(.+)", line)
            if header_match:
                # 先保存上一个标题下的内容
                flush_content()
                current_content = []

                level = len(header_match.group(1))
                title = header_match.group(2).strip()

                # 更新标题路径：只保留当前层级及更高级的标题
                current_section_path = current_section_path[: level - 1]
                current_section_path.append(title)
            else:
                current_content.append(line)

        # 保存最后一段内容
        flush_content()

        return chunks

    def _load_text(
        self, path: Path, agent_ids: Optional[list[str]]
    ) -> list[DocumentChunk]:
        """加载纯文本文件 - 按段落切分"""
        text = path.read_text(encoding="utf-8", errors="ignore")
        doc_name = path.stem

        sub_chunks = self._split_by_paragraph(text, self._chunk_size)
        chunks: list[DocumentChunk] = []

        for i, sub in enumerate(sub_chunks):
            effective_agents = agent_ids if agent_ids is not None else self._guess_applicable_agents(
                doc_name, sub
            )
            chunks.append(
                DocumentChunk(
                    content=sub,
                    source=doc_name,
                    metadata={
                        "source_doc": doc_name,
                        "section_path": doc_name,
                        "applicable_agents": effective_agents,
                        "chunk_index": i,
                        "file_type": "text",
                    },
                )
            )

        return chunks

    def _load_pdf(
        self, path: Path, agent_ids: Optional[list[str]]
    ) -> list[DocumentChunk]:
        """加载 PDF 文件 - 逐页提取

        需要安装 pypdf：pip install pypdf
        """
        try:
            from pypdf import PdfReader
        except ImportError:
            logger.warning(
                f"PDF 解析需要 pypdf，未安装。跳过文件: {path.name}。"
                f"安装方式: pip install pypdf"
            )
            return []

        doc_name = path.stem
        chunks: list[DocumentChunk] = []
        chunk_index = 0

        try:
            reader = PdfReader(str(path))
            for page_num, page in enumerate(reader.pages, 1):
                text = page.extract_text() or ""
                if not text.strip():
                    continue

                sub_chunks = self._split_by_paragraph(text, self._chunk_size)
                for sub in sub_chunks:
                    effective_agents = (
                        agent_ids
                        if agent_ids is not None
                        else self._guess_applicable_agents(doc_name, sub)
                    )
                    chunks.append(
                        DocumentChunk(
                            content=sub,
                            source=f"{doc_name} (p.{page_num})",
                            metadata={
                                "source_doc": doc_name,
                                "section_path": f"{doc_name} > Page {page_num}",
                                "applicable_agents": effective_agents,
                                "chunk_index": chunk_index,
                                "file_type": "pdf",
                                "page": page_num,
                            },
                        )
                    )
                    chunk_index += 1
        except Exception as e:
            logger.error(f"PDF 解析失败: {path.name}: {e}")

        return chunks

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    def _split_by_paragraph(self, text: str, max_size: int) -> list[str]:
        """按段落切分文本，超长段落进一步切分

        策略：
          1. 先按双换行分段
          2. 段落 < max_size → 保留
          3. 段落 >= max_size → 按句号/换行进一步切分，尽量在 max_size 附近断开
          4. 相邻 chunk 有 chunk_overlap 字符重叠（保证上下文连贯）
        """
        paragraphs = re.split(r"\n\s*\n", text.strip())
        paragraphs = [p.strip() for p in paragraphs if p.strip()]

        chunks: list[str] = []
        for para in paragraphs:
            if len(para) <= max_size:
                chunks.append(para)
            else:
                # 超长段落：按句号切分
                sentences = re.split(r"(?<=[。.!！?？\n])\s+", para)
                current = ""
                for sent in sentences:
                    if len(current) + len(sent) <= max_size:
                        current += sent
                    else:
                        if current:
                            chunks.append(current.strip())
                        # 重叠：保留上一块末尾的一部分
                        if chunks and self._chunk_overlap > 0:
                            overlap = chunks[-1][-self._chunk_overlap :]
                            current = overlap + sent
                        else:
                            current = sent
                if current.strip():
                    chunks.append(current.strip())

        return chunks

    def _guess_applicable_agents(self, source: str, content: str) -> list[str]:
        """根据文档名和内容关键词猜测适用的 Agent

        对应方案书 6.5: match_agents(doc_name)

        匹配逻辑：
          遍历所有领域 Agent 的 domain_tags 和 primary_function，
          如果关键词出现在文档名或内容中，则认为该 Agent 适用。

        Args:
            source: 文档名
            content: chunk 内容（只看前 500 字符以提高效率）

        Returns:
            匹配的 Agent ID 列表（空列表表示适用所有 Agent）
        """
        try:
            from backend.agents.agent_registry import get_domain_agents
        except ImportError:
            return []

        text = f"{source} {content[:500]}".lower()
        matched: list[str] = []

        for card in get_domain_agents():
            # 构建 keyword 列表：domain_tags + primary_function
            keywords = [t.lower() for t in card.get("domain_tags", [])]
            keywords.append(card.get("primary_function", "").lower())
            # 去掉空字符串
            keywords = [kw for kw in keywords if kw]

            if any(kw in text for kw in keywords):
                matched.append(card["agent_id"])

        return matched
