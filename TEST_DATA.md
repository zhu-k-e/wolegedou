# 测试数据交付说明（对应赛题「提交形式(三)」）

> 本文件说明测试数据的构成、位置与如何满足赛题要求，供评审核对与打包使用。

## 一、构成（三部分）

| 提交物 | 位置 | 规模 | 对应赛题要求 |
|---|---|---|---|
| 专业知识库切片 | `data/numpy_kb/` | 30532 chunks | ≥1 个垂直领域的专业知识库切片 |
| 差异化学习者学情数据源 | `data/io_examples/` | 3 组完整 I/O | ≥2 组差异化画像 + 完整输入输出示例 |
| 基准测试用例 | `tests/test_cases_100.json` | 100 条 | 指标评测的样本真值 |

---

## 二、1. 专业知识库切片（`data/numpy_kb/`）

预计算向量库四件套，bge-m3 编码，1024 维，覆盖 **10 个领域**（LLM基础 / Prompt工程 / LangChain / RAG / Agent框架 / HuggingFace / 模型微调 / 向量数据库 / 项目部署 / 代码调试）。

| 文件 | 大小 | 说明 |
|---|---|---|
| `vectors.npy` | 139.9 MB | 预计算向量矩阵（**已分卷**：`vectors.npy.part0` + `part1`，各 69.9 MB，打包时 `cat part0 part1 > vectors.npy` 合并） |
| `documents.json` | 12.8 MB | 文档正文 |
| `metadatas.json` | 16.1 MB | 元数据（domain / applicable_agents / language / source_doc / offset） |
| `ids.json` | 2.7 MB | chunk id |

> 加载时过滤非中英文 chunk，日志 `[NumpyKB] 加载完成: 30532 chunks, dim=1024`。

---

## 三、2. 差异化学习者学情数据源（`data/io_examples/`）

3 组真实落库的完整 I/O 示例（含输入画像 + 协同决策中间数据 + 最终资源），覆盖入门/中级/进阶三档学情，均为无强制放行标记（override_reason=null）的干净样例。

| 用例 | 画像 | 题目/领域 | 完整 I/O |
|---|---|---|---|
| `bm_TC-001_io.json` | 入门 / cs_student / LLM基础 | Token（语言模型基本单位） | ✅ |
| `bm_TC-020_io.json` | 中级 / developer / Agent框架 | ReAct 范式 | ✅ |
| `bm_TC-048_io.json` | 进阶 / developer / Agent框架 | 多 Agent 协作流程 | ✅ |

每组 JSON 结构（与赛题「完整输入输出示例」对齐）：
- `input_profile`（12 字段）：输入画像特征（background / knowledge_level / domain_hint / domain_confidence / test_results 等）
- `decision_mid`（14 字段）：多智能体协同决策中间数据（verdict / verification_rate / traceability / 各维度评分）
- `output_resources`（4 字段）：最终生成资源（lecture 讲义 / practice_guide 实操指南 / quiz 分阶测试题 5 题 / knowledge_refs 溯源）

> 详细口径（含引用标注「已验证 / 未命中KB检索」的区分）见 `data/io_examples/README.md`。

---

## 四、3. 基准测试用例（`tests/test_cases_100.json`）

100 条外部真值测试用例，画像覆盖 **4 种背景（cs_student / developer / researcher / product_manager）× 3 档水平（beginner / intermediate / advanced）**，用于四指标离线评测（覆盖率 / 适配率 / 幻觉率 / 谬误率）。结果见 `docs/metrics_validation_report.md`。

---

## 五、赛题要求对照结论

| 赛题「提交形式(三)」要求 | 满足情况 |
|---|---|
| ≥1 个垂直领域专业知识库切片 | ✅ 10 领域、30532 chunks、bge-m3 预计算 |
| ≥2 组差异化学习者学情数据源 | ✅ 3 组（入门/中级/进阶三档） |
| 含输入画像特征 | ✅ `input_profile` 12 字段 |
| 含多智能体协同决策中间数据 | ✅ `decision_mid` 14 字段 |
| 含最终生成的个性化学习资源 | ✅ `output_resources`（讲义+实操指南+测试题+溯源） |

## 六、打包注意

1. `vectors.npy` 超 100 MB（Git 单文件上限），已分卷 `part0`/`part1`，提交压缩包时可直接带完整 `vectors.npy` 或分卷均可，部署时合并。
2. 全部数据无 PII（画像仅含 background/knowledge_level/domain_confidence/test_results 等脱敏字段）。
