"""离线演示缓存服务（P1-6，方案书附录 E）

挑战杯现场演示若网络不稳，系统走缓存模式：
  /api/ask 优先查 demo_cache 表，命中则直接返回，不走 LLM。
  未命中时正常走编排器，可选地把新结果回写缓存。

启用方式：.env 设置 DEMO_CACHE_ENABLED=true
预缓存：演示前用常见问题跑一遍系统（开启缓存回写），自动填充 demo_cache 表。
"""

import hashlib
import json
from typing import Optional

from loguru import logger

from backend.db.database import query_one, execute_sql
from backend.config import get_settings


def _hash_question(question: str) -> str:
    """问题归一化后 sha256，作为缓存键

    归一化：去首尾空白 + 转小写 + 合并连续空白
    这样 "RAG 是什么？" 和 "rag 是什么？" 能命中同一缓存
    """
    normalized = " ".join(question.strip().lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def get_cached_answer(question: str) -> Optional[dict]:
    """查缓存，命中返回 AskResponse 字典，未命中返回 None"""
    if not get_settings().demo_cache_enabled:
        return None

    qhash = _hash_question(question)
    row = query_one(
        "SELECT answer_json FROM demo_cache WHERE question_hash = ?",
        (qhash,),
    )
    if row is None:
        logger.debug(f"demo_cache 未命中: {qhash[:8]}")
        return None

    # 命中，更新命中次数
    execute_sql(
        "UPDATE demo_cache SET hit_count = hit_count + 1, "
        "updated_at = CURRENT_TIMESTAMP WHERE question_hash = ?",
        (qhash,),
    )
    logger.info(f"demo_cache 命中: {qhash[:8]}")
    try:
        return json.loads(row["answer_json"])
    except json.JSONDecodeError as e:
        logger.warning(f"demo_cache answer_json 解析失败: {e}")
        return None


def cache_answer(
    question: str,
    answer: dict,
    profile: Optional[dict] = None,
) -> None:
    """把一条问答结果写入缓存（演示前预缓存 / 运行时自学习）"""
    if not get_settings().demo_cache_enabled:
        return

    qhash = _hash_question(question)
    execute_sql(
        """
        INSERT OR REPLACE INTO demo_cache
            (question_hash, question_text, answer_json, profile_json, hit_count)
        VALUES (?, ?, ?, ?, 0)
        """,
        (
            qhash,
            question.strip(),
            json.dumps(answer, ensure_ascii=False),
            json.dumps(profile, ensure_ascii=False) if profile else None,
        ),
    )
    logger.debug(f"demo_cache 已写入: {qhash[:8]}")


def warmup_cache(question_answer_pairs: list[tuple[str, dict]]) -> int:
    """批量预热缓存

    Args:
        question_answer_pairs: [(question, answer_dict), ...]

    Returns:
        写入条数
    """
    if not get_settings().demo_cache_enabled:
        logger.warning("demo_cache 未启用，warmup 跳过")
        return 0

    count = 0
    for question, answer in question_answer_pairs:
        cache_answer(question, answer)
        count += 1
    logger.info(f"demo_cache 预热完成: {count} 条")
    return count


def get_cache_stats() -> dict:
    """缓存统计（供调试 / 演示前检查）"""
    row = query_one("SELECT COUNT(*) AS cnt FROM demo_cache")
    total = row["cnt"] if row else 0
    row2 = query_one("SELECT COALESCE(SUM(hit_count), 0) AS hits FROM demo_cache")
    hits = row2["hits"] if row2 else 0
    return {"enabled": get_settings().demo_cache_enabled, "total": total, "total_hits": hits}
