"""覆盖率「语义匹配」诊断（只读现有 task_resources，不改变官方口径）

目的：量化官方字面匹配（2/3-gram）低估了多少「同义改写」造成的假阴性。
  - 官方 factual_coverage_rate 仍由 validate_metrics.py 的字面匹配计算（本脚本不改它）。
  - 本脚本在**同一份生成文本**上，对「字面未覆盖」的参考要点额外做 bge-m3 语义相似度匹配，
    看有多少点其实是「讲到了但换了说法」（语义可救），多少是「真没讲」（必须改生成器）。

用法：
  python -m backend.scripts.coverage_semantic_diagnose
"""
import re
import sys
from pathlib import Path

import numpy as np

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from backend.scripts.validate_metrics import MetricsCalculator
from backend.services.rag.embedding_service import EmbeddingService

# 保守阈值：bge-m3 稠密余弦，越高越严。多阈值同报，避免「单点挑阈值」嫌疑。
THRESHOLDS = [0.60, 0.68, 0.75]
_RESULT_PATH = _PROJECT_ROOT / "data" / "coverage_semantic_result.txt"

_EMB = EmbeddingService()


def _chunk(text: str, size: int = 200):
    """按句切分并聚合成 ~size 字符的块，供语义比对。"""
    sents = re.split(r"[。！？\n]", text or "")
    chunks, cur = [], ""
    for s in sents:
        s = s.strip()
        if not s:
            continue
        if cur and len(cur) + len(s) > size:
            chunks.append(cur)
            cur = s
        else:
            cur = (cur + "，" + s) if cur else s
    if cur:
        chunks.append(cur)
    return chunks


def _cos_max(point_vec: np.ndarray, chunk_vecs: np.ndarray) -> float:
    """点向量与若干块向量的最大余弦相似度。"""
    if chunk_vecs.size == 0:
        return -1.0
    pv = point_vec / np.linalg.norm(point_vec)
    cv = chunk_vecs / np.linalg.norm(chunk_vecs, axis=1, keepdims=True)
    return float(np.max(cv @ pv))


def _write_result(total_points, literal_covered, recovered, recovered_examples, idx, n_pairs, partial=False):
    literal_rate = literal_covered / total_points if total_points else 0.0
    lines = []
    if partial:
        lines.append(f"[部分进度 {idx}/{n_pairs}] 仍在跑，以下为当前累计（非最终）")
    lines.append(f"配对用例: {n_pairs}")
    lines.append(f"总参考要点: {total_points}")
    lines.append(f"字面匹配覆盖率(literal): {literal_rate:.1%}  ({literal_covered}/{total_points})")
    lines.append("")
    lines.append(f"{'阈值':>6s} | {'语义覆盖率':>10s} | {'救回要点数':>10s} | {'改写占比(估)':>12s}")
    lines.append("-" * 50)
    for t in THRESHOLDS:
        sem_rate = (literal_covered + recovered[t]) / total_points if total_points else 0.0
        lines.append(f"{t:>6.2f} | {sem_rate:>9.1%} | {recovered[t]:>10d} | "
                     f"{(sem_rate - literal_rate):>11.1%}")
    lines.append("")
    lines.append("说明：『改写占比(估)』= 语义覆盖率 - 字面覆盖率，即「字面漏掉、但语义上其实讲到了」"
                 "的要点比例上限。该部分可由语义匹配器合法修回；其余仍为『真漏』，必须改生成器。")
    if not partial:
        lines.append("")
        lines.append("=== 阈值 0.68 下被语义救回的要点样本（人工核验是否真为同义改写）===")
        for tid, sim, p in recovered_examples[0.68]:
            lines.append(f"  [{tid}] sim={sim}  {p}")
    _RESULT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main():
    calc = MetricsCalculator(bm_only=True, use_llm=False)
    pairs = calc._build_pairs()
    if not pairs:
        print("无配对数据，请先跑 benchmark_testcases。")
        return

    total_points = 0
    literal_covered = 0
    recovered = {t: 0 for t in THRESHOLDS}
    recovered_examples = {t: [] for t in THRESHOLDS}

    for idx, (tc, res) in enumerate(pairs, 1):
        points = tc.get("reference_answer_points") or []
        if not points:
            continue
        gen_text = calc._resource_text(res)
        gen_terms = calc._extract_terms(gen_text)

        missed = []
        for p in points:
            total_points += 1
            if calc._point_covered(calc._extract_terms(p), gen_terms):
                literal_covered += 1
            else:
                missed.append(p)

        if not missed:
            continue  # 全字面覆盖，无需编码，省时

        chunks = _chunk(gen_text)
        texts = chunks + missed
        vecs = np.array(_EMB.encode(texts), dtype=np.float32)
        chunk_vecs = vecs[: len(chunks)]
        missed_vecs = vecs[len(chunks):]

        for i, p in enumerate(missed):
            sim = _cos_max(missed_vecs[i], chunk_vecs)
            for t in THRESHOLDS:
                if sim >= t:
                    recovered[t] += 1
                    if len(recovered_examples[t]) < 40:
                        recovered_examples[t].append((tc.get("id"), round(sim, 3), p[:80]))

        # 每用例实时落盘当前累计，避免进程被回收时结果全丢
        _write_result(total_points, literal_covered, recovered, recovered_examples, idx, len(pairs), partial=True)
        print(f"  [{idx}/{len(pairs)}] 已处理，累计漏点 {total_points - literal_covered}", flush=True)

    literal_rate = literal_covered / total_points if total_points else 0.0

    lines = []
    lines.append(f"配对用例: {len(pairs)}")
    lines.append(f"总参考要点: {total_points}")
    lines.append(f"字面匹配覆盖率(literal): {literal_rate:.1%}  ({literal_covered}/{total_points})")
    lines.append("")
    lines.append(f"{'阈值':>6s} | {'语义覆盖率':>10s} | {'救回要点数':>10s} | {'改写占比(估)':>12s}")
    lines.append("-" * 50)
    for t in THRESHOLDS:
        sem_rate = (literal_covered + recovered[t]) / total_points
        lines.append(f"{t:>6.2f} | {sem_rate:>9.1%} | {recovered[t]:>10d} | "
                     f"{(sem_rate - literal_rate):>11.1%}")
    lines.append("")
    lines.append("说明：『改写占比(估)』= 语义覆盖率 - 字面覆盖率，即「字面漏掉、但语义上其实讲到了」"
                 "的要点比例上限。该部分可由语义匹配器合法修回；其余仍为『真漏』，必须改生成器。")
    lines.append("")
    lines.append("=== 阈值 0.68 下被语义救回的要点样本（人工核验是否真为同义改写）===")
    for tid, sim, p in recovered_examples[0.68]:
        lines.append(f"  [{tid}] sim={sim}  {p}")

    out = "\n".join(lines)
    print(out, flush=True)
    # 单独写干净文件，避免被 tqdm 进度条的 \r 刷屏淹没 / 进程被回收时丢失
    _write_result(total_points, literal_covered, recovered, recovered_examples,
                  len(pairs), len(pairs), partial=False)
    print(f"\n[结果已写入 {_RESULT_PATH}]", flush=True)


if __name__ == "__main__":
    main()
