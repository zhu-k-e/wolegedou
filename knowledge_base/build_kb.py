"""
知识库构建脚本。
使用方法：
    python -m knowledge_base.build_kb --dir ./data
将 data 目录下所有 .md/.txt/.py 文件导入向量库。
"""

import argparse
from pathlib import Path
from .document_loader import DocumentLoader
from .vector_store import VectorStore
from loguru import logger


def build_knowledge_base(data_dir: str, clear_first: bool = False):
    """
    构建知识库。

    Args:
        data_dir: 原始文档目录
        clear_first: 是否先清空已有数据
    """
    path = Path(data_dir)
    if not path.exists():
        logger.error(f"数据目录不存在: {data_dir}")
        logger.info(f"请在 {data_dir} 目录下放入以下类型的文档：")
        logger.info("  - .md  (Markdown 文档)")
        logger.info("  - .txt (纯文本文档)")
        logger.info("  - .py  (Python 代码)")
        return

    loader = DocumentLoader()
    store = VectorStore()

    if clear_first:
        store.clear()

    chunks = loader.load_directory(str(path))
    store.add_documents(chunks)

    logger.info(f"知识库构建完成！共入库 {len(chunks)} 个文本块")
    logger.info(f"存储位置: {store.client._path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="构建领域知识库")
    parser.add_argument("--dir", default="./data", help="原始文档目录")
    parser.add_argument("--clear", action="store_true", help="清空已有数据后重建")
    args = parser.parse_args()

    build_knowledge_base(args.dir, args.clear)
