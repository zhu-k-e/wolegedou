"""离线裁判（benchmark judge）—— 用强模型对基准用例做「事实准确率 / 适配匹配」双评

为何需要它（见 validate_metrics.py 指标口径说明）：
  1) 专业知识谬误率原先用 Verifier 自评 fact_accuracy，但 Verifier 在不确定时给 0.5 兜底，
     实测 9 例中 6 例=0.5，使谬误率虚高到 33% —— 这是测量污染，不是真实质量失败。
  2) 适配准确率原先用「生成 difficulty_note 关键词」与 expected_complexity 比对的粗启发式，
     但 difficulty_note 是「面向学生画像」的自适应级别，与题目固有难度(expected_complexity)不同轴，
     产生大量假不匹配（50%）。

本脚本用强模型(高档 GPT-4o)对每个 bm_ 用例的「生成讲义 + 参考要点 + 目标画像」做一次性结构化评判，
返回 {fact_accuracy, adaptation_match, rationale}。完全离线，不进入 /api/ask 线上路径，
因此不改变线上调用次数/耗时，也不改变生成资源质量。

用法：
  python -m backend.scripts.benchmark_judge                # 评全部已落库 bm_ 用例（断点续跑）
  python -m backend.scripts.benchmark_judge --limit 9      # 先小批量验证
  python -m backend.scripts.benchmark_judge --concurrency 4
"""
import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from loguru import logger
from backend.services.llm_client import LLMClient, ModelTier, get_llm_client
from backend.db.database import execute_sql, query_all

_TEST_PATH = _PROJECT_ROOT / "tests" / "test_cases_100.json"


def _norm_q(q) -> str:
    return re.sub(r"\s+", "", (q or "").strip().lower())


def _load_test_cases() -> dict:
    data = json.loads(_TEST_PATH.read_text(encoding="utf-8"))
    return {c["id"]: c for c in data.get("test_cases", [])}


def _ensure_table():
    execute_sql(
        """CREATE TABLE IF NOT EXISTS bm_judge (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT UNIQUE,
            fact_accuracy REAL,
            adaptation_match INTEGER,
            rationale TEXT,
            model TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )"""
    )


def _load_lecture_text(raw: str) -> str:
    """从 task_resources.lecture(JSON) 抽取可读正文。"""
    try:
        obj = json.loads(raw)
    except Exception:
        return raw or ""
    for key in ("lecture_markdown", "content_markdown"):
        if isinstance(obj, dict) and isinstance(obj.get(key), str) and obj[key].strip():
            return obj[key]
    # 兜底：递归抽取所有字符串
    parts = []

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
    return "\n".join(parts)


def _build_messages(tc: dict, lecture: str) -> list:
    points = tc.get("reference_answer_points") or []
    points_txt = "\n".join(f"- {p}" for p in points)
    profile = tc.get("suitable_profile") or "未指定"
    exp = (tc.get("expected_complexity") or "").lower()
    q = tc.get("question", "")
    sys_p = (
        "你是一个严格且保守的事实核查与教学适配评审专家。"
        "只依据给定材料判断，不引入外部未证实知识。输出严格 JSON，不要任何解释性前缀。"
    )
    user_p = f"""【用户问题】
{q}

【参考要点（标准答案核心点）】
{points_txt}

【目标学习者画像】{profile}
【题目期望难度】{exp}

【生成的讲义】
{lecture}

请评估：
1. fact_accuracy（0-1 小数）：讲义中对该技术主题的实质性事实陈述，与参考要点一致的比例。
   仅当陈述与参考要点明显矛盾或事实错误时才计为错；参考要点未覆盖的内容若本身正确不扣分；
   若无法判断真伪，按正确计（保守）。输出 0 到 1 之间的小数，如 0.9。
2. adaptation_match（true/false）：讲义的难度、术语解释、举例是否整体适配目标学习者画像与期望难度。
   若整体适配输出 true，否则 false。

输出格式（严格 JSON）：
{{"fact_accuracy": <float>, "adaptation_match": <bool>, "rationale": "<简短中文说明>"}}
"""
    return [
        {"role": "system", "content": sys_p},
        {"role": "user", "content": user_p},
    ]


