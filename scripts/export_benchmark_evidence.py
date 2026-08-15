"""导出基准评测逐案证据（清洗版，供评审核验，不暴露私有运行态）

只读取 `data/wolegedou.db` 中 `session_id LIKE 'bm_%'` 的 100 个基准用例落库行
（task_metrics + task_resources），与 tests/test_cases_100.json 按归一化问题配对，
输出 data/benchmark_evidence_100.json。

设计原则：
- 仅含基准评测用例（bm_），不含 demo/真实流量；不含 contribution_memory /
  student_profiles / conversations / sessions / elimination_log 等私有运行态。
- 覆盖率使用与 validate_metrics.calc_factual_coverage_rate 完全一致的确定性逻辑
  （reference_answer_points 关键术语命中率，离线、零 LLM），可独立复算 87.9%。
- 适配准确率 / 专业知识谬误率 / 幻觉率 三项由硬化 LLM 裁判（MetricsLLMJudge,
  HIGH 档）在跑分时刻计算，结果未持久化于数据库，本文件仅保留系统自评估字段作佐证，
  完整 4 指标见 docs/metrics_validation_report.md / docs/metrics_summary.md。

用法:
  python -m backend.scripts.export_benchmark_evidence
"""

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEST_CASES_PATH = _PROJECT_ROOT / "tests" / "test_cases_100.json"
DB_PATH = _PROJECT_ROOT / "data" / "wolegedou.db"
OUT_PATH = _PROJECT_ROOT / "data" / "benchmark_evidence_100.json"

_STOP_CHARS = set(
    "的是在与和及对等为有也一个这种那他她它我们你它们被把从到以可可以能会于等及或并且但是因为所以如果当在对于关于通过使用需要应该必须通常一般常见基本主要核心关键其之此该各"
)


def _norm_q(q) -> str:
    return re.sub(r"\s+", "", (q or "").strip().lower())


def _extract_terms(text) -> set:
    if not text:
        return set()
    text = str(text).lower()
    terms = set()
    for m in re.findall(r"[a-z0-9_]{2,}", text):
        terms.add(m)
    for run in re.findall(r"[\u4e00-\u9fff]+", text):
        run = "".join(ch for ch in run if ch not in _STOP_CHARS)
        n = len(run)
        if n >= 2:
            for k in (2, 3):
                for i in range(n - k + 1):
                    terms.add(run[i:i + k])
    return terms


def _resource_text(res: dict) -> str:
    parts = []
    for col in ("lecture", "practice_guide", "quiz", "knowledge_refs"):
        raw = res.get(col)
        if not raw:
            continue
        try:
            obj = json.loads(raw)

            def _walk(o):
                if isinstance(o, str):
                    parts.append(o)
                elif isinstance(o, dict):
                    for v in o.values():
                        _walk(v)
                elif isinstance(o, (list, tuple)):
                    for v in o:
                        _walk(v)

            _walk(obj)
        except Exception:
            parts.append(str(raw))
    return "\n".join(parts)


def _point_covered(point_terms: set, gen_terms: set) -> bool:
    if not point_terms:
        return False
    matched = point_terms & gen_terms
    if not matched:
        return False
    if any(len(t) >= 3 for t in matched):
        return True
    return len(matched) / len(point_terms) >= 0.5


def main():
    test_cases = json.loads(TEST_CASES_PATH.read_text(encoding="utf-8")).get("test_cases", [])
    tc_by_q = {_norm_q(t.get("question", "")): t for t in test_cases}

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    cur.execute("SELECT * FROM task_metrics WHERE session_id LIKE 'bm_%'")
    tm_rows = [dict(r) for r in cur.fetchall()]
    cur.execute(
        "SELECT task_id, question, lecture, practice_guide, quiz, knowledge_refs "
        "FROM task_resources WHERE session_id LIKE 'bm_%'"
    )
    tr_rows = {r["task_id"]: dict(r) for r in cur.fetchall()}
    con.close()

    cases = []
    cov_ratios = []
    for tm in tm_rows:
        task_id = tm["task_id"]
        tr = tr_rows.get(task_id, {})
        norm_q = _norm_q(tr.get("question") or tm.get("session_id"))
        tc = tc_by_q.get(norm_q, {})

        points = tc.get("reference_answer_points") or []
        coverage = None
        if points:
            gen_terms = _extract_terms(_resource_text(tr))
            covered = sum(
                1 for p in points if _point_covered(_extract_terms(p), gen_terms)
            )
            coverage = {
                "covered_points": covered,
                "total_points": len(points),
                "ratio": round(covered / len(points), 4),
            }
            cov_ratios.append(covered / len(points))

        cases.append({
            "case_id": tc.get("id"),
            "task_id": task_id,
            "question": (tc.get("question") or tr.get("question") or "")[:200],
            "expected_complexity": tc.get("expected_complexity"),
            "verdict": tm.get("verdict"),
            "coverage": coverage,
            "verification_rate": tm.get("verification_rate"),
            "traceability_verified": tm.get("traceability_verified"),
            "traceability_total": tm.get("traceability_total"),
            "knowledge_refs_count": tm.get("knowledge_refs_count"),
            "fact_accuracy": tm.get("fact_accuracy"),
            "pedagogical_fit": tm.get("pedagogical_fit"),
            "logic_completeness": tm.get("logic_completeness"),
            "review_score": tm.get("review_score"),
            "override_reason": tm.get("override_reason"),
            "created_at": tm.get("created_at"),
        })

    # 聚合（仅作文件内摘要，便于评审快速核对；非赛题判定依据）
    def _avg(vals):
        vals = [v for v in vals if isinstance(v, (int, float))]
        return round(sum(vals) / len(vals), 4) if vals else None

    summary = {
        "benchmark_cases": len(cases),
        "coverage_rate_deterministic": round(sum(cov_ratios) / len(cov_ratios), 4) if cov_ratios else None,
        "adaptation_self_eval_avg": _avg([c["pedagogical_fit"] for c in cases]),
        "knowledge_traceability_self_eval_avg": _avg([c["verification_rate"] for c in cases]),
        "force_pass_count": sum(1 for c in cases if c["override_reason"] is not None),
        "note": (
            "覆盖率(coverage_rate_deterministic) 使用与 validate_metrics 完全一致的离线关键词命中逻辑，"
            "可由本文件 + tests/test_cases_100.json 独立复算。适配准确率/专业知识谬误率/幻觉率三项由硬化 "
            "LLM 裁判(MetricsLLMJudge, HIGH 档, 去纵容/全文+练习+测验)在跑分时刻计算，结果未持久化于数据库；"
            "本文件保留系统自评估字段作佐证。完整 4 指标与口径见 docs/metrics_validation_report.md 与 docs/metrics_summary.md。"
        ),
    }

    out = {
        "meta": {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source": "data/wolegedou.db: task_metrics/task_resources WHERE session_id LIKE 'bm_%'",
            "paired_with": "tests/test_cases_100.json (by normalized question)",
            "scope": "仅含 100 个基准评测用例，不含 demo/真实流量及任何学生私有运行态",
        },
        "summary": summary,
        "cases": cases,
    }
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已导出 {len(cases)} 条基准证据 -> {OUT_PATH}")
    print(f"确定性覆盖率(复算): {summary['coverage_rate_deterministic']}")
    print(f"自评估适配均值: {summary['adaptation_self_eval_avg']} | 强制放行数: {summary['force_pass_count']}")


if __name__ == "__main__":
    main()
