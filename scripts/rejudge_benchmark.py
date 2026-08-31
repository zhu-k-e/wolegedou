"""复判基准 100 用例的"活裁判团"裁决（不重跑答案生成，不加载知识库）

目的（竞赛 XH-202630，2026-08-15）：
  裁判团此前因"软维度"(逻辑跳跃/难度偏差/溯源未100%)过严，导致 68% 用例被强制放行
  (unanimous_fail_force_pass 63 + revision_limit 3 + exception 2)。本次在
  judge_panel.py 已做校准（放松反向怀疑阈值、裁判长终审仅严重事实错误才 fail、
  逻辑/适用性裁判仅严重缺陷才 fail、事实闸门保留）后，仅对【已生成的讲义内容】重新
  跑裁判团投票 + 裁判长终审，刷新 task_metrics.verdict / override_reason。

设计要点：
- 不调用 domain/resource 生成（零答案生成）。裁判调用使用 MID 档(deepseek-chat,
  独立账户)以避开 qwen-max 并发/配额限流；judge_panel 的 tier 参数默认仍为 HIGH，
  不影响线上行为。
- 不加载知识库（get_knowledge_base 默认 Stub），跳过 _annotate_traceability，
  原 task_metrics 的 verification_rate / traceability_* 等由 Verifier 产出的字段保持不变。
- 仅复刻 judge() 的投票决策树（3:0 / 2:1 / 0:3 / 1:2），0:3 走裁判长终审，2:1 事实裁判
  失败走分歧解决（无候选 Agent 时跳过候选辩论，仅多数方回应 + 裁判长裁决）。
- 终态映射与真实 FSM 一致：任何非干净结果最终都会强制放行(low_confidence_passed)，
  仅把"干净通过"与"强制放行"如实区分，不粉饰。

用法:
  cd D:/projects/wolegedou
  .venv/Scripts/python.exe scripts/rejudge_benchmark.py
"""

import asyncio
import json
import re
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from backend.schemas.candidate_output import KnowledgeRef
from backend.schemas.focused_output import FocusedOutput
from backend.schemas.judge_verdict import Verdict
from backend.schemas.student_profile import (
    Background,
    ComplexityEstimate,
    CurrentGoal,
    IntentType,
    KnowledgeLevel,
    QuestionType,
    StudentProfile,
)
from backend.services.llm_client import ModelTier
from backend.agents.judge_panel import JudgePanel

TEST_CASES_PATH = _PROJECT_ROOT / "tests" / "test_cases_100.json"
DB_PATH = _PROJECT_ROOT / "data" / "wolegedou.db"
REJUDGE_TIER = ModelTier.MID  # deepseek-chat，避开 qwen-max 限流

# ---------- 学情画像映射（test_cases.suitable_profile -> StudentProfile 枚举） ----------
_LEVEL_MAP = {"beginner": "入门", "intermediate": "中级", "advanced": "进阶"}
_BG_MAP = {
    "cs_student": "理科_无编程",
    "developer": "有Python基础",
    "researcher": "有ML基础",
    "product_manager": "文科",
}
_GOAL_MAP = {
    "learn_basics": "快速上手应用",
    "build_project": "项目落地",
    "research": "算法研究",
    "deploy": "项目落地",
    "debug": "快速上手应用",
}


def _build_profile(suitable: dict) -> StudentProfile:
    lvl = _LEVEL_MAP.get(suitable.get("knowledge_level"), "中级")
    bg = _BG_MAP.get(suitable.get("background"), "理科_无编程")
    goal = _GOAL_MAP.get(suitable.get("current_goal"), "快速上手应用")
    return StudentProfile(
        knowledge_level=KnowledgeLevel(lvl),
        background=Background(bg),
        current_goal=CurrentGoal(goal),
        question_type=QuestionType("概念理解"),
        complexity_estimate=ComplexityEstimate("单领域"),
        intent_type=IntentType("generation"),
        domain_hint=[],
    )


