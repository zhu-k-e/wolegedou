"""全局离线验证：对全部 100 条跑判官驱动修复，对比修复前后【讲义(focused-text)】
的幻觉/谬误率。

为什么要聚焦"讲义"口径：
  闸门只改聚焦输出（结论+步骤+代码）。真实重跑中练习/测验由 repaired 聚焦输出派生，
  故讲义口径即闸门真实可控面。离线若把 repaired 结论与原练习/测验混判，会产生"假阳性新引入"
  （原练习/测验并非基于 repaired 结论生成）。本脚本用讲义口径给出无假阳性的全局 delta，
  并额外对改动用例同时报 full-text（含原练习/测验）以暴露该 artifact。

诚信约束：不改动覆盖率匹配口径、不喂测试集要点；仅对 judge 真实指出的断言做定向修复。
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

_RESULT_PATH = _PROJECT_ROOT / "data" / "offline_judgerepair_global_result.txt"
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
    conclusion = new_conclusion if new_conclusion is not None else (obj.get("content_markdown") or "")
    parts = []
    for k in ("title", "difficulty_note"):
        v = obj.get(k)
        if isinstance(v, str) and v.strip():
            parts.append(v.strip())
    if conclusion and isinstance(conclusion, str) and conclusion.strip():
        parts.append(conclusion.strip())
    return "\n\n".join(parts)


def _focused_text(conclusion, steps, code) -> str:
    parts = []
    if conclusion and str(conclusion).strip():
        parts.append(str(conclusion).strip())
    if steps:
        sl = [f"{i+1}. {s}" for i, s in enumerate(steps) if s and str(s).strip()]
        if sl:
            parts.append("步骤：\n" + "\n".join(sl))
    if code and str(code).strip():
        parts.append("代码示例：\n" + str(code).strip())
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
        new_code = repaired.code_example or code
        changed = new_conclusion.strip() != conclusion.strip() or (new_code or "").strip() != code.strip()

        practice = calc._col_text(res, "practice_guide")
        quiz = calc._col_text(res, "quiz")

        # 讲义口径（闸门真实可控面）
        o_foc = {"question": q, "expected_complexity": exp, "reference_points": refs,
                 "lecture_text": _focused_text(conclusion, steps, code), "practice_text": "", "quiz_text": ""}
        n_foc = {"question": q, "expected_complexity": exp, "reference_points": refs,
                 "lecture_text": _focused_text(new_conclusion, steps, new_code), "practice_text": "", "quiz_text": ""}
        try:
            ro_foc = (await judge.judge_batch([o_foc]))[0]
            rn_foc = (await judge.judge_batch([n_foc]))[0]
        except Exception as e:
            logger.warning(f"judge foc 失败 [{q[:30]}]: {e}")
            return None

        out = {
            "tc_id": tc.get("id"),
            "changed": changed,
            "hal_of": bool(ro_foc.get("hallucination")),
            "hal_nf": bool(rn_foc.get("hallucination")),
            "fer_of": bool(ro_foc.get("factual_error")),
            "fer_nf": bool(rn_foc.get("factual_error")),
        }
        # 仅对改动用例额外报 full-text（含原练习/测验）以暴露 artifact
        if changed:
            o_full = {"question": q, "expected_complexity": exp, "reference_points": refs,
                      "lecture_text": _lecture_text(obj), "practice_text": practice, "quiz_text": quiz}
            n_full = {"question": q, "expected_complexity": exp, "reference_points": refs,
                      "lecture_text": _lecture_text(obj, new_conclusion), "practice_text": practice, "quiz_text": quiz}
            try:
                ro_full = (await judge.judge_batch([o_full]))[0]
                rn_full = (await judge.judge_batch([n_full]))[0]
                out["hal_ofull"] = bool(ro_full.get("hallucination"))
                out["hal_nfull"] = bool(rn_full.get("hallucination"))
                out["fer_ofull"] = bool(ro_full.get("factual_error"))
                out["fer_nfull"] = bool(rn_full.get("factual_error"))
            except Exception as e:
                logger.warning(f"judge full 失败 [{q[:30]}]: {e}")
        return out


def _snapshot(results, total, done):
    foc = [r for r in results if r]
    hal_of = sum(1 for r in foc if r["hal_of"])
    hal_nf = sum(1 for r in foc if r["hal_nf"])
    fer_of = sum(1 for r in foc if r["fer_of"])
    fer_nf = sum(1 for r in foc if r["fer_nf"])
    changed = [r for r in foc if r["changed"]]
    lines = [
        f"[全局 judge-repair · 讲义口径] 已处理 {done}/{total}",
        f"  幻觉: 原 {hal_of} → 修复后 {hal_nf}  (净 {(hal_of-hal_nf):+d})",
        f"  谬误: 原 {fer_of} → 修复后 {fer_nf}  (净 {(fer_of-fer_nf):+d})",
        f"  闸门改动用例 = {len(changed)}",
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
        if done % 20 == 0 or done == len(tasks):
            _snapshot(results, len(tasks), done)

    foc = [r for r in results if r]
    hal_of = sum(1 for r in foc if r["hal_of"])
    hal_nf = sum(1 for r in foc if r["hal_nf"])
    fer_of = sum(1 for r in foc if r["fer_of"])
    fer_nf = sum(1 for r in foc if r["fer_nf"])
    changed = [r for r in foc if r["changed"]]

    out = [
        "=" * 64,
        "[全局 判官驱动修复实验 · 最终结果（讲义口径，无 artifact）]",
        f"配对用例={len(foc)}",
        f"幻觉(讲义): 原 {hal_of} → 修复后 {hal_nf}  (净 {(hal_of-hal_nf):+d}, {(hal_nf/max(1,len(foc))):.1%})",
        f"谬误(讲义): 原 {fer_of} → 修复后 {fer_nf}  (净 {(fer_of-fer_nf):+d}, {(fer_nf/max(1,len(foc))):.1%})",
        f"闸门改动用例={len(changed)}",
        "- 改动用例的 full-text（含原练习/测验，仅用于暴露 artifact） -",
    ]
    for r in changed:
        if "hal_ofull" in r:
            out.append(
                f"  [{r['tc_id']}] 幻觉 full: {int(r['hal_ofull'])}→{int(r['hal_nfull'])} | "
                f"谬误 full: {int(r['fer_ofull'])}→{int(r['fer_nfull'])}"
            )
    out.append("=" * 64)

    text = "\n".join(out)
    print(text, flush=True)
    _RESULT_PATH.write_text(text, encoding="utf-8")
    logger.warning(f"[结果已写入 {_RESULT_PATH}]")


if __name__ == "__main__":
    asyncio.run(main())
