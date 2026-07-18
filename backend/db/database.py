"""SQLite 数据库连接管理"""

import sqlite3
from pathlib import Path
from typing import Optional

from loguru import logger

from backend.config import get_settings


def get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """获取SQLite连接

    Args:
        db_path: 数据库路径，为None时使用配置中的默认路径

    Returns:
        sqlite3.Connection，设置 row_factory=Row 以支持字典式访问
    """
    settings = get_settings()
    path = Path(db_path) if db_path else settings.db_full_path

    # 确保父目录存在
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    # 启用外键约束
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def execute_sql(sql: str, params: tuple = (), db_path: Optional[str] = None) -> sqlite3.Cursor:
    """执行单条SQL语句"""
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(sql, params)
        conn.commit()
        return cursor
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def query_one(sql: str, params: tuple = (), db_path: Optional[str] = None) -> Optional[sqlite3.Row]:
    """查询单行"""
    conn = get_connection(db_path)
    try:
        return conn.execute(sql, params).fetchone()
    finally:
        conn.close()


def query_all(sql: str, params: tuple = (), db_path: Optional[str] = None) -> list[sqlite3.Row]:
    """查询多行"""
    conn = get_connection(db_path)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()
