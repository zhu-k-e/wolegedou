"""全局配置模块 - 从环境变量加载所有配置项"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """系统全局配置，从 .env 文件自动加载"""

    model_config = SettingsConfigDict(
        env_file=".env",
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
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o"

    # 低档模型
    openai_mini_model: str = "gpt-4o-mini"

    # --- 数据库 ---
    db_path: str = "data/wolegedou.db"

    # --- 向量知识库 ---
    chroma_db_path: str = "data/chroma_db"
    embedding_model: str = "BAAI/bge-m3"
    kb_top_k: int = 3
    kb_score_threshold: float = 0.6

    # --- 服务 ---
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = True
    log_level: str = "DEBUG"

    # --- 贡献记忆 ---
    ema_smooth: float = 0.8
    alpha_initial: float = 0.9
    elimination_threshold: float = 0.5
    elimination_consecutive_count: int = 3

    # --- 超时 ---
    llm_timeout: int = 30
    fsm_max_revisions: int = 2

    @property
    def db_full_path(self) -> Path:
        """数据库文件的绝对路径"""
        return Path(self.db_path).resolve()

    @property
    def project_root(self) -> Path:
        """项目根目录"""
        return Path(__file__).resolve().parent.parent


@lru_cache
def get_settings() -> Settings:
    """获取全局配置单例"""
    return Settings()