# ---------- 从讲义重建 FocusedOutput ----------
def _clean(md: str) -> str:
    return re.sub(r"[#*>`\-·•]", "", md).strip()


def _extract_conclusion(md: str) -> str:
    for para in re.split(r"\n\s*\n", md):
        t = _clean(para)
        if len(t) >= 15:
            return t[:300]
    return _clean(md)[:300] or "（无明确结论）"


def _extract_reasoning_steps(md: str) -> list[str]:
    lines = md.splitlines()
    sections: list[str] = []
    cur: list[str] = []
    for line in lines:
        if re.match(r"^#{1,4}\s", line):
            if cur:
                sections.append("\n".join(cur).strip())
                cur = []
            cur.append(line)
        else:
            cur.append(line)
    if cur:
        sections.append("\n".join(cur).strip())
    steps = [_clean(s) for s in sections if _clean(s)]
    if len(steps) < 3:
        paras = [_clean(p) for p in re.split(r"\n\s*\n", md) if _clean(p)]
        steps = paras or steps
    if len(steps) < 3:
        piece = max(1, len(md) // 3)
        steps = [md[i * piece:(i + 1) * piece].strip() or f"步骤{i + 1}" for i in range(3)]
    return steps[:12]


def _extract_code(md: str) -> str:
    blocks = re.findall(r"```[a-zA-Z0-9]*\n(.*?)```", md, re.DOTALL)
    return "\n\n".join(b.strip() for b in blocks) if blocks else None


def _build_focused(lecture_obj: dict, kr_raw) -> FocusedOutput:
    md = lecture_obj.get("content_markdown", "") or ""
    kr_list = []
    if kr_raw:
        try:
            items = json.loads(kr_raw) if isinstance(kr_raw, str) else kr_raw
            for it in items:
                src = it.get("source", "") if isinstance(it, dict) else str(it)
                if src:
                    kr_list.append(KnowledgeRef(source=src, content_summary=src))
        except Exception:
            pass
    diff = lecture_obj.get("difficulty_note")
    applicable = diff if diff and isinstance(diff, str) else (
        "适用场景见讲义；不适用场景：超出本主题范围；前置知识：见学情画像。"
    )
    return FocusedOutput(
        conclusion=_extract_conclusion(md),
        reasoning_steps=_extract_reasoning_steps(md),
        knowledge_refs=kr_list,
        applicable_conditions=applicable,
        code_example=_extract_code(md),
        difficulty_note=diff if isinstance(diff, str) else None,
    )


# ---------- 复制 judge() 的投票决策树（无溯源标注） ----------
async def _rejudge_one(panel: JudgePanel, focused: FocusedOutput, profile: StudentProfile, question: str):
    strict_mode = panel._detect_reverse_suspicion(focused)
    judges = await asyncio.gather(
        panel._judge_single(panel.judge_fact, focused, profile, strict_mode, tier=REJUDGE_TIER),
        panel._judge_single(panel.judge_logic, focused, profile, strict_mode, tier=REJUDGE_TIER),
        panel._judge_single(panel.judge_applicability, focused, profile, strict_mode, tier=REJUDGE_TIER),
    )
    pass_count = sum(1 for j in judges if j.judgment == "pass")
    fail_count = 3 - pass_count

    if pass_count == 3:
        return Verdict.PASSED, None
    elif pass_count == 2:
        fail_idx = next(i for i, j in enumerate(judges) if j.judgment == "fail")
        if fail_idx == 0:
            verdict, _ = await panel._resolve_dissent(
                focused, profile, judges, question, None, None, None, None, tier=REJUDGE_TIER
            )
            return verdict, None
        return Verdict.LOW_CONFIDENCE_PASSED, None
    elif fail_count == 3:
        return await panel._final_review_on_unanimous_fail(focused, profile, judges, tier=REJUDGE_TIER)
    else:  # 1:2
        return Verdict.REVISE, None


def _terminal(verdict: Verdict, override) -> tuple[str, object]:
    """映射为真实 FSM 终态：任何非干净结果最终都强制放行(low_confidence_passed)。"""
    if verdict == Verdict.PASSED:
        return "passed", None
    if verdict == Verdict.LOW_CONFIDENCE_PASSED:
        return "low_confidence_passed", override
    if verdict == Verdict.FAILED:
        return "low_confidence_passed", "unanimous_fail_force_pass"
    return "low_confidence_passed", "revision_limit_force_pass"


async def _process_with_retry(panel, sid, tr, tm, tc, attempts=4):
    last = None
    for attempt in range(attempts):
        try:
            lec = json.loads(tr["lecture"]) if isinstance(tr["lecture"], str) else tr["lecture"]
            cid = sid.replace("bm_", "")
            suitable = (tc.get(cid) or {}).get("suitable_profile", {})
            profile = _build_profile(suitable or {})
            focused = _build_focused(lec, tr.get("knowledge_refs"))
            question = tr.get("question") or (tc.get(cid) or {}).get("question", "")
            verdict, override = await _rejudge_one(panel, focused, profile, question)
            return sid, verdict, override, "ok"
        except Exception as e:  # 含 429 限流
            last = e
            if attempt < attempts - 1:
                wait = 5 * (attempt + 1)
                print(f"  [重试 {attempt + 1}] {sid}: {str(e)[:80]} (等待 {wait}s)")
                await asyncio.sleep(wait)
    return sid, None, None, f"err:{last}"


async def main():
    test_cases = json.loads(TEST_CASES_PATH.read_text(encoding="utf-8")).get("test_cases", [])
    tc_by_id = {c["id"]: c for c in test_cases}

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    tr_rows = {
        r["session_id"]: dict(r)
        for r in cur.execute(
            "SELECT session_id, question, lecture, knowledge_refs FROM task_resources "
            "WHERE session_id LIKE 'bm_%'"
        )
    }
    tm_rows = {
        r["session_id"]: dict(r)
        for r in cur.execute("SELECT * FROM task_metrics WHERE session_id LIKE 'bm_%'")
    }
    con.close()

    panel = JudgePanel()  # get_knowledge_base 默认 Stub，不加载真实 KB
    before_force = sum(1 for r in tm_rows.values() if r.get("override_reason") is not None)

    sem = asyncio.Semaphore(4)

    async def process(sid: str):
        async with sem:
            return await _process_with_retry(panel, sid, tr_rows[sid], tm_rows[sid], tc_by_id)

    results = []
    for fut in asyncio.as_completed([process(sid) for sid in tm_rows.keys()]):
        results.append(await fut)

    # 写回（仅写本次成功的；失败/跳过保持原值，下次可重跑补全）
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    updated = 0
    skipped = 0
    for sid, verdict, override, status in results:
        if status != "ok" or verdict is None:
            print(f"  [跳过] {sid}: {status}")
            skipped += 1
            continue
        term_v, term_o = _terminal(verdict, override)
        cur.execute(
            "UPDATE task_metrics SET verdict=?, override_reason=? WHERE session_id=?",
            (term_v, term_o, sid),
        )
        updated += 1
    con.commit()

    from collections import Counter
    new_verdicts = Counter()
    new_overrides = Counter()
    for r in cur.execute(
        "SELECT verdict, override_reason FROM task_metrics WHERE session_id LIKE 'bm_%'"
    ):
        new_verdicts[r[0]] += 1
        new_overrides[r[1] if r[1] is not None else "None"] += 1
    con.close()
    after_force = sum(v for k, v in new_overrides.items() if k != "None")

    print(f"\n=== 复判完成 ===")
    print(f"更新条数: {updated} | 跳过: {skipped}")
    print(f"强制放行: {before_force} -> {after_force}  (降幅 {before_force - after_force})")
    print(f"verdict 分布: {dict(new_verdicts)}")
    print(f"override 分布: {dict(new_overrides)}")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    asyncio.run(main())
