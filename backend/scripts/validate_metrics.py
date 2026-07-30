"""量化指标验证脚本（方案书第七部分）

对齐赛题 4 项量化指标，从数据库自动统计 + 知识库召回率测试：
  1. 专业知识谬误率 < 5%  (目标 <=3%)  — Verifier 事实准确率代理指标
  2. 适配准确率 >= 85%    (目标 >=90%) — Evaluator 教学适配度 + 学生反馈
  3. 核心知识点覆盖率 >= 90% (目标 >=95%) — 裁判团溯源验证率
  4. 幻觉率（附加）       (目标 <=3%)  — 裁判团 verdict 分布

用法:
  python -m backend.scripts.validate_metrics              # 全量验证
  python -m backend.scripts.validate_metrics --kb-only     # 仅知识库召回率测试
  python -m backend.scripts.validate_metrics --no-kb       # 跳过知识库测试（无需加载 bge-m3）
"""

import asyncio
import sys
import os
from datetime import datetime
from pathlib import Path

# 确保项目根在 sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from backend.db.database import query_all, query_one
from loguru import logger

# ============================================================
# 指标目标值（方案书 7.1 节）
# ============================================================

TARGETS = {
    "error_rate":      {"target": 0.03, "compare": "<=", "label": "专业知识谬误率", "unit": "%"},
    "adaptation_rate": {"target": 0.90, "compare": ">=", "label": "适配准确率",     "unit": "%"},
    "coverage_rate":   {"target": 0.95, "compare": ">=", "label": "核心知识点覆盖率", "unit": "%"},
    "hallucination_rate": {"target": 0.03, "compare": "<=", "label": "幻觉率", "unit": "%"},
    "force_pass_rate":    {"target": 0.05, "compare": "<=", "label": "强制放行率",     "unit": "%"},
}

# ============================================================
# 知识库召回率测试用例（方案书 7.2.3 节跨语言检索）
# ============================================================

KB_TEST_QUERIES = [
    {"query": "什么是大语言模型LLM", "expected_agent": "LLM基础Agent", "description": "中文→LLM基础"},
    {"query": "How to fine-tune a language model", "expected_agent": "模型微调Agent", "description": "英文→模型微调"},
    {"query": "HuggingFace transformers库怎么用", "expected_agent": "HuggingFace调用Agent", "description": "中文→HuggingFace"},
    {"query": "向量数据库FAISS Milvus对比", "expected_agent": "向量数据库Agent", "description": "中文→向量数据库"},
    {"query": "prompt engineering技巧", "expected_agent": "Prompt工程Agent", "description": "中文→Prompt工程"},
    {"query": "RAG检索增强生成架构", "expected_agent": "RAG架构Agent", "description": "中文→RAG架构"},
    {"query": "LangChain chain组件用法", "expected_agent": "LangChain组件Agent", "description": "中文→LangChain"},
    {"query": "AI agent框架设计", "expected_agent": "Agent框架Agent", "description": "中文→Agent框架"},
    {"query": "how to debug python code in AI project", "expected_agent": "代码调试Agent", "description": "英文→代码调试"},
    {"query": "大模型项目实战部署流程", "expected_agent": "项目实战Agent", "description": "中文→项目实战"},
]


# ============================================================
# 指标计算
# ============================================================

