"""Agent卡片 + Agent表现 Repository

操作 agent_cards 和 agent_performance 两张表。
"""

import json
from typing import Optional

from backend.db.database import query_one, query_all, execute_sql


def get_agent_card(agent_id: str) -> Optional[dict]:
    """获取Agent卡片信息"""
    row = query_one(
        "SELECT * FROM agent_cards WHERE agent_id = ?",
        (agent_id,),
    )
    if row:
        return _row_to_card(row)
    return None


def get_all_active_agents() -> list[dict]:
    """获取所有active状态的Agent卡片"""
    rows = query_all("SELECT * FROM agent_cards WHERE status = 'active'")
    return [_row_to_card(r) for r in rows]


def get_agent_performance(agent_id: str, function_tag: str) -> Optional[dict]:
    """获取某Agent在某function_tag下的表现数据"""
    row = query_one(
        "SELECT * FROM agent_performance WHERE agent_id = ? AND function_tag = ?",
        (agent_id, function_tag),
    )
    return dict(row) if row else None


def get_agent_all_performances(agent_id: str) -> list[dict]:
    """获取某Agent所有function_tag下的表现数据"""
    rows = query_all(
        "SELECT * FROM agent_performance WHERE agent_id = ?",
        (agent_id,),
    )
    return [dict(r) for r in rows]


def update_agent_performance(
    agent_id: str,
    function_tag: str,
    accuracy: float,
    count: int,
    rework_rate: float,
    importance_score: float,
    is_suspended: bool = False,
):
    """更新Agent表现数据"""
    execute_sql(
        """
        UPDATE agent_performance
        SET accuracy = ?, count = ?, rework_rate = ?,
            importance_score = ?, is_suspended = ?, updated_at = CURRENT_TIMESTAMP
        WHERE agent_id = ? AND function_tag = ?
        """,
        (accuracy, count, rework_rate, importance_score, is_suspended, agent_id, function_tag),
    )


def suspend_agent_tag(agent_id: str, function_tag: str):
    """暂停某Agent在某function_tag下的候选资格"""
    execute_sql(
        "UPDATE agent_performance SET is_suspended = 1, updated_at = CURRENT_TIMESTAMP "
        "WHERE agent_id = ? AND function_tag = ?",
        (agent_id, function_tag),
    )


def get_total_task_count() -> int:
    """获取全系统总任务记录数（所有agent所有function_tag的count之和）

    用于α动态切换判断（方案书§2.4.2：数据积累后自动降α）
    """
    row = query_one("SELECT COALESCE(SUM(count), 0) AS total FROM agent_performance")
    return row["total"] if row else 0


def _row_to_card(row) -> dict:
    """将数据库行转换为Agent卡片dict"""
    return {
        "agent_id": row["agent_id"],
        "agent_name": row["agent_name"],
        "primary_function": row["primary_function"],
        "secondary_functions": json.loads(row["secondary_functions"]),
        "domain_tags": json.loads(row["domain_tags"]),
        "status": row["status"],
    }
