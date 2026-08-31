"""赛题硬指标的 LLM 复核 judge（外部真值口径）

用于替换 validate_metrics.py 中两个有测量污染的代理指标：
- 适配准确率：关键词启发式 → LLM 判定生成讲义难度与 expected_complexity 是否匹配
- 专业知识谬误率：Verifier 自评 0.5 兜底 → LLM 判定生成讲义相对 reference_answer_points 是否存在事实错误

设计原则：
1. 每道题只调用一次 LLM，同时输出两项判断，降低 API 成本。
2. 使用低档/中档模型（默认 MID / deepseek-v4-flash），temperature=0，输出 JSON。
3. 结果缓存到 data/metrics_llm_judge_cache.json，避免重复调用。
4. 失败时保守回退（不计入成功样本），防止把 API 异常当成"无错误"而虚低谬误率。
"""

import asyncio
import hashlib
import json
import os
from pathlib import Path
from typing import Optional

from loguru import logger

from backend.services.llm_client import LLMClient, ModelTier

_CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "metrics_llm_judge_cache.json"

_JUDGE_PROMPT = """你是一名严格且审慎的 AI 教学评测员。请根据以下信息做三项独立判断，并以 JSON 输出。

【题目】
{question}

【期望难度】
{expected_complexity}（simple=简单/入门，medium=中等，complex=复杂/进阶）

【参考要点（视为事实正确）】
{reference_points}

【生成讲义】
{lecture_text}

【生成练习指导】
{practice_text}

【生成测验】
{quiz_text}

请输出 JSON：
{{
  "adaptation_matched": true/false,
  "adaptation_reason": "生成内容难度与期望难度是否匹配，一句话说明",
  "factual_error": true/false,
  "factual_confidence": 0.0-1.0,
  "factual_reason": "生成内容是否包含与参考要点直接矛盾的事实错误，一句话说明",
  "hallucination": true/false,
  "hallucination_confidence": 0.0-1.0,
  "hallucination_reason": "生成内容是否包含无可靠依据或明显错误的具体事实断言，一句话说明（注明具体断言）"
}}

判断规则（务必严格，禁止宽松纵容）：
- adaptation_matched 仅判断难度匹配，不考虑事实。
- factual_error：若生成内容存在与【参考要点】直接矛盾的事实陈述则为 true；否则 false。仅在确有矛盾时判 true，不确定给 false。
- hallucination：若生成内容包含下列任一情形则为 true：
  (a) 参考要点未出现、且明显编造或无可靠依据的具体断言（虚构数据/统计数字/API/论文/人物/命令/代码片段/库版本号等）；
  (b) 与公认事实明显矛盾、即“似真但错误”的具体事实断言（例如错误的公式、错误的时间复杂度、错误的技术结论），即使它未被参考要点覆盖；
  (c) 把不存在的能力/特性/限制强加给某个技术或工具。
  反之，对参考要点的同义转述、常识性正确内容、比喻与教学性展开不算幻觉。
  注意：hallucination 与 factual_error 互补——factual_error 只看与参考要点矛盾，hallucination 还覆盖编造与“似真但错误”，两者可同时为 true。
- 判定须基于文本中的具体可证伪断言；禁止“不确定就给 false”式的纵容——若能在生成内容中找到明确可证伪的错误/编造断言，就应判 true。但也不要无中生有：纯主观表述、建议性内容、未断言事实的评价不算幻觉。"""


