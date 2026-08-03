"""溯源判定阈值定标脚本 —— 论证"相似度能否判定事实正确性"

背景
----
系统最初把 verify_statement 的"已验证"阈值设为 0.72，期望"更严格"。
实测发现这会让 95% 的**正确**陈述也判不过，verification_rate 恒为 0，
指标彻底丧失区分力。本脚本用可复现的正负样本对照回答一个前置问题：

    向量相似度到底能不能区分"事实正确"与"事实错误"？

方法
----
正样本：tests/test_cases_100.json 中的 reference_answer_points（人工撰写的正确要点）
负样本：话题高度相关但事实明确错误的陈述（见 NEGATIVES，人工构造）
对每条陈述取知识库检索的最高相似度，比较两组分布，并扫描阈值计算区分度：

    区分度 = 正样本通过率 - 负样本通过率

若各阈值下区分度均 ≈ 0，则说明相似度只刻画"话题相关性"，
不具备事实核查能力，不能用作"核心知识点覆盖率"的口径。

用法
----
    # 必须用 PowerShell 运行（Git Bash 下加载 bge-m3 会 Segmentation fault）
    cd D:\\projects\\wolegedou
    .\\.venv\\Scripts\\python.exe -m backend.scripts.calibrate_verification
"""

import asyncio
import json
import statistics
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from loguru import logger

from backend.services.knowledge_base import get_knowledge_base
from backend.services.rag.kb_manager import init_knowledge_base

_TEST_PATH = _PROJECT_ROOT / "tests" / "test_cases_100.json"

# 负样本：话题相关但事实错误（考察阈值能否拒伪）
NEGATIVES = [
    "Token 是大模型输出图像的最小像素单位，与文本无关。",
    "Transformer 架构的核心是循环神经网络，不使用注意力机制。",
    "LoRA 微调需要更新模型的全部参数，显存占用比全量微调更高。",
    "RAG 检索增强生成不需要向量数据库，直接用正则表达式匹配即可。",
    "温度参数 temperature 设为 0 会让模型输出更随机多样。",
    "Embedding 向量的维度越低，语义表达能力一定越强。",
    "Prompt 工程中 Few-shot 指的是不给任何示例直接提问。",
    "BERT 是一个自回归生成模型，专门用于文本续写。",
    "梯度下降的学习率越大，模型一定收敛得越快越稳定。",
    "量化技术 INT8 会显著增加模型显存占用并降低推理速度。",
]

THRESHOLDS = (0.58, 0.60, 0.62, 0.64, 0.65, 0.66, 0.68, 0.70, 0.72, 0.75)


def load_positives(n: int = 40) -> list:
    data = json.loads(_TEST_PATH.read_text(encoding="utf-8"))
    out = []
    for tc in data.get("test_cases", []):
        for p in tc.get("reference_answer_points", []):
            out.append(p)
            if len(out) >= n:
                return out
    return out


async def _max_scores(kb, statements: list) -> list:
    vals = []
    for s in statements:
        results = await kb.search(s, top_k=5, score_threshold=0.0)
        if results:
            vals.append(max(r.score for r in results))
    return sorted(vals)


def _describe(name: str, xs: list) -> str:
    return "%s n=%-3d min=%.3f p25=%.3f median=%.3f p75=%.3f max=%.3f" % (
        name, len(xs), xs[0], xs[int(len(xs) * 0.25)],
        statistics.median(xs), xs[int(len(xs) * 0.75)], xs[-1],
    )


async def run(positive_n: int) -> int:
    init_knowledge_base()
    kb = get_knowledge_base()
    kb_name = type(kb).__name__
    print(f"知识库后端: {kb_name}")
    if kb_name == "StubKnowledgeBase":
        print("知识库为 Stub（检索恒空），无法定标。请检查 data/numpy_kb/ 与 bge-m3 模型。")
        return 2

    pos = await _max_scores(kb, load_positives(positive_n))
    neg = await _max_scores(kb, NEGATIVES)
    if not pos or not neg:
        print("样本不足，无法定标。")
        return 2

    print()
    print("=" * 78)
    print("  溯源阈值定标：正样本(已知正确) vs 负样本(事实错误) 相似度分布")
    print("=" * 78)
    print("  " + _describe("正样本", pos))
    print("  " + _describe("负样本", neg))
    print()
    print(f"  {'阈值':<8s}{'正样本通过率':>14s}{'负样本通过率':>14s}{'区分度':>12s}")
    print("  " + "-" * 60)

    best = None
    for th in THRESHOLDS:
        tp = sum(1 for x in pos if x >= th) / len(pos)
        fp = sum(1 for x in neg if x >= th) / len(neg)
        gap = tp - fp
        print(f"  {th:<8.2f}{tp * 100:>13.1f}%{fp * 100:>13.1f}%{gap:>+12.3f}")
        if best is None or gap > best[1]:
            best = (th, gap, tp, fp)

    print()
    print(f"  最佳区分阈值 = {best[0]:.2f}，区分度仅 {best[1]:+.3f}"
          f"（正样本通过 {best[2]:.1%}，负样本通过 {best[3]:.1%}）")
    print()
    if abs(best[1]) < 0.20:
        print("  结论：各阈值下区分度均接近 0 —— 向量相似度只能刻画『话题相关性』，")
        print("        不具备判定『事实正确性』的能力。因此：")
        print("        · verify_statement 的『已验证』只应表示『可溯源到知识库文档』；")
        print("        · 核心知识点覆盖率必须改用外部真值的事实比对口径")
        print("          （见 validate_metrics.py 的 factual_coverage_rate）。")
    else:
        print("  结论：存在具备区分力的阈值，可考虑用于事实核查。")
    print("=" * 78)
    return 0


def main() -> int:
    logger.remove()
    logger.add(sys.stderr, level="WARNING")
    n = 40
    for i, a in enumerate(sys.argv[1:]):
        if a == "--positives" and i + 2 <= len(sys.argv[1:]):
            try:
                n = int(sys.argv[i + 2])
            except (ValueError, IndexError):
                pass
    return asyncio.run(run(n))


if __name__ == "__main__":
    sys.exit(main())
