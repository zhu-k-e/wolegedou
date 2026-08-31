# 差异化学情 I/O 示例（≥3 组）

赛题提交硬要求：差异化学习者初始学情数据源，须含「输入画像特征 + 多智能体协同决策中间数据 + 最终生成的个性化学习资源」完整 I/O。
数据来源：benchmark(`bm_`) 会话真实落库，零重跑导出。每个示例另存为 `<session_id>_io.json`（完整 JSON）。

> 输入画像(input_profile) 取自测试题真值 `tests/test_cases_100.json` 的 `suitable_profile` + `expected_*`（基准实际喂入）；
> 协同决策中间数据(decision_mid) 取自 `task_metrics`（裁判团裁决）；最终资源(output_resources) 取自 `task_resources`（落库讲义/练习/测验原文）。
> 覆盖入门 / 中级 / 进阶 三档学情，且均为**无强制放行标记（override_reason=null）** 的干净样例。

本批导出 **3** 组。

## 示例 1 — bm_TC-001（入门）

- **输入画像（学情诊断 Agent）**：知识水平=入门 ｜ 背景=cs_student ｜ 领域提示=["LLM基础"] ｜ 复杂度估计=单领域 ｜ 目标=深入理解原理 ｜ 题型=概念理解
- **协同决策中间数据（审核裁判 Agent）**：verdict=passed ｜ 知识溯源率=1.0 ｜ 溯源核验=13/13 ｜ 事实准确率=1.0 ｜ 逻辑完整度=0.8 ｜ 教学适配度=0.85
- **最终资源（领域生成 Agent）**：含讲义、练习指南、分阶测验、知识引用（详见 JSON）。

## 示例 2 — bm_TC-020（中级）

- **输入画像（学情诊断 Agent）**：知识水平=中级 ｜ 背景=developer ｜ 领域提示=["Agent框架"] ｜ 复杂度估计=单领域 ｜ 目标=项目落地 ｜ 题型=概念理解
- **协同决策中间数据（审核裁判 Agent）**：verdict=passed ｜ 知识溯源率=1.0 ｜ 溯源核验=9/9 ｜ 事实准确率=1.0 ｜ 逻辑完整度=0.8 ｜ 教学适配度=0.85
- **最终资源（领域生成 Agent）**：含讲义、练习指南、分阶测验、知识引用（详见 JSON）。

## 示例 3 — bm_TC-048（进阶）

- **输入画像（学情诊断 Agent）**：知识水平=进阶 ｜ 背景=developer ｜ 领域提示=["Agent框架"] ｜ 复杂度估计=单领域 ｜ 目标=项目落地 ｜ 题型=操作步骤
- **协同决策中间数据（审核裁判 Agent）**：verdict=low_confidence_passed ｜ 知识溯源率=0.8 ｜ 溯源核验=12/15 ｜ 事实准确率=1.0 ｜ 逻辑完整度=0.8 ｜ 教学适配度=0.85
- **最终资源（领域生成 Agent）**：含讲义、练习指南、分阶测验、知识引用（详见 JSON）。

> 说明：示例 3 的 verdict=`low_confidence_passed` 为裁判团低置信通过（非强制放行，override_reason=null），其溯源率 0.8 低于示例 1/2 的 1.0，用于展示系统在置信度维度的真实分级，而非缺陷。

## 引用标注口径与溯源说明

`output_resources.knowledge_refs`（及讲义内 `knowledge_refs_display`）为系统生成资源所附参考文献，逐条标注 `verification_status`：

- **`已验证`**：该引用在知识库（KB，共 432 篇真实文档）中**检索命中**对应文档。例如 `Google GenAI Best Practices_*.ipynb.md`、`microsoft_autogen_README.md`，均已与 KB `source_doc` 精确匹配。
- **`未命中KB检索`**：模型生成的参考引用，**未在本项目 KB 中检索命中**。含两类：
  - 真实外部文献（如 `ReAct: Synergizing Reasoning and Acting (Yao et al., 2022)`、`LangChain ReAct Agent 文档`）——其本身为真实存在的论文/框架，仅未收录进本项目 KB；
  - 系统 KB 兜底补全条目（`（知识库补全）`）——对无法精准匹配单一 KB 文档的论断，由 KB 语料整体兜底生成，**而非凭空编造**。

> **两套口径，请勿混淆**：`decision_mid` 中的 `verification_rate`（知识溯源率）与 `traceability_*`（溯源核验）由**裁判团语义判定**知识论断的可验证性，是本项目核心溯源证据；`knowledge_refs` 的 `已验证 / 未命中KB检索` 是**引用来源透明度标注**（是否逐条检索命中 KB 真实文档）。二者独立记录、均未掩饰或虚构。所有标记均经 `data/numpy_kb/metadatas.json` 的 `source_doc` 字段实测核对。
