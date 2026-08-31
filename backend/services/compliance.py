"""数据合规服务（P1-7，方案书 7.4 节）

三块能力：
1. 会话隔离 — conversations 表按 session_id 隔离，不同学生数据互不可见
2. 数据保留 — 默认 30 天过期，cleanup_expired() 清理过期记录
3. AI 生成内容标注 — 所有 AI 输出明确标注"AI生成内容，仅供参考"
"""

from datetime import datetime, timedelta
from typing import Optional

from loguru import logger

from backend.db.database import execute_sql, query_all
from backend.config import get_settings


# AI 生成内容标注（方案书 7.4 节）
AI_DISCLAIMER = "⚠️ 以上内容由 AI 生成，仅供参考，请以官方文档与权威资料为准。"


# ============================================================
# 1. 会话历史记录 + 会话隔离
# ============================================================

def ensure_session(session_id: str) -> None:
    """确保 session 表中存在指定会话记录（不存在则创建）

    所有写入 session_id 的表（conversations / student_profiles /
    task_resource_stats / task_metrics / student_feedback）在写入前
    必须先调用此函数，避免外键约束失败或产生孤儿记录。
    """
    execute_sql(
        "INSERT OR IGNORE INTO session (session_id, created_at) VALUES (?, datetime('now'))",
        (session_id,),
    )


def record_conversation(
    session_id: str,
    role: str,
    content: str,
    task_id: Optional[str] = None,
    is_ai_generated: bool = False,
) -> None:
    """记录一条对话历史（共用全局数据库连接，解决跨连接外键失效问题）"""

    days = get_settings().conversation_retention_days
    expires_at = (datetime.utcnow() + timedelta(days=days)).isoformat(sep=" ")

    # 确保会话存在（INSERT OR IGNORE），再插入聊天记录
    ensure_session(session_id)

    execute_sql(
        """
        INSERT INTO conversations
            (session_id, task_id, role, content, is_ai_generated, expires_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            session_id,
            task_id,
            role,
            content,
            1 if is_ai_generated else 0,
            expires_at,
        ),
    )


def get_session_history(session_id: str, limit: int = 50) -> list[dict]:
    """获取指定会话的历史（会话隔离：只能看到自己的）

    按 created_at 升序返回（旧→新），便于编排器拼接到 history 字段。
    """
    rows = query_all(
        """
        SELECT role, content, is_ai_generated, created_at
        FROM conversations
        WHERE session_id = ?
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (session_id, limit),
    )
    # 反转为升序（旧→新）
    return [
        {
            "role": r["role"],
            "content": r["content"],
            "is_ai_generated": bool(r["is_ai_generated"]),
            "created_at": r["created_at"],
        }
        for r in reversed(rows)
    ]


# ============================================================
# 2. 数据保留 — 过期清理
# ============================================================

def cleanup_expired() -> int:
    """清理过期对话历史，返回清理条数

    建议在应用启动时调用一次，并可配合定时任务（如每天一次）。
    """
    from backend.db.database import query_one
    row = query_one(
        "SELECT COUNT(*) AS cnt FROM conversations WHERE expires_at < CURRENT_TIMESTAMP"
    )
    expired_count = row["cnt"] if row else 0

    if expired_count == 0:
        return 0

    execute_sql(
        "DELETE FROM conversations WHERE expires_at < CURRENT_TIMESTAMP"
    )
    logger.info(f"已清理过期对话历史: {expired_count} 条")
    return expired_count


# ============================================================
# 3. AI 生成内容标注
# ============================================================

def annotate_ai_content(text: str) -> str:
    """给 AI 生成内容追加标注

    若文本已包含标注则不重复添加；空文本原样返回。
    """
    if not text:
        return text
    if AI_DISCLAIMER in text:
        return text
    return f"{text}\n\n---\n{AI_DISCLAIMER}"


def is_ai_generated(history_item: dict) -> bool:
    """判断历史消息是否为 AI 生成"""
    return bool(history_item.get("is_ai_generated", False))