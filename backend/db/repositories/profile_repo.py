"""学情画像 Repository

操作 student_profiles 表，支持版本化历史查询。
"""

import json
from typing import Optional

from backend.db.database import query_one, query_all, execute_sql
from backend.services.compliance import ensure_session


def save_profile(
    session_id: str,
    version: int,
    knowledge_level: str,
    background: str,
    current_goal: str,
    question_type: str,
    domain_hint: list[str],
    complexity_estimate: str,
    intent_type: str,
    domain_confidence: dict,
    test_results: list = None,
) -> int:
    """保存学情画像（版本号自增）"""
    # 确保会话存在（避免外键约束失败 / 孤儿记录）
    ensure_session(session_id)
    cursor = execute_sql(
        """
        INSERT INTO student_profiles
            (session_id, version, knowledge_level, background, current_goal,
             question_type, domain_hint, complexity_estimate, intent_type, domain_confidence,
             test_results)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (session_id, version, knowledge_level, background, current_goal,
         question_type, json.dumps(domain_hint, ensure_ascii=False),
         complexity_estimate, intent_type,
         json.dumps(domain_confidence, ensure_ascii=False),
         json.dumps(test_results or [], ensure_ascii=False)),
    )
    return cursor.lastrowid


def get_latest_profile(session_id: str) -> Optional[dict]:
    """获取某session最新的学情画像"""
    row = query_one(
        "SELECT * FROM student_profiles WHERE session_id = ? ORDER BY version DESC LIMIT 1",
        (session_id,),
    )
    if row:
        return _row_to_profile(row)
    return None


def get_profile_history(session_id: str, limit: int = 3) -> list[dict]:
    """获取某session的学情画像历史（最近N个版本）"""
    rows = query_all(
        "SELECT * FROM student_profiles WHERE session_id = ? ORDER BY version DESC LIMIT ?",
        (session_id, limit),
    )
    return [_row_to_profile(r) for r in rows]


def get_next_version(session_id: str) -> int:
    """获取下一个版本号"""
    row = query_one(
        "SELECT MAX(version) as max_ver FROM student_profiles WHERE session_id = ?",
        (session_id,),
    )
    return (row["max_ver"] or 0) + 1


def _row_to_profile(row) -> dict:
    """将数据库行转换为学情画像dict"""
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "version": row["version"],
        "knowledge_level": row["knowledge_level"],
        "background": row["background"],
        "current_goal": row["current_goal"],
        "question_type": row["question_type"],
        "domain_hint": json.loads(row["domain_hint"]),
        "complexity_estimate": row["complexity_estimate"],
        "intent_type": row["intent_type"],
        "domain_confidence": json.loads(row["domain_confidence"]),
        "test_results": json.loads(row["test_results"]) if row["test_results"] else [],
        "created_at": row["created_at"],
    }
