"""基准评测脚本 —— 跑 test_cases_100.json 全集，生成资源落库供事实比对指标使用

复用与 /api/ask 完全一致的编排路径（Orchestrator.process_question），把每个用例当作一次
真实提问，落库到 task_resources（事实比对覆盖率/适配率数据源）与 task_metrics（代理指标数据源）。

设计要点：
  - 离线运行，不影响线上服务调用时间（独立进程）。
  - 断点续跑：已落库的归一化问题直接跳过，可反复运行直至 100 条全部完成。
  - 可 pilot：--limit / --start 控制范围，先小批量验证管线。
  - 并发：--concurrency 控制同时进行的用例数（默认 1，避免触发 LLM 限流）。

用法：
  python -m backend.scripts.benchmark_testcases                 # 跑完全部 100 条（断点续跑）
  python -m backend.scripts.benchmark_testcases --limit 10      # 先跑前 10 条做 pilot
  python -m backend.scripts.benchmark_testcases --start 10 --limit 20 --concurrency 2
"""

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from loguru import logger

from backend.core.orchestrator import Orchestrator
from backend.db.resource_store import save_task_resources, ensure_task_resources_table
from backend.db.database import execute_sql, query_all
from backend.services import compliance
from backend.services.knowledge_base import get_knowledge_base
from backend.services.rag.kb_manager import init_knowledge_base

_TEST_PATH = _PROJECT_ROOT / "tests" / "test_cases_100.json"


def _norm_q(q) -> str:
    return re.sub(r"\s+", "", (q or "").strip().lower())


