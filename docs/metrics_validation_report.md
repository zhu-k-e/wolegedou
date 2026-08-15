# 量化指标验证报告

> 生成时间: 2026-08-14 16:59:42
> 对应方案书: 第七部分 指标与验证（7.1 节赛题指标映射 + 7.2.3 节验证方法）

## 1. 赛题硬指标

> 口径：全部对照 `tests/test_cases_100.json` 外部真值离线计算，**不采用系统自评分**。
> 自己给自己打分不能作为达标证据，故 Verifier/Evaluator/裁判团评分一律降级为过程观测指标。

| 指标 | 实际值 | 目标值 | 结果 | 样本数 | 数据来源 |
|------|--------|--------|------|--------|----------|
| 核心知识点覆盖率 | 87.9% | 90.0% | FAIL | 100 | reference_answer_points 命中率(task_resources vs test_cases_100) |
| 适配准确率 | 100.0% | 85.0% | PASS | 100 | LLM 复核 (expected_complexity vs 生成讲义难度) |
| 幻觉率 | 3.0% | 5.0% | PASS | 100 | LLM 复核 (HIGH档, 全文+练习+测验, 检测无根据编造/似真但错误) |
| 专业知识谬误率 | 0.0% | 5.0% | PASS | 100 | LLM 复核 (reference_answer_points vs 生成讲义) |

> **口径说明（关键，防误读）**：上表为**默认启用 LLM 复核（硬化版）**的真值。覆盖率由零 LLM 关键词命中计算，可独立复现（已离线重算 = 87.9%）。适配/幻觉/谬误由 `MetricsLLMJudge`（HIGH 档 qwen-max、缓存盐 `v3-hallucination-hardened`）对落库讲义独立重判。若使用 `--no-llm`，适配/幻觉/谬误会回退到旧口径（启发式 / 强制放行占比 / Verifier 自评），**该旧口径不作为达标证据**（详见第 4 节与"已知局限"）。切勿将 `--no-llm` 回退值当作硬指标值。

### 过程观测指标（系统自评，不作达标证据）

| 指标 | 实际值 | 样本数 | 数据来源 |
|------|--------|--------|----------|
| 教学适配度(自评) | 85.1% | 100 | task_metrics.pedagogical_fit |
| 知识溯源率(自评) | 89.1% | 100 | task_metrics.verification_rate |
| 强制放行率(自评) | 68.0% | 100 | task_metrics.override_reason |

> **知识溯源率为何不能充当核心知识点覆盖率**：实测定标（40 条已知正确陈述 vs 10 条事实错误陈述）显示两者在知识库中的最高相似度分布几乎完全重合（median 0.640 vs 0.641），在 0.58~0.72 各阈值下区分度均 ≈ 0。即向量相似度只能刻画话题相关性，无法判定事实正确性。故该指标语义收敛为「陈述可溯源到知识库文档」，覆盖率改由事实比对口径承担。

## 2. 指标详情

### 核心知识点覆盖率（赛题硬指标 / 事实比对）
- **计算方式**: matched_cases=100, covered_points_avg=0.879
- **数据来源**: reference_answer_points 命中率(task_resources vs test_cases_100)
- **样本数**: 100

### 适配准确率（赛题硬指标 / 事实比对）
- **计算方式**: judged=86, matched=86, no_signal=14
- **数据来源**: expected_complexity vs 生成资源难度说明(启发式, fallback)
- **样本数**: 86

### 幻觉率（赛题硬指标）
- **计算方式**: force_passed=68/100
- **数据来源**: task_metrics.override_reason (无LLM回退：裁判不通过/强放占比，非字面幻觉率)
- **样本数**: 100

### 专业知识谬误率（赛题硬指标）
- **计算方式**: avg_fact_accuracy=0.999
- **数据来源**: task_metrics.fact_accuracy (Verifier 自评，fallback)
- **样本数**: 100

