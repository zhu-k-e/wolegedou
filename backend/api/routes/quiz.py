"""/quiz_submit 接口 - 答题验证

计算正确率 + 触发降维/进阶

【bug #4 修复 2026-08-27】后端真值判分：不再依赖前端 is_correct 字段，
从 task_resources 读 quiz.questions 拿真值答案自己判分。
"""

import json
import re
from difflib import SequenceMatcher

from fastapi import APIRouter
from loguru import logger

from backend.api.schemas import QuizSubmitRequest, QuizSubmitResponse
from backend.core.orchestrator import Orchestrator
from backend.api.routes.ask import get_orchestrator
from backend.db.database import query_one

router = APIRouter()


def _first_alpha(s: str) -> str:
    """从 'A' / 'A.' / 'A、' / 'A) 监督学习...' 中提取首字母（A-Z 字母或 T/F）"""
    s = (s or "").strip()
    if not s:
        return ""
    c = s[0].upper()
    if c.isalpha():
        return c
    return ""


def _grade_single(user: str, truth: str, qtype: str) -> bool:
    """单题判分：选择题/判断题按首字母相等，简答/设计分析按相似度+关键词。"""
    u = (user or "").strip()
    t = (truth or "").strip()
    if not u or not t:
        return False

    # 选择/判断/代码补全：单字母答案
    if qtype in ("选择", "判断"):
        ua, ta = _first_alpha(u), _first_alpha(t)
        if ua and ta:
            return ua == ta
        # 答案本身不是字母（罕见）：按全文包含
        return t in u or u == t

    # 设计分析 / 代码补全 / 简答：长答案
    # 1) 相似度
    sim = SequenceMatcher(None, u, t).ratio()
    if sim >= 0.5:
        return True
    # 2) 关键词包含：取真值中长度>=3 的实词片段，命中数≥一半
    kws = [w for w in re.split(r"[，。、；：,\s\.\(\)（）]", t) if len(w.strip()) >= 3][:6]
    if not kws:
        return u == t or t in u
    hit = sum(1 for k in kws if k in u)
    return hit >= max(1, len(kws) // 2)


def _load_true_answers(task_id: str) -> dict:
    """从 task_resources 加载题目真值。返回 {question_text: {type, answer}} 索引。
    加载失败返回空 dict（让调用方降级到信任前端 is_correct 保持向后兼容）。"""
    try:
        row = query_one(
            "SELECT quiz FROM task_resources WHERE task_id = ?",
            (task_id,),
        )
    except Exception as e:
        logger.warning(f"加载 quiz 真值失败: task_id={task_id}, err={e}")
        return {}
    if not row or not row["quiz"]:
        return {}
    q = row["quiz"]
    if isinstance(q, str):
        try:
            q = json.loads(q)
        except Exception:
            return {}
    questions = q.get("questions", []) if isinstance(q, dict) else (q or [])
    return {
        qq.get("question", ""): {"type": qq.get("type", "选择"), "answer": qq.get("answer", "")}
        for qq in questions
    }


@router.post("/quiz_submit", response_model=QuizSubmitResponse)
async def submit_quiz(request: QuizSubmitRequest) -> QuizSubmitResponse:
    """答题验证

    对应方案书 6.1.3 节延伸路径：
      正确率<60% → REDIMENSION（降维解释）
      正确率60%-85% → REDIMENSION（轻度降维）
      正确率≥85% → ADVANCE（进阶挑战）

    bug #4 修复：后端基于 task_resources 真值自己判分，不再依赖前端 is_correct。
    """
    total = len(request.answers)
    if total == 0:
        return QuizSubmitResponse(
            task_id=request.task_id,
            accuracy=0.0,
            action="redimension",
        )

    # 1) 后端真值判分（不再信任前端 is_correct）
    truth_map = _load_true_answers(request.task_id)
    correct = 0
    used_truth = False
    for a in request.answers:
        qtext = (a.get("question") or "").strip()
        user = (a.get("user_answer") or "").strip()
        if qtext and qtext in truth_map and user:
            used_truth = True
            info = truth_map[qtext]
            if _grade_single(user, info["answer"], info["type"]):
                correct += 1
        else:
            # 退化：真值缺失/题目对不上 → 信任前端 is_correct 保持向后兼容
            if a.get("is_correct", False):
                correct += 1

    if not used_truth:
        logger.warning(
            f"quiz_submit 真值未加载，回退信任前端 is_correct: task_id={request.task_id}, "
            f"answers={len(request.answers)}"
        )

    accuracy = correct / total

    # 2) 触发延伸路径
    orchestrator = get_orchestrator()
    result = await orchestrator.handle_extension(
        task_id=request.task_id,
        event_type="quiz_submit",
        event_data={
            "accuracy": accuracy,
            "answers": request.answers,
            "session_id": request.session_id,
        },
    )

    action = result.get("action", "redimension" if accuracy < 0.85 else "advance")
    followup_questions = result.get("followup_questions")

    return QuizSubmitResponse(
        task_id=request.task_id,
        accuracy=round(accuracy, 4),
        action=action,
        new_resources=result.get("reduced_resource_package"),
        advance_question=result.get("advance_question"),
        followup_questions=followup_questions,
    )
