"""贡献记忆 Repository

操作 contribution_memory, elimination_log, student_feedback, offline_evaluation_queue 表。
"""

from typing import Optional

from backend.db.database import query_one, query_all, execute_sql


# ============================================================
# 贡献记忆
# ============================================================

def save_contribution_memory(
    task_id: str,
    agent_id: str,
    function_tag: str,
    task_type: str,
    segment: Optional[str],
    review_score: float,
    importance_score: float,
    referee_verdict: str,
    referee_modifications: int = 0,
    rework_type: str = "none",
):
    """记录一次任务中某Agent的贡献记忆"""
    execute_sql(
        """
        INSERT INTO contribution_memory
            (task_id, agent_id, function_tag, task_type, segment,
             review_score, importance_score, referee_verdict,
             referee_modifications, rework_type)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (task_id, agent_id, function_tag, task_type, segment,
         review_score, importance_score, referee_verdict,
         referee_modifications, rework_type),
    )


def get_recent_importance_scores(
    agent_id: str, function_tag: str, limit: int = 3
) -> list[float]:
    """获取最近N次的importance_score（用于淘汰判定）"""
    rows = query_all(
        """
        SELECT importance_score FROM contribution_memory
        WHERE agent_id = ? AND function_tag = ?
        ORDER BY created_at DESC LIMIT ?
        """,
        (agent_id, function_tag, limit),
    )
    return [r["importance_score"] for r in rows]


# ============================================================
# 淘汰日志
# ============================================================

def log_elimination(agent_id: str, function_tag: Optional[str], reason: str):
    """记录淘汰信息"""
    execute_sql(
        "INSERT INTO elimination_log (agent_id, function_tag, reason) VALUES (?, ?, ?)",
        (agent_id, function_tag, reason),
    )


def restore_agent(agent_id: str, function_tag: Optional[str]):
    """恢复被淘汰的Agent"""
    execute_sql(
        "UPDATE elimination_log SET restored_at = CURRENT_TIMESTAMP "
        "WHERE agent_id = ? AND function_tag = ? AND restored_at IS NULL",
        (agent_id, function_tag),
    )


# ============================================================
# 学生反馈
# ============================================================

def save_student_feedback(
    session_id: str,
    agent_id: str,
    function_tag: str,
    feedback_type: str,
    comment: Optional[str] = None,
):
    """保存学生反馈"""
    execute_sql(
        """
        INSERT INTO student_feedback
            (session_id, agent_id, function_tag, feedback_type, comment)
        VALUES (?, ?, ?, ?, ?)
        """,
        (session_id, agent_id, function_tag, feedback_type, comment),
    )


# ============================================================
# 离线评估队列
# ============================================================

def add_to_offline_evaluation(agent_id: str, function_tag: Optional[str]):
    """将淘汰的Agent加入离线评估队列"""
    execute_sql(
        "INSERT INTO offline_evaluation_queue (agent_id, function_tag, status) "
        "VALUES (?, ?, 'pending')",
        (agent_id, function_tag),
    )


def get_offline_eval_pending() -> list[dict]:
    """获取待离线评估的Agent"""
    rows = query_all(
        "SELECT * FROM offline_evaluation_queue WHERE status = 'pending'"
    )
    return [dict(r) for r in rows]