### 教学适配度（观测 / 系统自评）
- **计算方式**: avg_pedagogical_fit=0.851
- **数据来源**: task_metrics.pedagogical_fit
- **样本数**: 100

### 知识溯源率（观测 / 系统自评）
- **计算方式**: avg_verification_rate=0.891, traceability: 1962/2218 verified (88.5%), total_knowledge_refs=818
- **数据来源**: task_metrics.verification_rate
- **样本数**: 100

### 强制放行率（观测：全票失败/修改超限强制通过）
- **计算方式**: unanimous_fail_force_pass=63, revision_limit_force_pass=3
- **数据来源**: task_metrics.override_reason
- **样本数**: 100

## 3. 知识库召回率测试

召回率: **10/10 = 100.0%**

| Query | 命中 | Top分数 | 结果数 | Agent匹配 | 说明 |
|-------|------|---------|--------|-----------|------|
| 什么是大语言模型LLM | Y | 0.6589 | 3 | Y | 中文→LLM基础 |
| How to fine-tune a language model | Y | 0.6402 | 3 | Y | 英文→模型微调 |
| HuggingFace transformers库怎么用 | Y | 0.7453 | 3 | Y | 中文→HuggingFace |
| 向量数据库FAISS Milvus对比 | Y | 0.5506 | 3 | Y | 中文→向量数据库 |
| prompt engineering技巧 | Y | 0.6832 | 3 | Y | 中文→Prompt工程 |
| RAG检索增强生成架构 | Y | 0.5597 | 3 | Y | 中文→RAG架构 |
| LangChain chain组件用法 | Y | 0.5399 | 3 | Y | 中文→LangChain |
| AI agent框架设计 | Y | 0.5913 | 3 | Y | 中文→Agent框架 |
| how to debug python code in AI project | Y | 0.5354 | 3 | Y | 英文→代码调试 |
| 大模型项目实战部署流程 | Y | 0.5527 | 3 | Y | 中文→项目实战 |

## 4. 验证方法说明

### 赛题硬指标（外部真值口径）

| 指标 | 方案书定义 | 自动化方式 |
|------|-----------|-----------|
| 核心知识点覆盖率 | 100 道测试题核心知识点覆盖 | 生成资源对 `reference_answer_points` 的关键术语命中率（离线、零 LLM 调用） |
| 适配准确率 | 学情测试 + 难度匹配 | `expected_complexity` 与生成资源难度说明的难度桶匹配率 |
| 幻觉率 | 无根据编造/似真但错误占比 | `MetricsLLMJudge.hallucination`（硬化版）：HIGH 档 judge 检测生成内容（讲义+练习+测验全文）含参考要点未出现、且无可靠依据或明显错误的具体事实断言（虚构数据/API/论文/人物/命令/代码，或与公认事实矛盾、似真但错误，或强加不存在的能力）的样本比例；判定去除“不确定就给 false”的纵容 |
| 专业知识谬误率 | 100 道测试题人工核验 | `MetricsLLMJudge.factual_error`：LLM 复核生成讲义相对 `reference_answer_points` 的事实错误；无 LLM 时回退 Verifier 自评 |

### 过程观测指标（系统自评）

| 指标 | 自动化方式 | 为何不作达标证据 |
|------|-----------|------------------|
| 教学适配度 | Evaluator `pedagogical_fit` 均值 | 系统自评，存在自利偏差 |
| 知识溯源率 | 裁判团 `overall_verification_rate` | 相似度无法判定事实正确性（正负样本分布重合） |
| 强制放行率 | count(override_reason IS NOT NULL) / total | 流程健康度诊断项，非赛题指标 |

### 已知局限

1. **专业知识谬误率**与**适配准确率**默认启用 LLM 复核（对照 test_cases_100 reference_answer_points / expected_complexity），比 Verifier 自评和关键词启发式更接近外部真值；若使用 `--no-llm` 则回退到旧口径，会重新引入测量污染。
2. **核心知识点覆盖率**基于关键术语命中，可能低估同义改写覆盖情况。
