"""覆盖率缺口诊断（benchmark 跑完后用）

定位未覆盖的 reference_answer_points，并判断这些术语是否可从 KB 检索到：
  - 可在 KB 检索到  → 缺失是因检索/生成未把真实事实带出来，可安全靠「提升检索召回」补齐，不增幻觉；
  - KB 中检索不到    → 该参考要点不在知识库内，需另想办法（扩 KB 或审视参考点设定）。

复用 validate_metrics 的官方口径（术语抽取 + 覆盖判定 + factual_coverage_rate），
保证诊断数字与赛题指标一致。

用法：
  python -m backend.scripts.coverage_diagnose
"""
import asyncio
import json
import re
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from backend.scripts.validate_metrics import MetricsCalculator, _STOP_CHARS
from backend.services.knowledge_base import get_knowledge_base
from backend.services.rag.kb_manager import init_knowledge_base


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


async def main():
    calc = MetricsCalculator(bm_only=True, use_llm=False)
    pairs = calc._build_pairs()
    if not pairs:
        print("无配对数据，请先跑 benchmark_testcases 并确认 task_resources 有 bm_ 数据")
        return

    # 官方口径的总覆盖率（与赛题指标一致）
    official = calc.calc_factual_coverage_rate()
    print(f"配对用例数: {len(pairs)}")
    print(f"官方核心知识点覆盖率(factual_coverage_rate): "
          f"{official.get('value'):.1%}" if official.get("value") is not None
          else f"官方覆盖率: {official}")

    # 逐用例拆分缺失要点
    per_case = []
    all_missed = []  # (tc_id, domains, point_text)
    for tc, res in pairs:
        points = tc.get("reference_answer_points") or []
        if not points:
            continue
        gen = _resource_text(res)
        gen_terms = _extract_terms(gen)
        covered = 0
        missed = []
        for p in points:
            if _point_covered(_extract_terms(p), gen_terms):
                covered += 1
            else:
                missed.append(p)
        rate = covered / len(points)
        per_case.append({
            "id": tc.get("id"),
            "domain": tc.get("expected_domains"),
            "rate": rate,
            "covered": covered,
            "total": len(points),
            "missed": missed,
        })
        for m in missed:
            all_missed.append((tc.get("id"), tc.get("expected_domains"), m))

    # 用官方聚合再校验一次（应一致）
    overall = sum(c["rate"] for c in per_case) / len(per_case)
    print(f"逐用例聚合覆盖率: {overall:.1%}")
    print(f"总缺失要点数: {len(all_missed)}")

    # 最差用例
    worst = sorted(per_case, key=lambda x: x["rate"])[:15]
    print("\n=== 覆盖率最差 15 个用例 ===")
    for c in worst:
        print(f"  [{c['id']}] {c['rate']:.0%} ({c['covered']}/{c['total']}) domains={c['domain']}")
        for m in c["missed"][:2]:
            print(f"       缺: {m[:70]}")

    # KB 可检索性：用 verify_statement 判断是否真在 KB（抽样控耗时）
    init_knowledge_base()
    kb = get_knowledge_base()
    print(f"\n知识库后端: {type(kb).__name__}")
    retrievable = 0
    not_in_kb = 0
    checked = 0
    sample_limit = 150
    for tc_id, dom, m in all_missed:
        if checked >= sample_limit:
            break
        checked += 1
        try:
            vr = await kb.verify_statement(statement=m, top_k=3)
            if vr.get("status") == "已验证":
                retrievable += 1
            else:
                not_in_kb += 1
        except Exception:
            not_in_kb += 1
    print(f"\n缺失要点 KB 可检索性（抽样 {checked} 条）:")
    print(f"  可在KB检索到(可安全靠召回补齐): {retrievable}")
    print(f"  KB中检索不到(需另想办法): {not_in_kb}")


if __name__ == "__main__":
    asyncio.run(main())