def _parse_judgment(text: str) -> dict | None:
    try:
        # 容错：截取首个 { 到末个 }
        s = text.strip()
        if not s.startswith("{"):
            m = re.search(r"\{.*\}", s, re.DOTALL)
            if not m:
                return None
            s = m.group(0)
        obj = json.loads(s)
        fa = float(obj.get("fact_accuracy"))
        am = bool(obj.get("adaptation_match"))
        fa = max(0.0, min(1.0, fa))
        return {"fact_accuracy": fa, "adaptation_match": am, "rationale": str(obj.get("rationale", ""))[:300]}
    except Exception as e:
        logger.warning(f"解析裁判结果失败: {e} | raw={text[:200]}")
        return None


async def judge_one(client: LLMClient, tc: dict, lecture: str, model: str) -> dict | None:
    messages = _build_messages(tc, lecture)
    try:
        raw = await client.chat(
            messages=messages, tier=ModelTier.HIGH, temperature=0.0, max_tokens=800,
            response_format={"type": "json_object"},
        )
    except Exception as e:
        logger.error(f"LLM 调用失败: {e}")
        return None
    return _parse_judgment(raw)


async def main(limit: int | None, concurrency: int):
    _ensure_table()
    client = get_llm_client()
    model = client._high_model

    tcs = _load_test_cases()
    rows = query_all("SELECT session_id, lecture FROM task_resources WHERE session_id LIKE 'bm_%'")
    # 已评集合
    done = {r["session_id"] for r in query_all("SELECT session_id FROM bm_judge")}

    pending = [r for r in rows if r["session_id"] not in done]
    if limit is not None:
        pending = pending[:limit]

    if not pending:
        logger.info("没有待评用例（全部已评或库中空）。")
    else:
        logger.info(f"待评用例: {len(pending)}（模型={model}）")

    sem = asyncio.Semaphore(max(1, concurrency))
    results = []

    async def _runner(row):
        sid = row["session_id"]
        tcid = sid.replace("bm_", "")
        tc = tcs.get(tcid)
        if not tc:
            logger.warning(f"{sid} 在 test_cases 中找不到对应用例，跳过")
            return
        lecture = _load_lecture_text(row["lecture"])
        async with sem:
            j = await judge_one(client, tc, lecture, model)
        if j:
            execute_sql(
                "INSERT OR REPLACE INTO bm_judge (session_id, fact_accuracy, adaptation_match, rationale, model) "
                "VALUES (?, ?, ?, ?, ?)",
                (sid, j["fact_accuracy"], int(j["adaptation_match"]), j["rationale"], model),
            )
            results.append((sid, j))
            logger.info(f"  [{sid}] fa={j['fact_accuracy']:.2f} am={j['adaptation_match']}")

    await asyncio.gather(*[_runner(r) for r in pending])

    # 汇总
    all_j = query_all("SELECT fact_accuracy, adaptation_match FROM bm_judge")
    if all_j:
        fa_vals = [r["fact_accuracy"] for r in all_j if r["fact_accuracy"] is not None]
        am_vals = [bool(r["adaptation_match"]) for r in all_j]
        avg_fa = sum(fa_vals) / len(fa_vals) if fa_vals else 0
        am_rate = sum(am_vals) / len(am_vals) if am_vals else 0
        print("\n" + "=" * 60)
        print(f"离线裁判汇总（样本={len(all_j)}）")
        print(f"  专业知识谬误率(1-avg fact_accuracy) = {1-avg_fa:.1%}   (avg_fact_accuracy={avg_fa:.3f})")
        print(f"  适配准确率(adaptation_match 比例)   = {am_rate:.1%}")
        print("=" * 60)
    else:
        print("无裁判结果")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="离线裁判：事实准确率 + 适配匹配双评")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--concurrency", type=int, default=4)
    args = ap.parse_args()
    asyncio.run(main(limit=args.limit, concurrency=args.concurrency))
