"""SQLite 数据库连接管理

P1-5: 改为线程级连接复用，避免每次操作都 open/close。
- 同一线程同一数据库路径复用同一个 Connection
- 启用 WAL 模式提升并发读写性能
- 提供 close_all() 用于应用关闭时清理

注意：sqlite3.Connection 默认 check_same_thread=True，不能跨线程使用。
本实现用 threading.local 保证每个线程独立持有连接，线程安全。
"""

import sqlite3
import threading
from pathlib import Path
from typing import Optional

from loguru import logger

from backend.config import get_settings


# 线程本地存储：每个线程独立持有 {db_path_str: sqlite3.Connection}
_local = threading.local()


def _get_thread_cache() -> dict[str, sqlite3.Connection]:
    """获取当前线程的连接缓存字典"""
    if not hasattr(_local, "connections"):
        _local.connections = {}
    return _local.connections


def get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """获取SQLite连接（线程级复用）

    同一线程对同一数据库路径的多次调用会返回同一个 Connection 对象，
    避免高频操作时反复 open/close 的开销。

    Args:
        db_path: 数据库路径，为None时使用配置中的默认路径

    Returns:
        sqlite3.Connection，设置 row_factory=Row 以支持字典式访问
    """
    settings = get_settings()
    path = Path(db_path) if db_path else settings.db_full_path

    # 确保父目录存在
    path.parent.mkdir(parents=True, exist_ok=True)

    cache_key = str(path)
    cache = _get_thread_cache()

    # 命中缓存则直接复用
    cached = cache.get(cache_key)
    if cached is not None:
        try:
            # 轻量探活：执行无副作用语句，连接已被关闭则重建
            cached.execute("SELECT 1")
            return cached
        except sqlite3.ProgrammingError:
            # 连接已关闭，清理后重建
            logger.debug(f"连接已失效，重建: {cache_key}")
            cache.pop(cache_key, None)

    # 新建连接
    conn = sqlite3.connect(str(path), check_same_thread=True)
    conn.row_factory = sqlite3.Row
    # 启用外键约束
    conn.execute("PRAGMA foreign_keys = ON")
    # 启用 WAL 模式：提升并发读写性能（读写不互斥）
    try:
        conn.execute("PRAGMA journal_mode = WAL")
    except sqlite3.OperationalError as e:
        logger.warning(f"启用 WAL 模式失败（不影响功能）: {e}")
    # WAL 模式下忙等待 5 秒，减少 SQLITE_BUSY 错误
    conn.execute("PRAGMA busy_timeout = 5000")

    cache[cache_key] = conn
    logger.debug(f"新建 SQLite 连接: {cache_key}")
    return conn


def execute_sql(sql: str, params: tuple = (), db_path: Optional[str] = None) -> sqlite3.Cursor:
    """执行单条SQL语句（连接复用，不主动关闭）"""
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(sql, params)
        conn.commit()
        return cursor
    except Exception:
        conn.rollback()
        raise


def query_one(sql: str, params: tuple = (), db_path: Optional[str] = None) -> Optional[sqlite3.Row]:
    """查询单行（连接复用，不主动关闭）"""
    conn = get_connection(db_path)
    return conn.execute(sql, params).fetchone()


def query_all(sql: str, params: tuple = (), db_path: Optional[str] = None) -> list[sqlite3.Row]:
    """查询多行（连接复用，不主动关闭）"""
    conn = get_connection(db_path)
    return conn.execute(sql, params).fetchall()


def close_all():
    """关闭当前线程持有的所有连接（应用关闭时调用）"""
    cache = _get_thread_cache()
    for path_key, conn in list(cache.items()):
        try:
            conn.close()
            logger.debug(f"已关闭连接: {path_key}")
        except Exception as e:
            logger.warning(f"关闭连接失败: {path_key}, {e}")
    cache.clear()
