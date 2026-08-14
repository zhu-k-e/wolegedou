"""/ask 接口 - 主流程入口

学生提交问题，触发FSM编排器完整流程。

P1-6 离线演示缓存：demo_cache_enabled 时优先查缓存，命中直接返回
P1-7 数据合规：记录对话历史 + AI 内容标注
8.2.2 可视化报告：保存资源难度统计（匹配曲线数据源）
"""

from fastapi import APIRouter

from backend.api.schemas import AskRequest, AskResponse
from backend.core.orchestrator import Orchestrator
from backend.services.demo_cache import get_cached_answer, cache_answer
from backend.services import compliance
from backend.config import get_settings
from backend.db.database import execute_sql

router = APIRouter()

# 编排器单例
_orchestrator: Orchestrator | None = None


def get_orchestrator() -> Orchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Orchestrator()
    return _orchestrator


@router.post("/ask", response_model=AskResponse)
async def ask(request: AskRequest) -> AskResponse:
    """学生提问 - 主流程入口

    触发FSM编排器：
      PROFILING → DISPATCHING → GENERATING → REVIEWING
      → FOCUSING → JUDGING → FORMATTING → COMPLETE

    响应时间：
      单领域 ~20s, 跨领域 ~27s, 全链路 ~38s
    """
    settings = get_settings()

    # P1-7: 记录用户提问（容错：记录失败不影响主流程）
    try:
        compliance.record_conversation(
            session_id=request.session_id,
            role="user",
            content=request.question,
        )
    except Exception as e:
        from loguru import logger
        logger.warning(f"记录用户提问失败（不影响主流程）: {e}")

    # P1-6: 离线缓存优先 — 命中则直接返回，不走 LLM
    cached = get_cached_answer(request.question)
    if cached is not None:
        # 补全 session_id（缓存里的 session_id 是首次提问者的）
        cached["session_id"] = request.session_id
        cached["from_cache"] = True
        # 记录 AI 回复
        try:
            _record_assistant_reply(request.session_id, cached)
        except Exception as e:
            from loguru import logger
            logger.warning(f"记录AI回复失败(缓存路径): {e}")
        return AskResponse(**cached)

    # 正常走编排器
    orchestrator = get_orchestrator()
    result = await orchestrator.process_question(
        question=request.question,
        session_id=request.session_id,
        history=request.history,
        profile=orchestrator._coerce_profile(request.profile),
    )

    response = AskResponse(**result)

    # P1-7: 记录 AI 回复（带标注，容错：记录失败不影响主流程）
    try:
        _record_assistant_reply(request.session_id, result, response.task_id)
    except Exception as e:
        from loguru import logger
        logger.warning(f"记录AI回复失败（不影响主流程）: {e}")

    # 8.2.2: 保存资源难度统计（匹配曲线数据源，容错）
    try:
        _save_resource_stats(request.session_id, result)
    except Exception as e:
        from loguru import logger
        logger.warning(f"保存资源难度统计失败（不影响主流程）: {e}")

    # 第七部分: 保存任务指标（量化指标验证数据源，容错）
    try:
        _save_task_metrics(request.session_id, result)
    except Exception as e:
        from loguru import logger
        logger.warning(f"保存任务指标失败（不影响主流程）: {e}")

    # 落库生成资源文本（事实比对指标 + 测试数据套装数据源，容错，不增加调用时间）
    try:
        from backend.db.resource_store import save_task_resources
        save_task_resources(result.get("task_id"), request.session_id, result, request.question)
    except Exception as e:
        from loguru import logger
        logger.warning(f"落库生成资源失败（不影响主流程）: {e}")

    # P1-6: 回写缓存（仅成功的完整响应才缓存，error 不缓存）
    if settings.demo_cache_enabled and not result.get("error"):
        cache_answer(request.question, result, result.get("profile"))

    return response


@router.post("/tasks")
async def create_task_endpoint(request: AskRequest) -> dict:
    """异步任务提交 - 立即返回 task_id，后端后台执行

    前端拿到 task_id 后轮询 GET /api/status/{task_id}（或连 WS /ws/{task_id}）获取进度与结果。
    解决 /api/ask 同步阻塞 + cloudflared 免费版 100s 隧道超时导致的联调断连问题。
    """
    orchestrator = get_orchestrator()
    task_id = orchestrator.submit_task(
        question=request.question,
        session_id=request.session_id,
        history=request.history,
        profile=request.profile,
    )
    return {"task_id": task_id, "status": "PENDING"}


