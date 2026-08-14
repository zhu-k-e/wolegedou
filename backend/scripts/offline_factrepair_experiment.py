"""离线实验：用已有 task_resources（KB接地版生成）跑判官驱动事实修复闸门，
预估幻觉/谬误率能否下降。

不重跑 FSM（省 2.7h）。对每条例证：
  1. 重建 FocusedOutput（conclusion=content_markdown, code_example=代码块）
  2. 跑 _judge_driven_repair_focused_output（judge 指哪打哪：硬化 judge 标记具体错误 → 定向修复 → 复验）
  3. 仅当闸门改动内容时，用硬化 judge（HIGH/qwen-max，全文+练习+测验）
     重判修复前后讲义的 hallucination / factual_error，对比 delta。

诚信约束：闸门仅删除/改写 judge 真实指出的具体断言，正常内容零影响；
不改动覆盖率匹配口径、不喂测试集要点。
"""

import asyncio
import json
import re
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from loguru import logger
logger.remove()
logger.add(sys.stderr, level="WARNING", format="<level>{level: <8}</level> | {message}")

from backend.agents.domain_agent import DomainAgent
from backend.schemas.focused_output import FocusedOutput
from backend.schemas.student_profile import StudentProfile
from backend.services.rag.kb_manager import init_knowledge_base
from backend.scripts.benchmark_testcases import _build_profile
from backend.scripts.validate_metrics import MetricsCalculator
from backend.scripts.metrics_llm_judge import MetricsLLMJudge

_RESULT_PATH = _PROJECT_ROOT / "data" / "offline_judgerepair_experiment_result.txt"
_CONCURRENCY = 4
_CODE_BLOCK_RE = re.compile(r"```(?:[\w]*)\n(.*?)```", re.DOTALL)


def _extract_code(text: str) -> str:
    blocks = _CODE_BLOCK_RE.findall(text or "")
    return "\n\n".join(b.strip() for b in blocks if b.strip())


def _lecture_json(res: dict) -> dict:
    raw = res.get("lecture")
    try:
        obj = json.loads(raw) if raw else {}
    except Exception:
        obj = {}
    return obj if isinstance(obj, dict) else {}


def _lecture_text(obj: dict, new_conclusion: str = None) -> str:
    """复刻 validate_metrics._lecture_text_for_judge（title+difficulty_note+content_markdown）。"""
    conclusion = new_conclusion if new_conclusion is not None else (obj.get("content_markdown") or "")
    parts = []
    for k in ("title", "difficulty_note"):
        v = obj.get(k)
        if isinstance(v, str) and v.strip():
            parts.append(v.strip())
    if conclusion and isinstance(conclusion, str) and conclusion.strip():
        parts.append(conclusion.strip())
    return "\n\n".join(parts)


async def _process_one(agent, judge, calc, tc, res, sem):
    async with sem:
        q = tc.get("question", "")
        refs = tc.get("reference_answer_points") or []
        exp = tc.get("expected_complexity")
        if not exp or not refs:
            return None
        profile = _build_profile(tc) or None

        obj = _lecture_json(res)
        conclusion = obj.get("content_markdown") or ""
        code = _extract_code(conclusion)
        steps = list(obj.get("reasoning_steps") or [])
        while len(steps) < 3:
            steps.append("")

        focused = FocusedOutput(
            conclusion=conclusion,
            reasoning_steps=steps,
            knowledge_refs=[],
            applicable_conditions=obj.get("applicable_conditions") or "",
            code_example=code or None,
            difficulty_note=obj.get("difficulty_note") or "",
        )
        try:
            repaired = await agent._judge_driven_repair_focused_output(q, profile, focused, refs)
        except Exception as e:
            logger.warning(f"judge-repair 失败 [{q[:30]}]: {e}")
            return None

        new_conclusion = repaired.conclusion or conclusion
        changed = new_conclusion.strip() != conclusion.strip()
        if not changed:
            return {"tc_id": tc.get("id"), "repaired": False}

        # 仅对改动用例重判：原始 vs 修复后
        practice = calc._col_text(res, "practice_guide")
        quiz = calc._col_text(res, "quiz")
        orig_item = {
            "question": q, "expected_complexity": exp, "reference_points": refs,
            "lecture_text": _lecture_text(obj), "practice_text": practice, "quiz_text": quiz,
        }
        new_item = {
            "question": q, "expected_complexity": exp, "reference_points": refs,
            "lecture_text": _lecture_text(obj, new_conclusion), "practice_text": practice, "quiz_text": quiz,
        }
        try:
            orig_res = (await judge.judge_batch([orig_item]))[0]
            new_res = (await judge.judge_batch([new_item]))[0]
        except Exception as e:
            logger.warning(f"judge 失败 [{q[:30]}]: {e}")
            return {"tc_id": tc.get("id"), "repaired": True, "judged": False}

        return {
            "tc_id": tc.get("id"),
            "repaired": True,
            "judged": True,
            "hal_orig": bool(orig_res.get("hallucination")),
            "hal_new": bool(new_res.get("hallucination")),
            "fer_orig": bool(orig_res.get("factual_error")),
            "fer_new": bool(new_res.get("factual_error")),
            "hal_reason_new": new_res.get("hallucination_reason", ""),
        }