class MetricsCalculator:
    """从数据库计算 4 项量化指标"""

    def __init__(self):
        self.task_metrics = query_all("SELECT * FROM task_metrics")
        self.contribution_memory = query_all("SELECT * FROM contribution_memory")
        self.student_feedback = query_all("SELECT * FROM student_feedback")

    @property
    def has_data(self) -> bool:
        return len(self.task_metrics) > 0 or len(self.contribution_memory) > 0

    # --- 指标1: 专业知识谬误率 ---
    def calc_error_rate(self) -> dict:
        """谬误率 = 1 - avg(fact_accuracy)

        fact_accuracy 来自 Verifier 事实核查评分（0-1）。
        谬误率 ≈ 1 - 事实准确率，作为代理指标。
        数据源优先级: task_metrics.fact_accuracy > contribution_memory.review_score
        """
        # 优先用 task_metrics 的 fact_accuracy
        fact_scores = [
            r["fact_accuracy"] for r in self.task_metrics
            if r["fact_accuracy"] is not None
        ]
        source = "task_metrics.fact_accuracy"

        if not fact_scores:
            # fallback: contribution_memory.review_score（含逻辑+适配，非纯事实分）
            review_scores = [
                r["review_score"] for r in self.contribution_memory
                if r["review_score"] is not None
            ]
            if review_scores:
                avg = sum(review_scores) / len(review_scores)
                return {
                    "value": 1.0 - avg,
                    "sample_count": len(review_scores),
                    "source": "contribution_memory.review_score (fallback, 含逻辑+适配分)",
                    "detail": f"avg_review_score={avg:.3f}",
                }
            return {"value": None, "sample_count": 0, "source": "无数据", "detail": ""}

        avg_fact = sum(fact_scores) / len(fact_scores)
        return {
            "value": 1.0 - avg_fact,
            "sample_count": len(fact_scores),
            "source": source,
            "detail": f"avg_fact_accuracy={avg_fact:.3f}",
        }

    # --- 指标2: 适配准确率 ---
    def calc_adaptation_rate(self) -> dict:
        """适配准确率 = avg(pedagogical_fit) 或 1 - difficulty_mismatch_ratio

        优先用 task_metrics.pedagogical_fit（Evaluator 教学适配度）。
        如有学生反馈，补充计算 difficulty_mismatch 比率。
        """
        peda_scores = [
            r["pedagogical_fit"] for r in self.task_metrics
            if r["pedagogical_fit"] is not None
        ]
        source = "task_metrics.pedagogical_fit"

        if not peda_scores:
            # fallback: contribution_memory.review_score
            review_scores = [
                r["review_score"] for r in self.contribution_memory
                if r["review_score"] is not None
            ]
            if review_scores:
                avg = sum(review_scores) / len(review_scores)
                return {
                    "value": avg,
                    "sample_count": len(review_scores),
                    "source": "contribution_memory.review_score (fallback)",
                    "detail": f"avg_review_score={avg:.3f}",
                }
            return {"value": None, "sample_count": 0, "source": "无数据", "detail": ""}

        avg_peda = sum(peda_scores) / len(peda_scores)

        # 补充: 学生反馈中的 difficulty_mismatch
        total_feedback = len(self.student_feedback)
        mismatch_count = sum(
            1 for f in self.student_feedback
            if f["feedback_type"] == "difficulty_mismatch"
        )
        detail = f"avg_pedagogical_fit={avg_peda:.3f}"
        if total_feedback > 0:
            mismatch_rate = mismatch_count / total_feedback
            detail += f", student_feedback: {mismatch_count}/{total_feedback} mismatch ({mismatch_rate:.1%})"

        return {
            "value": avg_peda,
            "sample_count": len(peda_scores),
            "source": source,
            "detail": detail,
        }

    # --- 指标3: 核心知识点覆盖率 ---
    def calc_coverage_rate(self) -> dict:
        """覆盖率 = avg(verification_rate) 或 traceability_verified / traceability_total

        verification_rate 来自裁判团溯源标注的验证率（overall_verification_rate）。
        """
        # 优先用 task_metrics.verification_rate
        vr_scores = [
            r["verification_rate"] for r in self.task_metrics
            if r["verification_rate"] is not None
        ]
        source = "task_metrics.verification_rate"

        if not vr_scores:
            return {"value": None, "sample_count": 0, "source": "无数据", "detail": ""}

        avg_vr = sum(vr_scores) / len(vr_scores)

        # 补充: traceability 统计
        total_trace = sum(r["traceability_total"] or 0 for r in self.task_metrics)
        verified_trace = sum(r["traceability_verified"] or 0 for r in self.task_metrics)
        detail = f"avg_verification_rate={avg_vr:.3f}"
        if total_trace > 0:
            trace_ratio = verified_trace / total_trace
            detail += f", traceability: {verified_trace}/{total_trace} verified ({trace_ratio:.1%})"

        # 补充: knowledge_refs_count
        total_refs = sum(r["knowledge_refs_count"] or 0 for r in self.task_metrics)
        detail += f", total_knowledge_refs={total_refs}"

        return {
            "value": avg_vr,
            "sample_count": len(vr_scores),
            "source": source,
            "detail": detail,
        }

    # --- 指标4: 幻觉率 ---
    def calc_hallucination_rate(self) -> dict:
        """幻觉率 = count(verdict IN ('failed', 'revise')) / total

        裁判团未通过的输出占比（方案书 7.1 节定义）。
        'failed' 和 'revise' 表示输出有问题，视为幻觉代理指标。
        """
        # 优先用 task_metrics.verdict
        if self.task_metrics:
            total = len(self.task_metrics)
            hallucination_count = sum(
                1 for r in self.task_metrics
                if r["verdict"] in ("failed", "revise")
            )
            source = "task_metrics.verdict"
            detail_parts = []
            for v in ("passed", "low_confidence_passed", "revise", "failed"):
                c = sum(1 for r in self.task_metrics if r["verdict"] == v)
                if c > 0:
                    detail_parts.append(f"{v}={c}")
            return {
                "value": hallucination_count / total if total > 0 else None,
                "sample_count": total,
                "source": source,
                "detail": ", ".join(detail_parts),
            }

        # fallback: contribution_memory.referee_verdict
        if self.contribution_memory:
            total = len(self.contribution_memory)
            hallucination_count = sum(
                1 for r in self.contribution_memory
                if r["referee_verdict"] in ("failed", "revise")
            )
            return {
                "value": hallucination_count / total if total > 0 else None,
                "sample_count": total,
                "source": "contribution_memory.referee_verdict",
                "detail": f"failed+revise={hallucination_count}/{total}",
            }

        return {"value": None, "sample_count": 0, "source": "无数据", "detail": ""}

    # --- 附加指标: 强制放行率 ---
    def calc_force_pass_rate(self) -> dict:
        """强制放行率 = count(override_reason IS NOT NULL) / total

        全票失败终审仍不通过但放行 + 修改超上限强制通过 的占比。
        用户要求：全票失败可以放行，但这种情况必须特别少。目标 <=5%。
        """
        if not self.task_metrics:
            return {"value": None, "sample_count": 0, "source": "无数据", "detail": ""}

        total = len(self.task_metrics)
        try:
            force_pass_count = sum(
                1 for r in self.task_metrics
                if r["override_reason"] is not None
            )
            detail_parts = []
            for reason in ("unanimous_fail_force_pass", "revision_limit_force_pass"):
                c = sum(
                    1 for r in self.task_metrics
                    if r["override_reason"] == reason
                )
                if c > 0:
                    detail_parts.append(f"{reason}={c}")
        except (KeyError, IndexError):
            return {
                "value": None,
                "sample_count": total,
                "source": "task_metrics.override_reason (列不存在，需迁移)",
                "detail": "请重新初始化数据库",
            }

        return {
            "value": force_pass_count / total if total > 0 else None,
            "sample_count": total,
            "source": "task_metrics.override_reason",
            "detail": ", ".join(detail_parts) if detail_parts else "无强制放行",
        }

    def calc_all(self) -> dict:
        return {
            "error_rate": self.calc_error_rate(),
            "adaptation_rate": self.calc_adaptation_rate(),
            "coverage_rate": self.calc_coverage_rate(),
            "hallucination_rate": self.calc_hallucination_rate(),
            "force_pass_rate": self.calc_force_pass_rate(),
        }


