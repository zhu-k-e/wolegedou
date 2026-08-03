# 量化指标验证报告

> 生成时间: 2026-08-02 15:08:35
> 对应方案书: 第七部分 指标与验证（7.1 节赛题指标映射 + 7.2.3 节验证方法）

## 1. 赛题硬指标

> 口径：全部对照 `tests/test_cases_100.json` 外部真值离线计算，**不采用系统自评分**。
> 自己给自己打分不能作为达标证据，故 Verifier/Evaluator/裁判团评分一律降级为过程观测指标。

| 指标 | 实际值 | 目标值 | 结果 | 样本数 | 数据来源 |
|------|--------|--------|------|--------|----------|
| 核心知识点覆盖率 | 95.6% | 90.0% | PASS | 9 | reference_answer_points 命中率(task_resources vs test_cases_100) |
| 适配准确率 | 50.0% | 85.0% | FAIL | 8 | expected_complexity vs 生成资源难度说明(启发式, 待 LLM 复核) |
| 幻觉率 | 0.0% | 5.0% | PASS | 9 | task_metrics.verdict |
| 专业知识谬误率 | 33.3% | 5.0% | FAIL | 9 | task_metrics.fact_accuracy |

### 过程观测指标（系统自评，不作达标证据）

| 指标 | 实际值 | 样本数 | 数据来源 |
|------|--------|--------|----------|
| 教学适配度(自评) | 87.3% | 9 | task_metrics.pedagogical_fit |
| 知识溯源率(自评) | 94.7% | 9 | task_metrics.verification_rate |
| 强制放行率 | 11.1% | 9 | task_metrics.override_reason |

> **知识溯源率为何不能充当核心知识点覆盖率**：实测定标（40 条已知正确陈述 vs 10 条事实错误陈述）显示两者在知识库中的最高相似度分布几乎完全重合（median 0.640 vs 0.641），在 0.58~0.72 各阈值下区分度均 ≈ 0。即向量相似度只能刻画话题相关性，无法判定事实正确性。故该指标语义收敛为「陈述可溯源到知识库文档」，覆盖率改由事实比对口径承担。

## 2. 指标详情

### 核心知识点覆盖率（赛题硬指标 / 事实比对）
- **计算方式**: matched_cases=9, covered_points_avg=0.956
- **数据来源**: reference_answer_points 命中率(task_resources vs test_cases_100)
- **样本数**: 9

### 适配准确率（赛题硬指标 / 事实比对）
- **计算方式**: judged=8, matched=4, no_signal=1
- **数据来源**: expected_complexity vs 生成资源难度说明(启发式, 待 LLM 复核)
- **样本数**: 8

### 幻觉率（赛题硬指标）
- **计算方式**: passed=8, low_confidence_passed=1
- **数据来源**: task_metrics.verdict
- **样本数**: 9

### 专业知识谬误率（赛题硬指标）
- **计算方式**: avg_fact_accuracy=0.667
- **数据来源**: task_metrics.fact_accuracy
- **样本数**: 9

### 教学适配度（观测 / 系统自评）
- **计算方式**: avg_pedagogical_fit=0.873
- **数据来源**: task_metrics.pedagogical_fit
- **样本数**: 9

### 知识溯源率（观测 / 系统自评）
- **计算方式**: avg_verification_rate=0.947, traceability: 73/77 verified (94.8%), total_knowledge_refs=22
- **数据来源**: task_metrics.verification_rate
- **样本数**: 9

### 强制放行率（观测：全票失败/修改超限强制通过）
- **计算方式**: revision_limit_force_pass=1
- **数据来源**: task_metrics.override_reason
- **样本数**: 9

## 4. 验证方法说明

### 赛题硬指标（外部真值口径）

| 指标 | 方案书定义 | 自动化方式 |
|------|-----------|-----------|
| 核心知识点覆盖率 | 100 道测试题核心知识点覆盖 | 生成资源对 `reference_answer_points` 的关键术语命中率（离线、零 LLM 调用） |
| 适配准确率 | 学情测试 + 难度匹配 | `expected_complexity` 与生成资源难度说明的难度桶匹配率 |
| 幻觉率 | 裁判团 verdict 分布 | count(verdict in failed/revise) / total |
| 专业知识谬误率 | 100 道测试题人工核验 | 当前为 Verifier 自评代理，**待人工/LLM 标注替换**（见下方局限） |

### 过程观测指标（系统自评）

| 指标 | 自动化方式 | 为何不作达标证据 |
|------|-----------|------------------|
| 教学适配度 | Evaluator `pedagogical_fit` 均值 | 系统自评，存在自利偏差 |
| 知识溯源率 | 裁判团 `overall_verification_rate` | 相似度无法判定事实正确性（正负样本分布重合） |
| 强制放行率 | count(override_reason IS NOT NULL) / total | 流程健康度诊断项，非赛题指标 |

### 已知局限

1. **专业知识谬误率**仍依赖 Verifier 自评（`1 - avg(fact_accuracy)`），而 Verifier 在知识库检索为空时会给出 0.0 / 兜底 0.5，使该值失真；正式评测需以人工或强模型标注替换。
2. **适配准确率**当前用难度说明的关键词启发式判定难度桶，对措辞敏感，建议正式评测时改由 LLM 复核。
3. 事实比对基于关键术语命中，可能低估同义改写的覆盖情况。
