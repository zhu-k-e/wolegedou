"""量化指标验证脚本（方案书第七部分）

对齐赛题 4 项量化指标，从数据库自动统计 + 知识库召回率测试：
  1. 专业知识谬误率 < 5%  — LLM 复核（参考要点 vs 生成讲义）
  2. 适配准确率 >= 85%    — LLM 复核（expected_complexity vs 生成讲义难度）
  3. 核心知识点覆盖率 >= 90% — 生成文本对 test_cases_100 reference_answer_points 命中率
  4. 幻觉率（附加）       — 裁判团 verdict 分布

事实比对指标（需先运行 benchmark_testcases 生成资源）：
  - 核心知识点覆盖率(事实) >= 90% — 关键词命中率
  - 适配准确率(事实) >= 85% — LLM 复核
  - 专业知识谬误率 < 5%   — LLM 复核

用法:
  python -m backend.scripts.validate_metrics              # 全量验证（默认启用 LLM 复核）
  python -m backend.scripts.validate_metrics --no-kb       # 跳过知识库测试（无需加载 bge-m3）
  python -m backend.scripts.validate_metrics --no-llm      # 禁用 LLM 复核（回退到旧口径）
  python -m backend.scripts.validate_metrics --kb-only     # 仅知识库召回率测试
  python -m backend.scripts.benchmark_testcases           # 跑 100 基准用例生成资源(供事实指标)
"""

import asyncio
import sys
import os
import re
import json
from datetime import datetime
from pathlib import Path

# 确保项目根在 sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from backend.db.database import query_all, query_one
from backend.scripts.metrics_llm_judge import MetricsLLMJudge
from loguru import logger

# ============================================================
# 指标目标值（方案书 7.1 节）
# ============================================================

# 对齐赛题「实用价值」评分硬指标（方案书第六部分）：
#   专业知识谬误率 < 5% / 适配准确率 >= 85% / 核心知识点覆盖率 >= 90% / 幻觉率 < 5%
# 【指标口径说明】
# 赛题 4 项硬指标一律以「事实比对口径」为准（对照 tests/test_cases_100.json 外部真值），
# 而非系统自评。系统自评分（Verifier/Evaluator/裁判团打分）仅作为过程观测指标列出，
# 不参与达标判定 —— 自己给自己打分不能作为达标证据。
#
# 特别说明「知识溯源率」为何被降级为观测指标：
#   实测定标（40 条已知正确陈述 vs 10 条事实错误陈述）显示，二者在知识库中的
#   最高相似度分布几乎完全重合（median 0.640 vs 0.641），各阈值下区分度均 ≈ 0。
#   即向量相似度只能刻画"话题相关性"，无法判定"事实正确性"。
#   故溯源率只表示"有知识库文档支撑（可溯源）"，不能充当核心知识点覆盖率。
TARGETS = {
    # —— 赛题硬指标（事实比对口径，外部真值，离线无 LLM）——
    "factual_coverage_rate":   {"target": 0.90, "compare": ">=", "label": "核心知识点覆盖率", "unit": "%", "official": True},
    "factual_adaptation_rate": {"target": 0.85, "compare": ">=", "label": "适配准确率",     "unit": "%", "official": True},
    "hallucination_rate": {"target": 0.05, "compare": "<=", "label": "幻觉率", "unit": "%", "official": True},
    "error_rate":      {"target": 0.05, "compare": "<=", "label": "专业知识谬误率", "unit": "%", "official": True},
    # —— 过程观测指标（系统自评，不作达标证据）——
    "adaptation_rate": {"target": 0.85, "compare": ">=", "label": "教学适配度(自评)", "unit": "%", "official": False},
    "coverage_rate":   {"target": 0.90, "compare": ">=", "label": "知识溯源率(自评)", "unit": "%", "official": False},
    "force_pass_rate": {"target": 0.05, "compare": "<=", "label": "强制放行率(自评)", "unit": "%", "official": False},
}

# 报告展示顺序：赛题硬指标在前，过程观测指标在后
OFFICIAL_KEYS = ["factual_coverage_rate", "factual_adaptation_rate", "hallucination_rate", "error_rate"]
OBSERVED_KEYS = ["adaptation_rate", "coverage_rate", "force_pass_rate"]
REPORT_KEYS = OFFICIAL_KEYS + OBSERVED_KEYS