# ============================================================
# 知识库召回率测试
# ============================================================

async def test_kb_recall(top_k: int = 3, score_threshold: float = 0.3) -> dict:
    """知识库召回率测试（方案书 7.2.3 节）

    对预定义 query 逐个检索知识库，检查:
    1. 是否返回结果（非空）
    2. Top-1 score 是否超过阈值
    3. filter_agent 是否匹配预期 Agent
    """
    from backend.services.rag.kb_manager import init_knowledge_base
    from backend.services.knowledge_base import get_knowledge_base

    init_knowledge_base()
    kb = get_knowledge_base()

    results = []
    hit_count = 0

    for tc in KB_TEST_QUERIES:
        try:
            hits = await kb.search(
                query=tc["query"],
                top_k=top_k,
                score_threshold=score_threshold,
                filter_agent=tc["expected_agent"],
            )
        except Exception as e:
            results.append({
                "query": tc["query"],
                "description": tc["description"],
                "hit": False,
                "top_score": 0.0,
                "result_count": 0,
                "agent_match": False,
                "error": str(e),
            })
            continue

        top_score = hits[0].score if hits else 0.0
        agent_match = any(
            tc["expected_agent"] in (h.metadata.get("applicable_agents", "") or "")
            for h in hits
        ) if hits else False
        hit = len(hits) > 0 and top_score >= score_threshold

        if hit:
            hit_count += 1

        results.append({
            "query": tc["query"],
            "description": tc["description"],
            "hit": hit,
            "top_score": round(top_score, 4),
            "result_count": len(hits),
            "agent_match": agent_match,
            "error": None,
        })

    return {
        "total": len(KB_TEST_QUERIES),
        "hit_count": hit_count,
        "recall_rate": hit_count / len(KB_TEST_QUERIES) if KB_TEST_QUERIES else 0.0,
        "details": results,
    }


