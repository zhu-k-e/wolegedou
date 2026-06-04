"""
文档加载器。
负责从各种格式（Markdown/PDF/TXT/HTML）加载文档，统一转为结构化文本块。
"""

import os
from pathlib import Path
from typing import List, Dict
from loguru import logger


class DocumentLoader:
    """
    加载并切分领域知识文档。

    支持的格式：
    - .md  (Markdown)
    - .txt (纯文本)
    - .py  (Python代码，可作为实操素材)
    更多格式（PDF/HTML）在P2阶段扩展
    """

    def __init__(self, chunk_size: int = 800, chunk_overlap: int = 100):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def load_file(self, file_path: str) -> str:
        """加载单个文件的文本内容。"""
        path = Path(file_path)
        suffix = path.suffix.lower()

        if suffix in (".md", ".txt", ".py"):
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read()
        else:
            logger.warning(f"不支持的格式: {suffix}，跳过 {file_path}")
            return ""

    def chunk_text(self, text: str, source: str = "") -> List[Dict]:
        """
        将长文本按 chunk_size 切分，保留 overlap 确保跨块连贯。
        """
        if not text.strip():
            return []

        chunks = []
        start = 0
        text_len = len(text)

        while start < text_len:
            end = start + self.chunk_size
            chunk_content = text[start:end]
            chunks.append({
                "content": chunk_content,
                "source": source,
                "chunk_index": len(chunks),
                "start_char": start,
                "end_char": min(end, text_len),
            })
            start = end - self.chunk_overlap

        return chunks

    def load_directory(self, dir_path: str) -> List[Dict]:
        """
        加载目录下所有支持的文档，统一切分返回。
        """
        all_chunks = []
        path = Path(dir_path)

        if not path.exists():
            logger.error(f"目录不存在: {dir_path}")
            return all_chunks

        supported = [".md", ".txt", ".py"]
        files = [f for f in path.rglob("*") if f.suffix.lower() in supported]

        logger.info(f"扫描到 {len(files)} 个文档，开始加载...")

        for f in files:
            text = self.load_file(str(f))
            if text:
                chunks = self.chunk_text(text, source=str(f.name))
                all_chunks.extend(chunks)
                logger.debug(f"  {f.name}: {len(chunks)} 个块, {len(text)} 字符")

        logger.info(f"文档加载完成，共 {len(all_chunks)} 个文本块")
        return all_chunks
