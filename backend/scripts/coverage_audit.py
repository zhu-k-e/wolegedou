"""覆盖率口径复核（纯本地，不调 LLM）：
导出 test_cases_100 与 bm_ 生成结果配对后的【未覆盖参考点】，
并区分「生成完全未提(真漏)」与「生成含核心词但未达标(口径差异候选)」。
目的：合法排查 _point_covered / _extract_terms 是否误杀合理覆盖，
不放宽匹配口径、不改覆盖率算法、不喂参考点。
"""
import sys
import re
from pathlib import Path

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))
from backend.scripts.validate_metrics import MetricsCalculator  # noqa: E402


def main():
    mc = MetricsCalculator(bm_only=True, use_llm=False)
    pairs = mc._build_pairs()
    if not pairs:
        print("无配对样本（bm_ 数据缺失）")
        return

    total = 0
    covered = 0
    true_missing = []   # 生成完全没提核心词 -> 真漏
    borderline = []     # 生成含核心词但没达标 -> 口径/部分覆盖候选
    all_uncovered = []

    for tc, res in pairs:
        points = tc.get("reference_answer_points") or []
        if not points:
            continue
        gen_text = mc._resource_text(res)
        gen_lower = gen_text.lower()
        gen_terms = mc._extract_terms(gen_text)
        q = (tc.get("question") or "")[:70]
        for p in points:
            pt = mc._extract_terms(p)
            total += 1
            if mc._point_covered(pt, gen_terms):
                covered += 1
                continue
            # 宽松候选：参考点里较长的连续段（>=2中文 / >=3英文）是否作为子串出现在生成
            core_segs = re.findall(r"[一-鿿]{2,}|[a-z0-9_]{3,}", p.lower())
            has_core = any(seg in gen_lower for seg in core_segs)
            rec = {
                "q": q,
                "point": p,
                "has_core": has_core,
                "gen_snippet": gen_text[:240].replace("\n", " "),
            }
            all_uncovered.append(rec)
            (borderline if has_core else true_missing).append(rec)

    rate = covered / total if total else 0.0
    lines = []
    lines.append("=" * 70)
    lines.append("覆盖率口径复核结果（纯本地，bm_only）")
    lines.append("=" * 70)
    lines.append(f"配对用例: {len(pairs)}")
    lines.append(f"总参考要点: {total}  覆盖: {covered}  未覆盖: {len(all_uncovered)}")
    lines.append(f"字面覆盖率: {rate*100:.1f}%  (赛题目标 >=90%)")
    lines.append(f"未覆盖中 | 真漏(生成完全未提核心词): {len(true_missing)}")
    lines.append(f"未覆盖中 | 口径/部分覆盖候选(含核心词未达标): {len(borderline)}")
    lines.append("")
    lines.append("-" * 70)
    lines.append("【真漏样本（前 25 条，生成确实没讲）】")
    lines.append("-" * 70)
    for r in true_missing[:25]:
        lines.append(f"[Q] {r['q']}")
        lines.append(f"  未覆盖点: {r['point']}")
        lines.append(f"  生成片段: {r['gen_snippet']}")
        lines.append("")
    lines.append("-" * 70)
    lines.append("【口径/部分覆盖候选（前 25 条，含核心词但未达标）】")
    lines.append("-" * 70)
    for r in borderline[:25]:
        lines.append(f"[Q] {r['q']}")
        lines.append(f"  未覆盖点: {r['point']}")
        lines.append(f"  生成片段: {r['gen_snippet']}")
        lines.append("")

    out = ROOT / "data" / "coverage_audit_result.txt"
    out.write_text("\n".join(lines), encoding="utf-8")
    # 同时打印摘要
    print("\n".join(lines[:9]))
    print(f"结果已写入: {out}")


if __name__ == "__main__":
    main()