# ============================================================
# 报告输出
# ============================================================

def _format_value(value, unit: str) -> str:
    if value is None:
        return "N/A"
    pct = value * 100
    return f"{pct:.1f}{unit}"


def _pass_fail(value, target, compare: str) -> str:
    if value is None:
        return "N/A (无数据)"
    if compare == "<=":
        return "PASS" if value <= target else "FAIL"
    else:
        return "PASS" if value >= target else "FAIL"


def print_console_report(metrics: dict, kb_result: dict | None, targets: dict):
    """控制台表格输出"""
    print()
    print("=" * 80)
    print("  量化指标验证报告（方案书第七部分）")
    print(f"  生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    # 4 项核心指标
    print()
    print("  [核心指标]")
    print(f"  {'指标':<20s} {'实际值':>8s} {'目标值':>8s} {'结果':>6s}  {'样本数':>6s}  数据来源")
    print("  " + "-" * 76)

    for key in ["error_rate", "adaptation_rate", "coverage_rate", "hallucination_rate", "force_pass_rate"]:
        m = metrics[key]
        t = targets[key]
        val_str = _format_value(m["value"], t["unit"])
        tgt_str = _format_value(t["target"], t["unit"])
        pf = _pass_fail(m["value"], t["target"], t["compare"])
        print(f"  {t['label']:<20s} {val_str:>8s} {tgt_str:>8s} {pf:>6s}  {m['sample_count']:>6d}  {m['source']}")

    # 指标详情
    print()
    print("  [指标详情]")
    for key in ["error_rate", "adaptation_rate", "coverage_rate", "hallucination_rate", "force_pass_rate"]:
        m = metrics[key]
        t = targets[key]
        if m["detail"]:
            print(f"    {t['label']}: {m['detail']}")

    # 知识库召回率
    if kb_result:
        print()
        print("  [知识库召回率测试]")
        print(f"  召回率: {kb_result['hit_count']}/{kb_result['total']} = {kb_result['recall_rate']:.1%}")
        print(f"  {'Query':<40s} {'命中':>4s} {'Top分数':>8s} {'结果数':>6s} {'Agent匹配':>10s}  说明")
        print("  " + "-" * 76)
        for d in kb_result["details"]:
            hit_str = "Y" if d["hit"] else "N"
            match_str = "Y" if d["agent_match"] else "N"
            err = f" [ERROR: {d['error']}]" if d["error"] else ""
            print(f"  {d['query'][:38]:<40s} {hit_str:>4s} {d['top_score']:>8.4f} {d['result_count']:>6d} {match_str:>10s}  {d['description']}{err}")

    print()
    print("=" * 80)
    print()


def generate_markdown_report(metrics: dict, kb_result: dict | None, targets: dict) -> str:
    """生成 Markdown 报告"""
    lines = [
        f"# 量化指标验证报告",
        f"",
        f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"> 对应方案书: 第七部分 指标与验证（7.1 节赛题指标映射 + 7.2.3 节验证方法）",
        f"",
        f"## 1. 核心指标汇总",
        f"",
        f"| 指标 | 实际值 | 目标值 | 结果 | 样本数 | 数据来源 |",
        f"|------|--------|--------|------|--------|----------|",
    ]

    for key in ["error_rate", "adaptation_rate", "coverage_rate", "hallucination_rate", "force_pass_rate"]:
        m = metrics[key]
        t = targets[key]
        val_str = _format_value(m["value"], t["unit"])
        tgt_str = _format_value(t["target"], t["unit"])
        pf = _pass_fail(m["value"], t["target"], t["compare"])
        lines.append(f"| {t['label']} | {val_str} | {tgt_str} | {pf} | {m['sample_count']} | {m['source']} |")

    lines.append("")
    lines.append("## 2. 指标详情")
    lines.append("")

    detail_map = {
        "error_rate": "专业知识谬误率",
        "adaptation_rate": "适配准确率",
        "coverage_rate": "核心知识点覆盖率",
        "hallucination_rate": "幻觉率",
        "force_pass_rate": "强制放行率（全票失败/修改超限强制通过）",
    }
    for key, label in detail_map.items():
        m = metrics[key]
        lines.append(f"### {label}")
        lines.append(f"- **计算方式**: {m['detail'] or '无详情'}")
        lines.append(f"- **数据来源**: {m['source']}")
        lines.append(f"- **样本数**: {m['sample_count']}")
        lines.append("")

    if kb_result:
        lines.append("## 3. 知识库召回率测试")
        lines.append("")
        lines.append(f"召回率: **{kb_result['hit_count']}/{kb_result['total']} = {kb_result['recall_rate']:.1%}**")
        lines.append("")
        lines.append("| Query | 命中 | Top分数 | 结果数 | Agent匹配 | 说明 |")
        lines.append("|-------|------|---------|--------|-----------|------|")
        for d in kb_result["details"]:
            hit_str = "Y" if d["hit"] else "N"
            match_str = "Y" if d["agent_match"] else "N"
            err = f" [ERROR: {d['error']}]" if d["error"] else ""
            lines.append(f"| {d['query']} | {hit_str} | {d['top_score']:.4f} | {d['result_count']} | {match_str} | {d['description']}{err} |")
        lines.append("")

    lines.append("## 4. 验证方法说明")
    lines.append("")
    lines.append("| 指标 | 方案书定义 | 自动化方式 |")
    lines.append("|------|-----------|-----------|")
    lines.append("| 专业知识谬误率 | 100道测试题人工核验 | Verifier fact_accuracy 代理指标（1 - avg(fact_accuracy)） |")
    lines.append("| 适配准确率 | 20组学情测试+模拟学生评估 | Evaluator pedagogical_fit 均值 + 学生 difficulty_mismatch 反馈 |")
    lines.append("| 核心知识点覆盖率 | 知识库召回率测试+溯源覆盖率 | 裁判团 overall_verification_rate 均值 + traceability 统计 |")
    lines.append("| 幻觉率 | 裁判团 verdict 分布 | count(verdict in failed/revise) / total |")
    lines.append("| 强制放行率 | 全票失败/修改超限的强制放行占比 | count(override_reason IS NOT NULL) / total |")
    lines.append("")
    lines.append("> 注: 人工核验指标（谬误率）使用审核评分作为代理指标，实际谬误率需人工标注确认。")
    lines.append("")

    return "\n".join(lines)


# ============================================================
# 主入口
# ============================================================

def main(run_kb: bool = True):
    logger.info("开始量化指标验证...")

    # 1. 从 DB 计算指标
    calc = MetricsCalculator()
    if not calc.has_data:
        print()
        print("WARNING: 数据库中无 task_metrics 或 contribution_memory 数据。")
        print("  请先运行系统产生数据，或使用 --kb-only 仅测试知识库召回率。")
        print()
    metrics = calc.calc_all()

    # 2. 知识库召回率测试（可选）
    kb_result = None
    if run_kb:
        logger.info("开始知识库召回率测试（需加载 bge-m3，约 10s）...")
        try:
            kb_result = asyncio.run(test_kb_recall())
        except Exception as e:
            logger.warning(f"知识库召回率测试失败: {e}")
            kb_result = None

    # 3. 输出报告
    print_console_report(metrics, kb_result, TARGETS)

    # 4. 写 Markdown 报告
    report_dir = _PROJECT_ROOT / "docs"
    report_path = report_dir / "metrics_validation_report.md"
    md = generate_markdown_report(metrics, kb_result, TARGETS)
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path.write_text(md, encoding="utf-8")
    print(f"Markdown 报告已保存: {report_path}")

    # 5. 返回退出码（有 FAIL 则非零）
    has_fail = False
    for key, t in TARGETS.items():
        m = metrics[key]
        if m["value"] is not None:
            if t["compare"] == "<=" and m["value"] > t["target"]:
                has_fail = True
            elif t["compare"] == ">=" and m["value"] < t["target"]:
                has_fail = True

    return 1 if has_fail else 0


if __name__ == "__main__":
    args = sys.argv[1:]
    run_kb = True
    if "--no-kb" in args:
        run_kb = False
    if "--kb-only" in args:
        run_kb = True
        # 跳过 DB 指标，仅跑 KB
        logger.info("仅测试知识库召回率...")
        kb_result = asyncio.run(test_kb_recall())
        print()
        print("=" * 80)
        print("  知识库召回率测试报告")
        print("=" * 80)
        print(f"  召回率: {kb_result['hit_count']}/{kb_result['total']} = {kb_result['recall_rate']:.1%}")
        print()
        for d in kb_result["details"]:
            hit_str = "Y" if d["hit"] else "N"
            print(f"  [{hit_str}] {d['query'][:40]:<42s} score={d['top_score']:.4f}  {d['description']}")
        print()
        sys.exit(0)

    sys.exit(main(run_kb=run_kb))
