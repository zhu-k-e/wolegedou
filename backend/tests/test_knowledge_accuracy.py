"""领域知识生成准确性 —— 核心度量逻辑单元测试 + 真实数据一致性回归。

赛题要求：单元测试用例需针对"领域知识生成准确性"等核心模块。
本测试验证 4 指标中【核心知识点覆盖率】的判定逻辑正确性
（术语抽取 + 覆盖判定），并对照真实 benchmark 数据做一次可处理性回归，
确保度量口径稳定、可复现（与 docs/metrics_validation_report.md 一致）。
"""
import json
import sqlite3
from pathlib import Path

import pytest

from backend.scripts.validate_metrics import MetricsCalculator

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REAL_DB = PROJECT_ROOT / "data" / "wolegedou.db"


# ------------------------------------------------------------
# 术语抽取（覆盖判定的输入）
# ------------------------------------------------------------
def test_extract_terms_chinese_ngram():
    terms = MetricsCalculator._extract_terms("LangGraph 规划-执行-审查模式")
    assert "langgraph" in terms
    # 中文 2/3-gram 应包含连续子串，保证细粒度知识点可被命中
    assert any("规划" in t for t in terms)
    assert any("执行" in t for t in terms)
    assert any("审查" in t for t in terms)


def test_extract_terms_english_word():
    terms = MetricsCalculator._extract_terms("Use temperature and top_p parameters")
    assert "temperature" in terms
    assert "top_p" in terms


def test_extract_terms_empty():
    assert MetricsCalculator._extract_terms("") == set()
    assert MetricsCalculator._extract_terms(None) == set()


# ------------------------------------------------------------
# 覆盖判定（生成内容是否命中参考知识点）
# ------------------------------------------------------------
def test_point_covered_full_match():
    point = MetricsCalculator._extract_terms("temperature 参数调优")
    gen = MetricsCalculator._extract_terms("我们通过调整 temperature 参数来完成调优")
    assert MetricsCalculator._point_covered(point, gen) is True


def test_point_covered_partial_miss():
    # 参考点列了多个子知识点，生成只覆盖部分核心词 → 判定未覆盖
    point = MetricsCalculator._extract_terms("presence_penalty frequency_penalty 采样参数")
    gen = MetricsCalculator._extract_terms("使用 temperature 与 top_p 控制生成")
    assert MetricsCalculator._point_covered(point, gen) is False


def test_point_covered_strong_signal_3gram():
    # 强信号：连续 3-gram 命中即算覆盖，避免漏判
    point = MetricsCalculator._extract_terms("规划-执行-审查闭环")
    gen = MetricsCalculator._extract_terms("系统采用规划-执行-审查的闭环架构")
    assert MetricsCalculator._point_covered(point, gen) is True


def test_point_covered_threshold_robustness():
    # 强信号：命中任一长度>=3的术语即判覆盖
    point_long = MetricsCalculator._extract_terms("temperature learning")
    assert MetricsCalculator._point_covered(
        point_long, MetricsCalculator._extract_terms("temperature")) is True
    # 无命中：判未覆盖
    point_x = MetricsCalculator._extract_terms("xyzabc qwerty")
    assert MetricsCalculator._point_covered(
        point_x, MetricsCalculator._extract_terms("nomatch")) is False
    # 占比逻辑（全短词、无强信号）：命中 <0.5 判未覆盖，>=0.5 判覆盖
    point_short = MetricsCalculator._extract_terms("ab cd ef gh")  # 4 个 2 字母词
    gen_low = MetricsCalculator._extract_terms("ab")              # 1/4 = 0.25
    gen_half = MetricsCalculator._extract_terms("ab cd")          # 2/4 = 0.50
    assert MetricsCalculator._point_covered(point_short, gen_low) is False
    assert MetricsCalculator._point_covered(point_short, gen_half) is True


# ------------------------------------------------------------
# 真实数据一致性回归（不变量，非达标证据）
# ------------------------------------------------------------
def test_real_lecture_terms_nonempty():
    """真实 benchmark 讲义应能被术语抽取处理，且产出非空术语集。"""
    if not REAL_DB.exists():
        pytest.skip("真实 benchmark 数据库缺失，跳过一致性回归")
    conn = sqlite3.connect(str(REAL_DB))
    row = conn.execute(
        "SELECT lecture FROM task_resources WHERE session_id LIKE 'bm_%' LIMIT 1"
    ).fetchone()
    conn.close()
    if not row or not row[0]:
        pytest.skip("无 bm_ 讲义数据，跳过")
    terms = MetricsCalculator._extract_terms(row[0])
    assert len(terms) > 0, "真实讲义术语抽取不应为空"


def test_real_benchmark_coverage_invariant():
    """真实 benchmark 的知识点覆盖率应落在已报告区间（约 0.85-0.88）。

    严格复刻 validate_metrics 口径：test_cases_100.json 的 reference_answer_points
    按归一化问题配对 db task_resources 的讲义/练习/测验全文，离线计算命中率。
    仅验证度量口径稳定、生成质量落在合理区间（非赛题达标证明）。
    """
    json_path = PROJECT_ROOT / "tests" / "test_cases_100.json"
    if not (REAL_DB.exists() and json_path.exists()):
        pytest.skip("缺 benchmark 数据库或 test_cases_100.json，跳过")
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
        tcs = data.get("test_cases", data) if isinstance(data, dict) else data
    except Exception:
        pytest.skip("test_cases_100.json 解析失败，跳过")
    ref_by_q = {}
    for tc in tcs:
        q = (tc.get("question") or "").strip().lower()
        if q:
            ref_by_q[q] = tc.get("reference_answer_points") or []

    conn = sqlite3.connect(str(REAL_DB))
    rows = conn.execute(
        "SELECT question, lecture, practice_guide, quiz, knowledge_refs "
        "FROM task_resources WHERE session_id LIKE 'bm_%'"
    ).fetchall()
    conn.close()

    total = 0
    covered = 0
    for q, lec, prac, quiz, krefs in rows:
        refs = ref_by_q.get((q or "").strip().lower())
        if not refs:
            continue
        res = {"lecture": lec, "practice_guide": prac, "quiz": quiz, "knowledge_refs": krefs}
        gen_text = MetricsCalculator._resource_text(res)
        gen_terms = MetricsCalculator._extract_terms(gen_text)
        for p in refs:
            pt = MetricsCalculator._extract_terms(p)
            if not pt:
                continue
            total += 1
            if MetricsCalculator._point_covered(pt, gen_terms):
                covered += 1

    if total == 0:
        pytest.skip("无配对样本，跳过")
    rate = covered / total
    # 与 docs/metrics_validation_report.md 报告值（87.3%）保持一致区间
    assert 0.80 <= rate <= 0.92, f"真实覆盖率 {rate:.3f} 偏离已报告区间"