def _cache_key(question: str, expected_complexity: str, lecture_text: str, reference_points: list[str], practice_text: str = "", quiz_text: str = "") -> str:
    payload = {
        # 硬化版盐：HIGH 档 judge + 全文(讲义+练习+测验) + 放宽口径(似真但错误) → 旧缓存全部失效重判
        "v": "v3-hallucination-hardened",
        "q": question,
        "exp": expected_complexity,
        "lecture": lecture_text,
        "practice": practice_text,
        "quiz": quiz_text,
        "refs": reference_points,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _load_cache(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"加载 LLM judge 缓存失败: {e}")
    return {}


def _save_cache(path: Path, cache: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # 原子写：先写临时文件再 rename，避免并发（多 agent 共享缓存文件）写交错导致 JSON 损坏
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _format_reference_points(points: list[str]) -> str:
    return "\n".join(f"- {p}" for p in points) if points else "（无显式参考要点）"


def _normalize_judge_result(raw: dict) -> dict:
    """把 LLM 输出归一化为固定字段，缺失字段给安全默认值。"""
    return {
        "adaptation_matched": bool(raw.get("adaptation_matched", False)),
        "adaptation_reason": str(raw.get("adaptation_reason", "")),
        "factual_error": bool(raw.get("factual_error", False)),
        "factual_confidence": max(0.0, min(1.0, float(raw.get("factual_confidence", 0.5)))),
        "factual_reason": str(raw.get("factual_reason", "")),
        "hallucination": bool(raw.get("hallucination", False)),
        "hallucination_confidence": max(0.0, min(1.0, float(raw.get("hallucination_confidence", 0.5)))),
        "hallucination_reason": str(raw.get("hallucination_reason", "")),
    }


class MetricsLLMJudge:
    """赛题硬指标 LLM 复核 judge"""

    def __init__(
        self,
        cache_path: Optional[Path] = None,
        concurrency: int = 5,
        tier: ModelTier = ModelTier.HIGH,
        max_section_chars: int = 6000,
    ):
        self.client = LLMClient()
        self.cache_path = cache_path or _CACHE_PATH
        self.concurrency = concurrency
        self.tier = tier
        self.max_section_chars = max_section_chars
        self._cache = _load_cache(self.cache_path)
        self._lock = asyncio.Lock()

    def _build_prompt(self, question: str, expected_complexity: str, lecture_text: str, reference_points: list[str], practice_text: str = "", quiz_text: str = "") -> str:
        cap = self.max_section_chars
        lecture_text = (lecture_text or "")[:cap]
        practice_text = (practice_text or "")[:cap]
        quiz_text = (quiz_text or "")[:cap]
        return _JUDGE_PROMPT.format(
            question=question,
            expected_complexity=expected_complexity,
            reference_points=_format_reference_points(reference_points),
            lecture_text=lecture_text,
            practice_text=practice_text,
            quiz_text=quiz_text,
        )

    async def _judge_one(self, item: dict) -> dict:
        """item 字段: question, expected_complexity, lecture_text, practice_text, quiz_text, reference_points

        加锁保护缓存读写与落盘：多个并发调用方（如判官驱动修复闸门对同一 judge
        实例并发 _judge_one）共享 self._cache / 缓存文件，锁仅在缓存查/写段加锁，
        LLM 调用（慢）在锁外执行，避免串行化推理的同时保证缓存一致性。
        """
        question = item.get("question", "")
        exp = (item.get("expected_complexity") or "").lower()
        lecture_text = item.get("lecture_text", "")
        practice_text = item.get("practice_text", "")
        quiz_text = item.get("quiz_text", "")
        refs = item.get("reference_points") or []

        key = _cache_key(question, exp, lecture_text, refs, practice_text, quiz_text)
        async with self._lock:
            if key in self._cache:
                cached = dict(self._cache[key])
                cached["_cached"] = True
                return cached

        prompt = self._build_prompt(question, exp, lecture_text, refs, practice_text, quiz_text)
        try:
            text = await self.client.chat(
                messages=[{"role": "user", "content": prompt}],
                tier=self.tier,
                temperature=0.0,
                max_tokens=1024,
                response_format={"type": "json_object"},
                max_retries=2,
            )
            parsed = json.loads(text or "{}")
            result = _normalize_judge_result(parsed)
            result["_cached"] = False
        except Exception as e:
            logger.warning(f"LLM judge 失败 [{question[:30]}...]: {e}")
            # 失败时返回哨兵，调用方应排除该样本，不能当成"无错误"
            result = {
                "adaptation_matched": False,
                "adaptation_reason": f"judge failed: {e}",
                "factual_error": False,
                "factual_confidence": 0.0,
                "factual_reason": "judge failed",
                "hallucination": False,
                "hallucination_confidence": 0.0,
                "hallucination_reason": "judge failed",
                "_failed": True,
            }

        async with self._lock:
            self._cache[key] = result
            _save_cache(self.cache_path, self._cache)
        return result

    async def judge_batch(self, items: list[dict]) -> list[dict]:
        """批量复核 items，返回与输入顺序一致的 list[dict]。"""
        if not items:
            return []

        sem = asyncio.Semaphore(self.concurrency)

        async def _wrapped(item: dict) -> dict:
            async with sem:
                return await self._judge_one(item)

        results = await asyncio.gather(*[_wrapped(it) for it in items], return_exceptions=True)
        out = []
        for r in results:
            if isinstance(r, Exception):
                logger.warning(f"LLM judge batch 项异常: {r}")
                out.append({
                    "adaptation_matched": False,
                    "adaptation_reason": f"batch exception: {r}",
                    "factual_error": False,
                    "factual_confidence": 0.0,
                    "factual_reason": "batch exception",
                    "_failed": True,
                })
            else:
                out.append(r)
        return out
