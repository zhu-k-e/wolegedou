"""离线实验：用已有 task_resources（旧生成）跑增强版 self-heal 补全，预估覆盖率涨幅。

不重跑 FSM（省 2.7h），仅对每条例证讲义做「覆盖自检+KB补全」，再用官方字面覆盖率算法
对比补全前后。目标：几分钟预估「生成器补缺」能否把覆盖率从 ~85.8% 抬过 90%。

诚信约束：self-heal 的补全源是系统自有 KB（与 benchmark 评测要点完全独立），非测试集。
"""

import asyncio
import json
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

_RESULT_PATH = _PROJECT_ROOT / "data" / "offline_selfheal_experiment_result.txt"
_CONCURRENCY = 4


def _replace_lecture_content(res: dict, new_content: str) -> dict:
    """把 task_resources 里 lecture JSON 的 content_markdown 换成补全后的文本。"""
    new_res = dict(res)
    raw = res.get("lecture")
    try:
        obj = json.loads(raw) if raw else {}
    except Exception:
        obj = {}
    if isinstance(obj, dict):
        obj["content_markdown"] = new_content
        new_res["lecture"] = json.dumps(obj, ensure_ascii=False)
    else:
        new_res["lecture"] = new_content
    return new_res


async def _process_one(agent: DomainAgent, calc: MetricsCalculator, tc: dict, res: dict, sem):
    async with sem:
        q = tc.get("question", "")
        refs = tc.get("reference_answer_points") or []
        if not refs:
            return None
        profile = _build_profile(tc) or None
        old_gt = calc._resource_text(res)
        old_gt_terms = calc._extract_terms(old_gt)
        old_cov = sum(1 for pt in refs if calc._point_covered(calc._extract_terms(pt), old_gt_terms))

        # 用旧 lecture 的 conclusion 构造 FocusedOutput 喂给增强 self-heal
        lec = {}
        try:
            lec = json.loads(res.get("lecture") or "{}")
        except Exception:
            lec = {}
        if not isinstance(lec, dict):
            lec = {}
        old_conclusion = lec.get("content_markdown") or lec.get("conclusion") or ""
        steps = list(lec.get("reasoning_steps") or [])
        while len(steps) < 3:
            steps.append("")  # 占位，不贡献覆盖率词；仅为通过 pydantic 校验
        focused = FocusedOutput(
            conclusion=old_conclusion,
            reasoning_steps=steps,
            knowledge_refs=[],
            applicable_conditions=lec.get("applicable_conditions") or "",
            code_example=lec.get("code_example"),
            difficulty_note=lec.get("difficulty_note") or "",
        )
        try:
            healed = await agent._self_heal_focused_output(q, profile, focused)
            new_conclusion = healed.conclusion or old_conclusion
        except Exception as e:
            logger.warning(f"self-heal 失败 [{q[:30]}]: {e}")
            new_conclusion = old_conclusion

        new_res = _replace_lecture_content(res, new_conclusion)
        new_gt = calc._resource_text(new_res)
        new_gt_terms = calc._extract_terms(new_gt)
        new_cov = sum(1 for pt in refs if calc._point_covered(calc._extract_terms(pt), new_gt_terms))

        return {
            "tc_id": tc.get("id"),
            "n_pts": len(refs),
            "old_cov": old_cov,
            "new_cov": new_cov,
            "supp_added": max(0, new_cov - old_cov),
        }


async def main():
    init_knowledge_base()
    agent = DomainAgent("agent_004")  # RAG 架构 Agent，检索全 KB 均可 fallback
    calc = MetricsCalculator(bm_only=True, use_llm=False)
    pairs = calc._build_pairs()
    logger.warning(f"配对用例数: {len(pairs)}")

    sem = asyncio.Semaphore(_CONCURRENCY)
    tasks = [_process_one(agent, calc, tc, res, sem) for tc, res in pairs]
    results = []
    done = 0
    for coro in asyncio.as_completed(tasks):
        r = await coro
        if r:
            results.append(r)
        done += 1
        # 实时累计落盘，避免进程被回收丢结果
        if done % 5 == 0 or done == len(tasks):
            old_total = sum(x["old_cov"] for x in results)
            new_total = sum(x["new_cov"] for x in results)
            pt_total = sum(x["n_pts"] for x in results)
            old_rate = old_total / pt_total if pt_total else 0
            new_rate = new_total / pt_total if pt_total else 0
            lines = [
                f"[离线 self-heal 实验] 已处理 {done}/{len(tasks)}",
                f"参考要点总数={pt_total}",
                f"旧字面覆盖率={old_rate:.1%} ({old_total}/{pt_total})",
                f"补全后字面覆盖率={new_rate:.1%} ({new_total}/{pt_total})",
                f"净增覆盖要点={new_total - old_total}",
            ]
            _RESULT_PATH.write_text("\n".join(lines), encoding="utf-8")

    old_total = sum(x["old_cov"] for x in results)
    new_total = sum(x["new_cov"] for x in results)
    pt_total = sum(x["n_pts"] for x in results)
    old_rate = old_total / pt_total if pt_total else 0
    new_rate = new_total / pt_total if pt_total else 0
    explicit = sum(1 for x in results if x["supp_added"] > 0)

    out = [
        "=" * 60,
        "[离线 self-heal 补全实验 · 最终结果]",
        f"配对用例={len(results)}  参考要点总数={pt_total}",
        f"旧字面覆盖率   = {old_rate:.2%}  ({old_total}/{pt_total})",
        f"补全后字面覆盖率 = {new_rate:.2%}  ({new_total}/{pt_total})",
        f"净增覆盖要点    = {new_total - old_total}",
        f"发生补全的用例数 = {explicit}/{len(results)}",
        "=" * 60,
    ]
    text = "\n".join(out)
    print(text, flush=True)
    _RESULT_PATH.write_text(text, encoding="utf-8")
    logger.warning(f"[结果已写入 {_RESULT_PATH}]")


if __name__ == "__main__":
    asyncio.run(main())
