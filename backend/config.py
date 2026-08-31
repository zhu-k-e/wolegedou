"""全局配置模块 - 从环境变量加载所有配置项"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """系统全局配置，从 .env 文件自动加载"""

    model_config = SettingsConfigDict(
        # 用绝对路径定位项目根的 .env，避免因 CWD 不同读到 backend/.env 导致两份配置不一致
        env_file=Path(__file__).resolve().parent.parent / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- LLM API配置 ---
    # 中档模型
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-chat"

    # 高档模型
    openai_api_key: str = ""
    openai_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    openai_model: str = "qwen-max"

    # 低档模型
    openai_mini_model: str = "qwen-turbo"

    # --- 数据库 ---
    db_path: str = "data/wolegedou.db"

    # --- 向量知识库 ---
    chroma_db_path: str = "data/chroma_db"
    embedding_model: str = "BAAI/bge-m3"
    kb_top_k: int = 3
    kb_score_threshold: float = 0.6
    kb_docs_path: str = "data/raw_docs"           # 领域文档原始目录（队友放的文档）
    kb_collection_name: str = "wolegedou_kb"       # ChromaDB collection 名

    # numpy 预计算向量知识库（知识库同学直接给向量化产物时用）
    # auto: 优先 numpy（若数据存在），否则 chroma
    # numpy: 强制用 numpy 预计算数据（data/kb_numpy_dir）
    # chroma: 强制用 ChromaDB（走运行时向量化 + 持久化）
    kb_backend: str = "auto"
    kb_numpy_dir: str = "data/numpy_kb"            # numpy 四件套目录（vectors.npy 等）

    # 混合检索（方案书 6.6 节：稠密+稀疏混合模式）
    # True: dense(bge-m3 cosine) + sparse(BM25) → RRF 融合
    # False: 纯稠密检索（降级模式）
    kb_hybrid_search: bool = True
    kb_rrf_k: int = 60                             # RRF 融合参数 k（业界默认 60）

    # 查询扩展（方案书 v7.0：查询扩展+术语映射表）
    # True: 对 query 做术语映射扩展，生成多变体提升跨语言检索召回率
    # BM25 对每个变体检索取最高分；dense 对多变体编码取平均向量
    kb_query_expansion: bool = True

    # bge-m3 模型本地缓存目录
    # 首次通过 git clone https://hf-mirror.com/BAAI/bge-m3 下载到此处
    # 加载时优先使用本地路径，避免 huggingface_hub 在国内下载失败
    embedding_model_local_path: str = "data/bge_m3_model"

    # --- 服务 ---
    host: str = "127.0.0.1"
    port: int = 8000
    debug: bool = False
    log_level: str = "INFO"

    # --- 贡献记忆 ---
    ema_smooth: float = 0.8
    alpha_initial: float = 0.9
    elimination_threshold: float = 0.5
    elimination_consecutive_count: int = 3

    # --- 超时 ---
    # 必须 >= max_tokens / 模型输出速度下限。域Agent候选生成/聚焦用 max_tokens=4096，
    # 按 30~60 token/s 需 68~136s；曾误设为 30s，导致长输出必然超时抛异常（整段丢失，
    # 非截断），触发资源包整体降级。配合 llm_client 的 max_retries=1，最坏 120×2=240s。
    llm_timeout: int = 120
    fsm_max_revisions: int = 2

    # --- CORS / 安全 ---
    # 逗号分隔的允许源列表，留空则用默认 localhost 白名单
    cors_origins: list[str] = []
    # 简单 API Key 认证（空字符串=不启用；启用后客户端需带 X-API-Key 头）
    api_key: str = ""
    # 每个客户端每分钟最大请求数（0=不限流）
    rate_limit_per_minute: int = 60

    # --- 数据合规（方案书 7.4 节）---
    # 对话历史保留天数，过期自动清除
    conversation_retention_days: int = 30

    # --- 离线演示缓存（附录 E）---
    # 启用后 /api/ask 优先查 demo_cache 表，命中则不走 LLM
    demo_cache_enabled: bool = False

    @property
    def db_full_path(self) -> Path:
        """数据库文件的绝对路径

        相对路径统一锚定到项目根（project_root），避免 server 从不同启动目录
        （项目根 vs backend/）运行时落到两份不同的 DB，导致指标脚本读不到
        实时 demo 数据。绝对路径行为不变。
        """
        p = Path(self.db_path)
        if not p.is_absolute():
            p = self.project_root / p
        return p.resolve()

    @property
    def project_root(self) -> Path:
        """项目根目录"""
        return Path(__file__).resolve().parent.parent


@lru_cache
def get_settings() -> Settings:
    """获取全局配置单例"""
    return Settings()