# 100 条测试用例真值（事实比对基准）
TEST_CASES_PATH = _PROJECT_ROOT / "tests" / "test_cases_100.json"

# 中文停用字符（用于抽取参考要点关键词时降噪）
_STOP_CHARS = set("的是在与和及对等为有也一个这种那他她它我们你它们被把从到以可可以能会于等及或并且但是因为所以如果当在对于关于通过使用需要应该必须通常一般常见基本主要核心关键其之此该各")

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

    def __init__(self, bm_only: bool = False, use_llm: bool = True):
        self.bm_only = bm_only
        self.use_llm = use_llm
        self._llm_judge_results: dict[str, dict] = {}
        all_tm = query_all("SELECT * FROM task_metrics")
        # 转 dict 以支持 .get 访问（query_all 返回 Row 对象）
        all_tm = [dict(r) for r in all_tm]
        # bm_only: 仅统计基准评测用例(bm_*)的落库行，排除用户 demo/真实流量数据，
        # 使赛题指标口径严格对应 test_cases_100.json 评测集，避免样本污染。
        self.task_metrics = (
            [r for r in all_tm if (r.get("session_id") or "").startswith("bm_")]
            if bm_only else all_tm
        )
        self.contribution_memory = query_all("SELECT * FROM contribution_memory")
        self.student_feedback = query_all("SELECT * FROM student_feedback")
        # 事实比对基准
        self.test_cases = self._load_test_cases()
        self.task_resources = self._load_task_resources()

    # --- 事实比对基准加载 ---
    def _load_test_cases(self) -> list:
        try:
            data = json.loads(TEST_CASES_PATH.read_text(encoding="utf-8"))
            return data.get("test_cases", [])
        except Exception as e:
            logger.warning(f"加载 test_cases_100.json 失败(事实指标将无样本): {e}")
            return []

    def _load_task_resources(self) -> list:
        try:
            from backend.db.resource_store import ensure_task_resources_table
            ensure_task_resources_table()
            rows = query_all(
                "SELECT task_id, session_id, question, lecture, practice_guide, quiz, knowledge_refs "
                "FROM task_resources"
            )
            return [dict(r) for r in rows]
        except Exception as e:
            logger.warning(f"加载 task_resources 失败(表可能未初始化): {e}")
            return []

    @staticmethod
    def _norm_q(q) -> str:
        return re.sub(r"\s+", "", (q or "").strip().lower())

    @property
    def has_data(self) -> bool:
        return len(self.task_metrics) > 0 or len(self.contribution_memory) > 0

    # --- LLM 复核入口（替代有污染的自评/启发式口径） ---
    def _build_judge_items(self) -> list[dict]:
        """为可配对用例构造 LLM judge 输入（硬化版：讲义+练习+测验全文）。"""
        items = []
        for tc, res in self._build_pairs():
            q = tc.get("question", "")
            exp = tc.get("expected_complexity")
            refs = tc.get("reference_answer_points") or []
            if not exp or not refs:
                continue
            lecture = self._col_text(res, "lecture")
            practice = self._col_text(res, "practice_guide")
            quiz = self._col_text(res, "quiz")
            # 至少一个内容非空才送审
            if not (lecture or practice or quiz):
                continue
            items.append({
                "question": q,
                "expected_complexity": exp,
                "reference_points": refs,
                "lecture_text": lecture,
                "practice_text": practice,
                "quiz_text": quiz,
                "norm_q": self._norm_q(q),
            })
        return items

    @staticmethod
    def _lecture_text_for_judge(res: dict) -> str:
        """从 task_resources 提取供 judge 使用的讲义文本。"""
        raw = res.get("lecture")
        if not raw:
            return ""
        try:
            obj = json.loads(raw)
            if not isinstance(obj, dict):
                return str(raw)
            parts = []
            for k in ("title", "difficulty_note", "content_markdown"):
                v = obj.get(k)
                if isinstance(v, str) and v.strip():
                    parts.append(v.strip())
            return "\n\n".join(parts)
        except Exception:
            return str(raw)

    @staticmethod
    def _col_text(res: dict, col: str) -> str:
        """从 task_resources 某列(JSON)递归抽取全部文本（硬化版用于练习/测验全文复核）。"""
        raw = res.get(col)
        if not raw:
            return ""
        try:
            obj = json.loads(raw)
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
            return "\n\n".join(p.strip() for p in parts if isinstance(p, str) and p.strip())
        except Exception:
            return str(raw)

    async def _async_ensure_llm_judge_results(self) -> dict[str, dict]:
        """异步批量调用 LLM judge，结果按归一化问题索引。"""
        if self._llm_judge_results:
            return self._llm_judge_results
        items = self._build_judge_items()
        if not items:
            logger.warning("无可用 LLM judge 样本（缺少 expected_complexity/reference_answer_points/lecture）")
            self._llm_judge_results = {}
            return self._llm_judge_results

        logger.info(f"开始 LLM 复核 {len(items)} 条用例（适配准确率 + 专业知识谬误率）...")
        judge = MetricsLLMJudge()
        results = await judge.judge_batch(items)
        self._llm_judge_results = {
            item["norm_q"]: result
            for item, result in zip(items, results)
            if not result.get("_failed")
        }
        failed = sum(1 for r in results if r.get("_failed"))
        if failed:
            logger.warning(f"LLM judge 失败 {failed}/{len(items)} 条，已排除")
        logger.info(f"LLM 复核完成，有效样本 {len(self._llm_judge_results)}/{len(items)}")
        return self._llm_judge_results

    def ensure_llm_judge_results(self) -> dict[str, dict]:
        """同步包装：确保 LLM judge 结果已加载。"""
        if not self.use_llm:
            return {}
        if self._llm_judge_results:
            return self._llm_judge_results
        try:
            return asyncio.run(self._async_ensure_llm_judge_results())
        except Exception as e:
            logger.warning(f"LLM judge 初始化失败，回退到旧口径: {e}")
            return {}

    # --- 指标1: 专业知识谬误率 ---
    def calc_error_rate(self) -> dict:
        """专业知识谬误率 = 生成内容相对参考要点存在事实错误的样本比例。

        优先使用 LLM 复核（外部真值口径）；LLM 不可用时回退到 Verifier 自评。
        """
        # 优先用 LLM 复核
        judge_results = self.ensure_llm_judge_results()
        if judge_results:
            error_scores = []
            for r in judge_results.values():
                # 有错误 = 置信度加权错误分；无错误 = 0
                if r.get("factual_error"):
                    error_scores.append(r.get("factual_confidence", 1.0))
                else:
                    error_scores.append(0.0)
            if error_scores:
                value = sum(error_scores) / len(error_scores)
                return {
                    "value": value,
                    "sample_count": len(error_scores),
                    "source": "LLM 复核 (reference_answer_points vs 生成讲义)",
                    "detail": f"errors={sum(1 for s in error_scores if s > 0)}, avg_confidence={value:.3f}",
                }

        # 回退：Verifier 自评（存在 0.5 兜底污染，仅作 fallback）
        fact_scores = [
            r["fact_accuracy"] for r in self.task_metrics
            if r["fact_accuracy"] is not None
        ]
        source = "task_metrics.fact_accuracy (Verifier 自评，fallback)"

        if not fact_scores:
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

    # --- 指标4: 幻觉率（真实测量）---
    def calc_hallucination_rate(self) -> dict:
        """幻觉率 = 生成讲义含「无根据编造」的样本比例。

        真测量：复用 MetricsLLMJudge 的 hallucination 字段 ——
        LLM 检测生成内容是否包含参考要点中未出现、且明显编造/无可靠依据的具体断言
        （虚构数据/API/论文/人物/命令/代码）。与 error_rate（事实错误）互补、口径不同。

        无 LLM 时回退到「裁判不通过/强制放行占比」（真实但口径不同，已在 source 标注）。
        """
        # 优先用 LLM 复核（外部真值口径）
        judge_results = self.ensure_llm_judge_results()
        if judge_results:
            flags = [r for r in judge_results.values() if not r.get("_failed")]
            if flags:
                n = sum(1 for r in flags if r.get("hallucination"))
                return {
                    "value": n / len(flags),
                    "sample_count": len(flags),
                    "source": "LLM 复核 (HIGH档, 全文+练习+测验, 检测无根据编造/似真但错误)",
                    "detail": f"hallucinated={n}/{len(flags)}",
                }

        # 回退：裁判不通过/强制放行占比（real，但非字面幻觉率）
        if self.task_metrics:
            total = len(self.task_metrics)
            n = sum(1 for r in self.task_metrics if r.get("override_reason") is not None)
            return {
                "value": n / total if total > 0 else None,
                "sample_count": total,
                "source": "task_metrics.override_reason (无LLM回退：裁判不通过/强放占比，非字面幻觉率)",
                "detail": f"force_passed={n}/{total}",
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

    # ============================================================
    # 事实比对指标（test_cases_100.json 真值，离线，无 LLM 调用）
    #   覆盖率 = 生成文本对 reference_answer_points 关键术语的命中率
    #   适配率 = 生成资源难度说明 vs expected_complexity（启发式，待 LLM 复核）
    # ============================================================

    # --- 术语抽取（中文 2/3 元文法 + 英文词，去停用字符） ---
    @staticmethod
    def _extract_terms(text) -> set:
        if not text:
            return set()
        text = str(text).lower()
        terms = set()
        # 英文/数字词（长度 >=2）
        for m in re.findall(r"[a-z0-9_]{2,}", text):
            terms.add(m)
        # 中文连续段 -> 2-gram / 3-gram（去掉停用字符降噪）
        for run in re.findall(r"[\u4e00-\u9fff]+", text):
            run = "".join(ch for ch in run if ch not in _STOP_CHARS)
            n = len(run)
            if n >= 2:
                for k in (2, 3):
                    for i in range(n - k + 1):
                        terms.add(run[i:i + k])
        return terms

    @staticmethod
    def _resource_text(res: dict) -> str:
        """把 task_resources 一行拼接成可检索的纯文本。

        lecture/practice_guide/quiz/knowledge_refs 列存的是 JSON（model_dump），
        递归抽取所有字符串字段（content_markdown / explanation 等），避免被 JSON
        结构字符干扰命中判定。
        """
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

    @staticmethod
    def _lecture_difficulty_note(res: dict) -> str | None:
        """仅取讲义的 difficulty_note 作为难度信号（正文会有'深入/复杂/高级'等词，不能扫全文）"""
        raw = res.get("lecture")
        if not raw:
            return None
        try:
            obj = json.loads(raw)
            note = obj.get("difficulty_note") if isinstance(obj, dict) else None
            return note if isinstance(note, str) and note.strip() else None
        except Exception:
            return None

    @staticmethod
    def _detect_difficulty(text) -> str | None:
        """从难度说明启发式识别难度桶: simple / medium / complex / None(无信号)

        仅对 difficulty_note 调用（正文噪声大）。按关键词**首次出现位置**判定，
        因为等级标记（入门级/中级难度）都在句首，而句尾常见"想深入理解原理的学生"
        这类建议性表述（含'深入/深度'）不能当作当前内容难度。
        注意: 不含裸'基础'（会命中'机器学习基础'等误判），不含'深入/深度'（建议性表述）。
        """
        if not text:
            return None
        t = str(text).lower()
        groups = {
            "simple": [r"入门级", r"入门难度", r"入门", r"初级", r"零基础", r"新手",
                       r"beginner", r"\bbasic\b", r"\bintro", r"fundamental"],
            "medium": [r"中级", r"intermediate"],
            "complex": [r"高级", r"专家", r"高阶", r"复杂",
                        r"expert", r"\badvanced\b", r"\bdeep\b"],
        }
        best = None  # (bucket, index)
        for bucket, pats in groups.items():
            for p in pats:
                m = re.search(p, t)
                if m and (best is None or m.start() < best[1]):
                    best = (bucket, m.start())
        return best[0] if best else None

    def _build_pairs(self) -> list:
        """按归一化问题，把 test_cases 与 task_resources 配对。"""
        by_q: dict = {}
        for r in self.task_resources:
            if self.bm_only and not (r.get("session_id") or "").startswith("bm_"):
                continue
            q = r.get("question")
            if q:
                by_q[self._norm_q(q)] = r
        pairs = []
        for tc in self.test_cases:
            q = tc.get("question")
            if q and self._norm_q(q) in by_q:
                pairs.append((tc, by_q[self._norm_q(q)]))
        return pairs

    @staticmethod
    def _point_covered(point_terms: set, gen_terms: set) -> bool:
        """参考要点是否被生成文本覆盖。

        覆盖判定: 命中术语占比 >= 0.5，或存在强信号（3-gram / 长度>=3 英文词）。
        """
        if not point_terms:
            return False
        matched = point_terms & gen_terms
        if not matched:
            return False
        if any(len(t) >= 3 for t in matched):
            return True
        return len(matched) / len(point_terms) >= 0.5

    def calc_factual_coverage_rate(self) -> dict:
        """核心知识点覆盖率(事实) = avg(单用例命中要点数 / 该用例总要点数)

        仅对 test_cases_100 与 task_resources 能按问题配对的用例计算。
        """
        pairs = self._build_pairs()
        if not pairs:
            return {
                "value": None,
                "sample_count": 0,
                "source": "task_resources 中无与 test_cases_100 匹配的问题",
                "detail": "请先运行基准评测生成资源: python -m backend.scripts.benchmark_testcases",
            }
        per_case = []
        for tc, res in pairs:
            points = tc.get("reference_answer_points") or []
            if not points:
                continue
            gen_terms = self._extract_terms(self._resource_text(res))
            covered = 0
            for p in points:
                if self._point_covered(self._extract_terms(p), gen_terms):
                    covered += 1
            per_case.append(covered / len(points))
        if not per_case:
            return {
                "value": None,
                "sample_count": len(pairs),
                "source": "reference_answer_points 命中率",
                "detail": "配对用例均无有效参考要点",
            }
        value = sum(per_case) / len(per_case)
        return {
            "value": value,
            "sample_count": len(per_case),
            "source": "reference_answer_points 命中率(task_resources vs test_cases_100)",
            "detail": f"matched_cases={len(pairs)}, covered_points_avg={value:.3f}",
        }

    def calc_factual_adaptation_rate(self) -> dict:
        """适配准确率 = 生成资源难度与 expected_complexity 匹配的样本比例。

        优先使用 LLM 复核（外部真值口径）；LLM 不可用时回退到关键词启发式。
        """
        pairs = self._build_pairs()
        if not pairs:
            return {
                "value": None,
                "sample_count": 0,
                "source": "task_resources 中无与 test_cases_100 匹配的问题",
                "detail": "请先运行基准评测生成资源: python -m backend.scripts.benchmark_testcases",
            }

        # 优先用 LLM 复核
        judge_results = self.ensure_llm_judge_results()
        if judge_results:
            matched = 0
            judged = 0
            for tc, res in pairs:
                exp = (tc.get("expected_complexity") or "").lower()
                if exp not in ("simple", "medium", "complex"):
                    continue
                norm_q = self._norm_q(tc.get("question", ""))
                r = judge_results.get(norm_q)
                if not r:
                    continue
                judged += 1
                if r.get("adaptation_matched"):
                    matched += 1
            if judged > 0:
                value = matched / judged
                return {
                    "value": value,
                    "sample_count": judged,
                    "source": "LLM 复核 (expected_complexity vs 生成讲义难度)",
                    "detail": f"judged={judged}, matched={matched}",
                }

        # 回退：关键词启发式（LLM 不可用时）
        matched = 0
        judged = 0
        no_signal = 0
        for tc, res in pairs:
            exp = (tc.get("expected_complexity") or "").lower()
            if exp not in ("simple", "medium", "complex"):
                continue
            note = self._lecture_difficulty_note(res)
            gen = self._detect_difficulty(note) if note else None
            if gen is None:
                no_signal += 1
                continue
            judged += 1
            if gen == exp:
                matched += 1
        if judged == 0:
            return {
                "value": None,
                "sample_count": len(pairs),
                "source": "expected_complexity vs 生成难度说明(启发式, fallback)",
                "detail": f"配对用例均无难度信号(no_signal={no_signal})",
            }
        value = matched / judged
        return {
            "value": value,
            "sample_count": judged,
            "source": "expected_complexity vs 生成资源难度说明(启发式, fallback)",
            "detail": f"judged={judged}, matched={matched}, no_signal={no_signal}",
        }

    def calc_all(self) -> dict:
        return {
            "error_rate": self.calc_error_rate(),
            "adaptation_rate": self.calc_adaptation_rate(),
            "coverage_rate": self.calc_coverage_rate(),
            "hallucination_rate": self.calc_hallucination_rate(),
            "force_pass_rate": self.calc_force_pass_rate(),
            "factual_coverage_rate": self.calc_factual_coverage_rate(),
            "factual_adaptation_rate": self.calc_factual_adaptation_rate(),
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

    # 赛题硬指标（事实比对口径，外部真值）
    print()
    print("  [赛题硬指标 —— 对照 test_cases_100.json 外部真值，非系统自评]")
    print(f"  {'指标':<20s} {'实际值':>8s} {'目标值':>8s} {'结果':>6s}  {'样本数':>6s}  数据来源")
    print("  " + "-" * 76)
    for key in OFFICIAL_KEYS:
        m = metrics[key]
        t = targets[key]
        val_str = _format_value(m["value"], t["unit"])
        tgt_str = _format_value(t["target"], t["unit"])
        pf = _pass_fail(m["value"], t["target"], t["compare"])
        print(f"  {t['label']:<24s} {val_str:>8s} {tgt_str:>8s} {pf:>6s}  {m['sample_count']:>6d}  {m['source']}")

    # 过程观测指标（系统自评，不作达标证据）
    print()
    print("  [过程观测指标 —— 系统自评，仅供诊断，不作达标证据]")
    print("  " + "-" * 76)
    for key in OBSERVED_KEYS:
        m = metrics[key]
        t = targets[key]
        val_str = _format_value(m["value"], t["unit"])
        print(f"  {t['label']:<24s} {val_str:>8s} {'-':>8s} {'-':>6s}  {m['sample_count']:>6d}  {m['source']}")

    # 指标详情
    print()
    print("  [指标详情]")
    for key in REPORT_KEYS:
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
        f"## 1. 赛题硬指标",
        f"",
        f"> 口径：全部对照 `tests/test_cases_100.json` 外部真值离线计算，**不采用系统自评分**。",
        f"> 自己给自己打分不能作为达标证据，故 Verifier/Evaluator/裁判团评分一律降级为过程观测指标。",
        f"",
        f"| 指标 | 实际值 | 目标值 | 结果 | 样本数 | 数据来源 |",
        f"|------|--------|--------|------|--------|----------|",
    ]

    for key in OFFICIAL_KEYS:
        m = metrics[key]
        t = targets[key]
        val_str = _format_value(m["value"], t["unit"])
        tgt_str = _format_value(t["target"], t["unit"])
        pf = _pass_fail(m["value"], t["target"], t["compare"])
        lines.append(f"| {t['label']} | {val_str} | {tgt_str} | {pf} | {m['sample_count']} | {m['source']} |")

    lines.append("")
    lines.append("### 过程观测指标（系统自评，不作达标证据）")
    lines.append("")
    lines.append("| 指标 | 实际值 | 样本数 | 数据来源 |")
    lines.append("|------|--------|--------|----------|")
    for key in OBSERVED_KEYS:
        m = metrics[key]
        t = targets[key]
        val_str = _format_value(m["value"], t["unit"])
        lines.append(f"| {t['label']} | {val_str} | {m['sample_count']} | {m['source']} |")

    lines.append("")
    lines.append("> **知识溯源率为何不能充当核心知识点覆盖率**：实测定标（40 条已知正确陈述 vs "
                 "10 条事实错误陈述）显示两者在知识库中的最高相似度分布几乎完全重合"
                 "（median 0.640 vs 0.641），在 0.58~0.72 各阈值下区分度均 ≈ 0。"
                 "即向量相似度只能刻画话题相关性，无法判定事实正确性。"
                 "故该指标语义收敛为「陈述可溯源到知识库文档」，覆盖率改由事实比对口径承担。")

    lines.append("")
    lines.append("## 2. 指标详情")
    lines.append("")

    detail_map = {
        "factual_coverage_rate": "核心知识点覆盖率（赛题硬指标 / 事实比对）",
        "factual_adaptation_rate": "适配准确率（赛题硬指标 / 事实比对）",
        "hallucination_rate": "幻觉率（赛题硬指标）",
        "error_rate": "专业知识谬误率（赛题硬指标）",
        "adaptation_rate": "教学适配度（观测 / 系统自评）",
        "coverage_rate": "知识溯源率（观测 / 系统自评）",
        "force_pass_rate": "强制放行率（观测：全票失败/修改超限强制通过）",
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
    lines.append("### 赛题硬指标（外部真值口径）")
    lines.append("")
    lines.append("| 指标 | 方案书定义 | 自动化方式 |")
    lines.append("|------|-----------|-----------|")
    lines.append("| 核心知识点覆盖率 | 100 道测试题核心知识点覆盖 | 生成资源对 `reference_answer_points` 的关键术语命中率（离线、零 LLM 调用） |")
    lines.append("| 适配准确率 | 学情测试 + 难度匹配 | `expected_complexity` 与生成资源难度说明的难度桶匹配率 |")
    lines.append("| 幻觉率 | 无根据编造/似真但错误占比 | `MetricsLLMJudge.hallucination`（硬化版）：HIGH 档 judge 检测生成内容（讲义+练习+测验全文）含参考要点未出现、且无可靠依据或明显错误的具体事实断言（虚构数据/API/论文/人物/命令/代码，或与公认事实矛盾、似真但错误，或强加不存在的能力）的样本比例；判定去除“不确定就给 false”的纵容 |")
    lines.append("| 专业知识谬误率 | 100 道测试题人工核验 | `MetricsLLMJudge.factual_error`：LLM 复核生成讲义相对 `reference_answer_points` 的事实错误；无 LLM 时回退 Verifier 自评 |")
    lines.append("")
    lines.append("### 过程观测指标（系统自评）")
    lines.append("")
    lines.append("| 指标 | 自动化方式 | 为何不作达标证据 |")
    lines.append("|------|-----------|------------------|")
    lines.append("| 教学适配度 | Evaluator `pedagogical_fit` 均值 | 系统自评，存在自利偏差 |")
    lines.append("| 知识溯源率 | 裁判团 `overall_verification_rate` | 相似度无法判定事实正确性（正负样本分布重合） |")
    lines.append("| 强制放行率 | count(override_reason IS NOT NULL) / total | 流程健康度诊断项，非赛题指标 |")
    lines.append("")
    lines.append("### 已知局限")
    lines.append("")
    lines.append("1. **专业知识谬误率**与**适配准确率**默认启用 LLM 复核（对照 test_cases_100 "
                 "reference_answer_points / expected_complexity），比 Verifier 自评和关键词启发式更接近外部真值；"
                 "若使用 `--no-llm` 则回退到旧口径，会重新引入测量污染。")
    lines.append("2. **核心知识点覆盖率**基于关键术语命中，可能低估同义改写覆盖情况。")
    lines.append("")

    return "\n".join(lines)


# ============================================================
# 主入口
# ============================================================

def main(run_kb: bool = True, bm_only: bool = False, use_llm: bool = True):
    logger.info("开始量化指标验证...")

    # 1. 从 DB 计算指标
    calc = MetricsCalculator(bm_only=bm_only, use_llm=use_llm)
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

    # 5. 返回退出码（仅按赛题硬指标判定；过程观测指标不影响成败）
    has_fail = False
    for key in OFFICIAL_KEYS:
        t = TARGETS[key]
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
    bm_only = False
    use_llm = "--no-llm" not in args
    if "--no-kb" in args:
        run_kb = False
    if "--bm-only" in args:
        bm_only = True
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

    sys.exit(main(run_kb=run_kb, bm_only=bm_only, use_llm=use_llm))