def _record_assistant_reply(
    session_id: str,
    result: dict,
    task_id: str | None = None,
) -> None:
    """把 AI 回复记入会话历史（带 AI 标注）"""
    # 拼一个简短的回复摘要用于历史记录
    parts = []
    if result.get("navigation_roadmap"):
        parts.append(result["navigation_roadmap"])
    if result.get("clarification_options"):
        parts.append(" / ".join(result["clarification_options"]))
    if result.get("resource_package"):
        rp = result["resource_package"]
        # resource_package 里可能有讲义/指南/测试题
        if isinstance(rp, dict):
            for key in ("lecture", "guide", "quiz"):
                if rp.get(key):
                    parts.append(str(rp[key])[:500])
    if result.get("error"):
        parts.append(f"[错误] {result['error']}")

    content = "\n\n".join(parts) if parts else "(空回复)"
    # 加 AI 标注
    content = compliance.annotate_ai_content(content)

    compliance.record_conversation(
        session_id=session_id,
        role="assistant",
        content=content,
        task_id=task_id or result.get("task_id"),
        is_ai_generated=True,
    )


def _save_resource_stats(session_id: str, result: dict) -> None:
    """保存资源难度统计（8.2.2 节匹配曲线数据源）

    从 resource_package 聚合 quiz difficulty 分布，写入 task_resource_stats 表。
    无 quiz 时跳过。
    """
    import json

    rp = result.get("resource_package")
    if not rp or not isinstance(rp, dict):
        return

    # 聚合 quiz difficulty 分布
    quiz = rp.get("quiz")
    diffs: dict[str, int] = {}
    if quiz and isinstance(quiz, dict):
        for q in quiz.get("questions", []):
            d = q.get("difficulty", "基础")
            diffs[d] = diffs.get(d, 0) + 1

    lecture = rp.get("lecture")
    lecture_note = ""
    if lecture and isinstance(lecture, dict):
        lecture_note = lecture.get("difficulty_note", "")

    # 无难度数据则跳过
    if not diffs and not lecture_note:
        return

    # 确保会话存在（外键完整性）
    compliance.ensure_session(session_id)

    # 取 domain 和 level
    dispatch = result.get("dispatch_info") or {}
    domains = dispatch.get("domains", [])
    domain = domains[0] if domains else None
    profile = result.get("profile") or {}
    level = profile.get("knowledge_level", "ENTRY")

    execute_sql(
        """INSERT INTO task_resource_stats
           (task_id, session_id, domain, knowledge_level,
            quiz_difficulties, lecture_difficulty_note)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            result.get("task_id"),
            session_id,
            domain,
            level,
            json.dumps(diffs, ensure_ascii=False),
            lecture_note,
        ),
    )


def _save_task_metrics(session_id: str, result: dict) -> None:
    """保存任务指标（第七部分量化指标验证数据源）

    从 judge_verdict + review_summary 提取裁判裁决指标和审核评分，
    写入 task_metrics 表。无 judge_verdict 时跳过。
    """
    jv = result.get("judge_verdict")
    if not jv or not isinstance(jv, dict):
        return

    verdict = jv.get("verdict")
    verification_rate = jv.get("overall_verification_rate")
    override_reason = jv.get("override_reason")

    # 溯源标注统计
    traceability = jv.get("traceability", [])
    traceability_total = len(traceability)
    traceability_verified = sum(
        1 for t in traceability
        if isinstance(t, dict) and t.get("verification_status") == "已验证"
    )

    # 知识引用数
    knowledge_refs_count = result.get("knowledge_refs_count", 0)

    # 审核评分（review_summary 由编排器提取）
    rs = result.get("review_summary") or {}
    fact_accuracy = rs.get("fact_accuracy")
    logic_completeness = rs.get("logic_completeness")
    pedagogical_fit = rs.get("pedagogical_fit")

    # 综合评分
    scores_list = [s for s in [fact_accuracy, logic_completeness, pedagogical_fit] if s is not None]
    review_score = sum(scores_list) / len(scores_list) if scores_list else None

    # 确保会话存在（外键完整性）
    compliance.ensure_session(session_id)

    execute_sql(
        """INSERT INTO task_metrics
           (task_id, session_id, verdict, verification_rate,
            traceability_total, traceability_verified, knowledge_refs_count,
            fact_accuracy, logic_completeness, pedagogical_fit, review_score,
            override_reason)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            result.get("task_id"),
            session_id,
            verdict,
            verification_rate,
            traceability_total,
            traceability_verified,
            knowledge_refs_count,
            fact_accuracy,
            logic_completeness,
            pedagogical_fit,
            review_score,
            override_reason,
        ),
    )
