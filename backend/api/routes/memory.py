"""贡献记忆闭环可视化接口

赛题"作品完整性30分"要求闭环：学情画像 → 多智能体协同调度 → 领域知识生成
→ 交互反馈 → 动态决策更新。最后一步"动态决策更新"即贡献记忆闭环。

GET /api/memory_stats
返回当前 α 值、各 Agent 贡献分/准确率/返工率、最近贡献记录、淘汰记录，
供前端在任务完成后展示"多智能体协同优化反馈"卡片，向评委证明闭环存在。

注意：contribution_memory 查询已排除 task_type='offline_eval'（benchmark 隔离），
仅返回真实交互产生的贡献，避免演示数据污染评分。
"""

from fastapi import APIRouter
from backend.db.repositories import agent_repo, memory_repo, config_repo
from backend.db.database import query_all

router = APIRouter()


@router.get("/memory_stats")
async def get_memory_stats() -> dict:
    """贡献记忆闭环状态（动态决策更新可视化）

    前端在 /api/status 任务 COMPLETE 后调用，展示各 Agent 表现进化与淘汰记录，
    闭环最后一步"交互反馈→动态决策更新"的可视化证据。
    """
    alpha = config_repo.get_alpha()

    perfs = query_all(
        """
        SELECT p.agent_id, p.function_tag, p.accuracy, p.count,
               p.rework_rate, p.importance_score, p.is_suspended,
               c.agent_name
        FROM agent_performance p
        LEFT JOIN agent_cards c ON c.agent_id = p.agent_id
        ORDER BY p.importance_score DESC
        """
    )
    agents = [dict(r) for r in perfs]

    recent = query_all(
        """
        SELECT task_id, agent_id, function_tag, review_score,
               importance_score, referee_verdict, created_at
        FROM contribution_memory
        WHERE task_type <> 'offline_eval'
        ORDER BY created_at DESC
        LIMIT 20
        """
    )
    recent_contributions = [dict(r) for r in recent]

    elim = query_all(
        """
        SELECT agent_id, function_tag, reason, created_at
        FROM elimination_log
        ORDER BY created_at DESC
        LIMIT 20
        """
    )
    eliminations = [dict(r) for r in elim]

    return {
        "alpha": alpha,
        "agent_count": len(agents),
        "agents": agents,
        "recent_contributions": recent_contributions,
        "eliminations": eliminations,
    }