def _save_task_metrics(session_id: str, result: dict) -> None:
    """与 /api/ask 中 _save_task_metrics 一致的指标落库（代理指标数据源）"""
    jv = result.get("judge_verdict")
    if not jv or not isinstance(jv, dict):
        return

    verdict = jv.get("verdict")
    verification_rate = jv.get("overall_verification_rate")
    override_reason = jv.get("override_reason")

    traceability = jv.get("traceability", [])
    traceability_total = len(traceability)
    traceability_verified = sum(
        1 for t in traceability
        if isinstance(t, dict) and t.get("verification_status") == "已验证"
    )
    knowledge_refs_count = result.get("knowledge_refs_count", 0)

    rs = result.get("review_summary") or {}
    fact_accuracy = rs.get("fact_accuracy")
    logic_completeness = rs.get("logic_completeness")
    pedagogical_fit = rs.get("pedagogical_fit")
    scores_list = [s for s in [fact_accuracy, logic_completeness, pedagogical_fit] if s is not None]
    review_score = sum(scores_list) / len(scores_list) if scores_list else None

    compliance.ensure_session(session_id)

    execute_sql(
        """INSERT INTO task_metrics
           (task_id, session_id, verdict, verification_rate,
            traceability_total, traceability_verified, knowledge_refs_count,
            fact_accuracy, logic_completeness, pedagogical_fit, review_score,
            override_reason)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            result.get("task_id"), session_id, verdict, verification_rate,
            traceability_total, traceability_verified, knowledge_refs_count,
            fact_accuracy, logic_completeness, pedagogical_fit, review_score,
            override_reason,
        ),
    )


def _load_cases() -> list:
    data = json.loads(_TEST_PATH.read_text(encoding="utf-8"))
    return data.get("test_cases", [])


def _done_set() -> set:
    try:
        rows = query_all("SELECT question FROM task_resources WHERE question IS NOT NULL")
        return {_norm_q(r["question"]) for r in rows}
    except Exception:
        return set()


async def run_one(orch: Orchestrator, tc: dict, done: set) -> dict:
    q = tc.get("question", "")
    tc_id = tc.get("id", "?")
    if _norm_q(q) in done:
        return {"id": tc_id, "status": "skipped"}

    session_id = f"bm_{tc_id}"
    t0 = time.time()
    try:
        result = await orch.process_question(question=q, session_id=session_id, history=[])
    except Exception as e:
        return {"id": tc_id, "status": "error", "detail": str(e)[:200]}

    if result.get("error"):
        return {"id": tc_id, "status": "error", "detail": str(result["error"])[:200]}

    # 落库（与 /api/ask 一致的容错逻辑）
    try:
        compliance.ensure_session(session_id)
        _save_task_metrics(session_id, result)
        save_task_resources(result.get("task_id"), session_id, result, q)
    except Exception as e:
        logger.warning(f"[{tc_id}] 落库失败: {e}")
        return {"id": tc_id, "status": "stored_partial", "detail": str(e)[:200], "elapsed": time.time() - t0}

    return {"id": tc_id, "status": "ok", "elapsed": time.time() - t0}


async def main(limit: int | None, start: int, concurrency: int) -> int:
    # 关键：必须与 API 服务（main.py lifespan）一致地初始化知识库。
    # 否则全局是 StubKnowledgeBase（检索恒空），会导致：
    #   1) 领域 Agent 的 RAG 增强失效 → 生成资源质量低于真实服务；
    #   2) 裁判团溯源全部“待验证” → verification_rate 恒为 0；
    #   3) Verifier 拿到空检索结果 → fact_accuracy 给 0.0 或兜底 0.5。
    # 即基准评测必须跑在与线上同等条件下，指标才有意义。
    init_knowledge_base()
    kb = get_knowledge_base()
    kb_name = type(kb).__name__
    logger.info(f"知识库后端: {kb_name}")
    if kb_name == "StubKnowledgeBase":
        logger.error(
            "知识库为 Stub（检索恒空），基准评测结果无效：资源质量与溯源率都会被严重低估。"
            "请检查 data/numpy_kb/ 数据与 bge-m3 模型是否就绪后重试。"
        )
        return 2

    cases = _load_cases()
    total = len(cases)
    logger.info(f"基准用例总数: {total}")

    done = _done_set()
    logger.info(f"已完成(已落库)问题数: {len(done)}")

    pending = [c for c in cases if _norm_q(c.get("question", "")) not in done]
    # 切片
    if start:
        pending = pending[start:]
    if limit is not None:
        pending = pending[:limit]

    if not pending:
        logger.info("没有待跑用例，全部已完成。")
        return 0

    logger.info(f"本次待跑: {len(pending)} 条（start={start}, limit={limit}, concurrency={concurrency}）")

    orch = Orchestrator()
    sem = asyncio.Semaphore(max(1, concurrency))
    stats = {"ok": 0, "error": 0, "skipped": 0, "stored_partial": 0}

    async def _runner(tc):
        async with sem:
            return await run_one(orch, tc, done)

    t_start = time.time()
    results = []
    for fut in asyncio.as_completed([_runner(c) for c in pending]):
        r = await fut
        stats[r["status"]] = stats.get(r["status"], 0) + 1
        results.append(r)
        el = r.get("elapsed")
        el_s = f"{el:.1f}s" if el is not None else "-"
        logger.info(f"  [{r['id']}] {r['status']} ({el_s}) {r.get('detail', '')}")

    dt = time.time() - t_start
    logger.info("=" * 60)
    logger.info(f"完成: ok={stats.get('ok',0)} error={stats.get('error',0)} "
                f"partial={stats.get('stored_partial',0)} 耗时={dt:.1f}s")
    logger.info(f"剩余待跑(含已跳过已完成的): 共 {total} 条，本次新增完成 {stats.get('ok',0)+stats.get('stored_partial',0)} 条")
    logger.info("下一步: python -m backend.scripts.validate_metrics --no-kb  查看事实比对指标")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="跑 test_cases_100 基准用例生成资源落库")
    parser.add_argument("--limit", type=int, default=None, help="本次最多跑多少条")
    parser.add_argument("--start", type=int, default=0, help="从第几条(已过滤已完成后)开始")
    parser.add_argument("--concurrency", type=int, default=1, help="并发数(默认1)")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(limit=args.limit, start=args.start, concurrency=args.concurrency)))
