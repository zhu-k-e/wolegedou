"""系统配置 Repository

操作 system_config 表，存储α值等全局参数。
"""

import json
from typing import Any, Optional

from backend.db.database import query_one, execute_sql


def get_config(key: str, default: Any = None) -> Any:
    """获取配置值（JSON解析）"""
    row = query_one("SELECT value FROM system_config WHERE key = ?", (key,))
    if row:
        return json.loads(row["value"])
    return default


def set_config(key: str, value: Any):
    """设置配置值（JSON序列化）"""
    execute_sql(
        "INSERT INTO system_config (key, value, updated_at) "
        "VALUES (?, ?, CURRENT_TIMESTAMP) "
        "ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = CURRENT_TIMESTAMP",
        (key, json.dumps(value, ensure_ascii=False), json.dumps(value, ensure_ascii=False)),
    )


def get_alpha() -> float:
    """获取当前α值（调度员遴选权重）"""
    return get_config("alpha", 0.9)


def set_alpha(alpha: float):
    """更新α值"""
    set_config("alpha", alpha)


def get_review_weights() -> dict:
    """获取审核团队权重配置"""
    return get_config("review_weights", {"w1": 0.35, "w2": 0.35, "w3": 0.30})


def get_ema_smooth() -> float:
    """获取EMA平滑系数"""
    return get_config("ema_smooth", 0.8)


def get_importance_snapshot() -> Optional[dict]:
    """获取上一轮importance_score快照（用于早停判断）

    对应方案书 2.4.4 节早停机制
    """
    return get_config("importance_snapshot", None)


def set_importance_snapshot(snapshot: dict):
    """更新importance_score快照"""
    set_config("importance_snapshot", snapshot)


def get_stable_rounds() -> int:
    """获取连续稳定的轮数（用于早停判断）

    对应方案书 2.4.4 节：连续2轮波动<0.05才触发早停
    """
    return get_config("stable_rounds", 0)


def set_stable_rounds(rounds: int):
    """更新连续稳定轮数"""
    set_config("stable_rounds", rounds)