def _snapshot(results, total, done):
    rep = [r for r in results if r and r.get("repaired")]
    jud = [r for r in rep if r.get("judged")]
    fixed_hal = sum(1 for r in jud if r["hal_orig"] and not r["hal_new"])
    intro_hal = sum(1 for r in jud if (not r["hal_orig"]) and r["hal_new"])
    fixed_fer = sum(1 for r in jud if r["fer_orig"] and not r["fer_new"])
    intro_fer = sum(1 for r in jud if (not r["fer_orig"]) and r["fer_new"])
    lines = [
        f"[离线 judge-repair 实验] 已处理 {done}/{total}",
        f"闸门触发(内容改动)用例 = {len(rep)}",
        f"  其中已重判 = {len(jud)}",
        f"  幻觉: 原命中 {sum(1 for r in jud if r['hal_orig'])} → 修复后 {sum(1 for r in jud if r['hal_new'])}",
        f"    净修复(true→false) = {fixed_hal} | 新引入(false→true) = {intro_hal}",
        f"  谬误: 原命中 {sum(1 for r in jud if r['fer_orig'])} → 修复后 {sum(1 for r in jud if r['fer_new'])}",
        f"    净修复 = {fixed_fer} | 新引入 = {intro_fer}",
    ]
    _RESULT_PATH.write_text("\n".join(lines), encoding="utf-8")


async def main():
    init_knowledge_base()
    agent = DomainAgent("agent_004")
    judge = MetricsLLMJudge(concurrency=_CONCURRENCY)
    calc = MetricsCalculator(bm_only=True, use_llm=False)
    pairs = calc._build_pairs()
    logger.warning(f"配对用例数: {len(pairs)}")

    sem = asyncio.Semaphore(_CONCURRENCY)
    tasks = [_process_one(agent, judge, calc, tc, res, sem) for tc, res in pairs]
    results = []
    done = 0
    for coro in asyncio.as_completed(tasks):
        r = await coro
        if r:
            results.append(r)
        done += 1
        if done % 10 == 0 or done == len(tasks):
            _snapshot(results, len(tasks), done)

    # 最终汇总
    rep = [r for r in results if r and r.get("repaired")]
    jud = [r for r in rep if r.get("judged")]
    fixed_hal = sum(1 for r in jud if r["hal_orig"] and not r["hal_new"])
    intro_hal = sum(1 for r in jud if (not r["hal_orig"]) and r["hal_new"])
    fixed_fer = sum(1 for r in jud if r["fer_orig"] and not r["fer_new"])
    intro_fer = sum(1 for r in jud if (not r["fer_orig"]) and r["fer_new"])
    fixed_examples = [r for r in jud if r["hal_orig"] and not r["hal_new"]]

    out = [
        "=" * 64,
        "[离线 判官驱动修复实验 · 最终结果]",
        f"配对用例={len(results)}  闸门触发(改动)={len(rep)}  已重判={len(jud)}",
        f"幻觉 原命中={sum(1 for r in jud if r['hal_orig'])} → 修复后={sum(1 for r in jud if r['hal_new'])}",
        f"  净修复(true→false)={fixed_hal}  新引入(false→true)={intro_hal}",
        f"谬误 原命中={sum(1 for r in jud if r['fer_orig'])} → 修复后={sum(1 for r in jud if r['fer_new'])}",
        f"  净修复={fixed_fer}  新引入={intro_fer}",
        "- 幻觉被修复的用例 -",
    ]
    for r in fixed_examples:
        out.append(f"  [{r['tc_id']}] 修复后理由: {r.get('hal_reason_new','')[:120]}")
    out.append("=" * 64)

    text = "\n".join(out)
    print(text, flush=True)
    _RESULT_PATH.write_text(text, encoding="utf-8")
    logger.warning(f"[结果已写入 {_RESULT_PATH}]")


if __name__ == "__main__":
    asyncio.run(main())
