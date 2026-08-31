"""Embedding 服务 - bge-m3 多语言向量编码

对应方案书 6.4 节：跨语言检索方案（中文问题 -> 英文文档）

技术选型：
  - 主方案：FlagEmbedding.BGEM3FlagModel（方案书推荐，支持稠密+稀疏+多向量）
  - 备选方案：sentence-transformers（更通用，仅稠密检索）
  - 模型懒加载：第一次 encode 时才加载（bge-m3 约 2.2GB）

bge-m3 优势（方案书 6.4.2）：
  - 支持 100+ 语言（中/英/日/韩等），跨语言检索 MTEB Top3
  - 同一模型支持稠密检索、稀疏检索、多向量检索三种模式
  - 本地运行，无 API 成本
"""

import threading
from typing import Optional

from loguru import logger

from backend.config import get_settings


class EmbeddingService:
    """bge-m3 Embedding 服务（线程安全单例）

    特性：
      1. 懒加载：第一次调用 encode() 时才加载模型
      2. 双后端：优先 FlagEmbedding，备选 sentence-transformers
      3. 线程安全：多 Agent 并行检索时共享同一模型实例
      4. 批量编码：支持一次编码多条文本

    向量维度：bge-m3 稠密向量维度为 1024
    """

    _instance: Optional["EmbeddingService"] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized"):
            return
        self._settings = get_settings()
        self._model = None
        self._backend: Optional[str] = None  # "flag" | "st" | None
        self._loaded = False
        self._model_lock = threading.Lock()
        self._initialized = True

    @property
    def model_name(self) -> str:
        return self._settings.embedding_model

    @property
    def backend(self) -> Optional[str]:
        """当前使用的后端：'flag' / 'st' / None"""
        return self._backend

    @property
    def dimension(self) -> int:
        """稠密向量维度（bge-m3 = 1024）"""
        return 1024

    def _resolve_model_path(self) -> str:
        """解析模型加载路径：优先本地缓存目录，否则用 HF hub id

        解决 huggingface_hub 在国内网络下载失败的问题：
        git clone https://hf-mirror.com/BAAI/bge-m3 data/bge_m3_model
        """
        local_path = self._settings.project_root / self._settings.embedding_model_local_path
        # 本地目录存在且包含 config.json 才认为是完整模型
        if local_path.exists() and (local_path / "config.json").exists():
            return str(local_path)
        return self.model_name  # 回退到 "BAAI/bge-m3"（走 HF hub 下载）

    def _load_model(self):
        """加载 bge-m3 模型（懒加载，线程安全）"""
        if self._loaded:
            return

        with self._model_lock:
            if self._loaded:
                return

            model_path = self._resolve_model_path()
            is_local = model_path != self.model_name
            logger.info(
                f"正在加载 Embedding 模型: {model_path}"
                f"{'（本地路径）' if is_local else '（首次加载需下载约 2.2GB）'}"
            )

            # 优先尝试 FlagEmbedding（方案书 6.5 推荐方式）
            try:
                from FlagEmbedding import BGEM3FlagModel

                self._model = BGEM3FlagModel(model_path, use_fp16=True)
                self._backend = "flag"
                self._loaded = True
                logger.info("Embedding 模型加载成功 (后端: FlagEmbedding)")
                return
            except ImportError:
                logger.debug("FlagEmbedding 未安装，尝试 sentence-transformers 后端")
            except Exception as e:
                logger.warning(f"FlagEmbedding 加载失败: {e}，尝试 sentence-transformers")

            # 备选：sentence-transformers
            try:
                from sentence_transformers import SentenceTransformer

                self._model = SentenceTransformer(model_path)
                self._backend = "st"
                self._loaded = True
                logger.info("Embedding 模型加载成功 (后端: sentence-transformers)")
                return
            except ImportError:
                raise ImportError(
                    "Embedding 依赖未安装。请安装以下任一方案：\n"
                    "  方案1 (推荐): pip install FlagEmbedding\n"
                    "  方案2: pip install sentence-transformers\n"
                    "安装后模型会自动下载 (约 2.2GB)。\n"
                    "在此之前，知识库将自动降级为 Stub 模式 (返回空结果)。"
                )
            except Exception as e:
                raise RuntimeError(f"Embedding 模型加载失败: {e}")

    def encode(self, texts: list[str]) -> list[list[float]]:
        """批量编码文本为稠密向量

        Args:
            texts: 待编码文本列表

        Returns:
            稠密向量列表，每个向量维度 1024 (bge-m3)
        """
        if not texts:
            return []

        self._load_model()

        if self._backend == "flag":
            # FlagEmbedding 返回 dict，取 dense_vecs
            output = self._model.encode(texts, batch_size=12, max_length=8192)
            return output["dense_vecs"].tolist()
        else:
            # sentence-transformers 直接返回 numpy 数组
            embeddings = self._model.encode(texts, show_progress_bar=False)
            return embeddings.tolist()

    def encode_query(self, text: str) -> list[float]:
        """编码单条查询文本（用于检索时编码学生问题）

        Args:
            text: 查询文本（可能是中文）

        Returns:
            稠密向量 (1024维)
        """
        return self.encode([text])[0]

    @property
    def is_available(self) -> bool:
        """检查 Embedding 依赖是否可用（不实际加载模型）

        用于 kb_manager 判断是否可以启用真实知识库。
        """
        try:
            import FlagEmbedding  # noqa: F401

            return True
        except ImportError:
            pass
        try:
            import sentence_transformers  # noqa: F401

            return True
        except ImportError:
            return False
