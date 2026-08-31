# 项目材料文档（v4.1）审核报告

> 审核方法：逐条对照 `backend/` 真实源码核实文档中的硬 claim（数字、Agent 数、FSM、接口、指标、技术栈）。  
> 审核日期：2026-08-20。结论分 **严重 / 中等 / 轻微 / 已对齐** 四级。  
> 核心原则：**竞赛铁律——每个指标必须真测，低可以、假不行。** 文档里任何"看起来很厉害但代码没有"的声明都是风险点。

---

## 一、严重（必须改，否则评审对照代码会穿帮）

### 1. FSM 16 状态表的"状态名"与代码不符（数量对，名字错）
- **文档写法**（2.2 表格）：异常 2 态 = `TIMEOUT_ERROR` / `SYSTEM_ERROR`；延伸 5 态 = `REVISING` / `RETRYING` / `DEBATING` / `FALLBACK` / `HUMAN_REVIEW`。
- **代码真相**（`backend/core/fsm.py:20-43`）——`FSMState` 枚举共 **16 个**，但成员是：
  `IDLE, PROFILING, DISPATCHING, GENERATING, REVIEWING, FOCUSING, JUDGING, FORMATTING, COMPLETE`（主 9）＋ `REVISING, ERROR`（异常 2，其中**只有一个 `ERROR`**，没有 `TIMEOUT_ERROR`/`SYSTEM_ERROR`）＋ `QUIZ_EVAL, REDIMENSION, ADVANCE, RECHECK, HEURISTIC_FOLLOWUP`（延伸 5）。
- **问题**：文档列出的 `TIMEOUT_ERROR`、`SYSTEM_ERROR`、`RETRYING`、`DEBATING`、`FALLBACK`、`HUMAN_REVIEW` **在代码里根本不存在为 FSM 状态**。辩论/降级/人工复核这些机制确实存在，但实现为函数或队列（`judge_panel` 辩论逻辑、`orchestrator` 降级分支、`feedback` → `human_review_queue`），**不是枚举状态**。评审若 grep `FSMState`，会找到 16 个但名字对不上——等于把"实现概念"伪造成"已枚举的状态机状态"。
- **修改建议**：把 2.2 的状态表改成代码的真实 16 态（上列），并把"辩论/降级/人工复核"作为**机制说明**而非状态枚举。分组改为：主链 9 态 / 异常 1 态(`ERROR`) / 延伸 6 态(`REVISING`+`QUIZ_EVAL`+`REDIMENSION`+`ADVANCE`+`RECHECK`+`HEURISTIC_FOLLOWUP`)。

### 2. `/api/status` 响应示例是伪造的（4.2.5）
- **文档写法**：`GET /api/status/{task_id}` 示例返回含 `fsm_state / numpy_kb:"connected" / kb_chunks:34154 / kb_dim:1024 / sqlite / model_mid / model_high`。
- **代码真相**（`backend/api/routes/status.py:28-33`）：实际只返回 **`task_id / state / data / result`** 四个字段，没有 `kb_chunks`、`kb_dim`、服务连通性等任何字段。
- **问题**：示例响应与真实接口契约不符，评审照着 curl 会对不上。
- **修改建议**：把 4.2.5 的 `/api/status` 示例改成真实形态（task_id/state/data/result）；把"服务连通性/KB chunk 数"挪到 `/api/kb/health` 的说明里（该接口确实返回 `mode/chunk_count/chromadb_available/message`，见 `kb_manager.py:308-372`，但**也不返回 dim**）。

### 3. "10 个领域"的命名与代码 domain_tags 不符
- **文档写法**（2.2 / 5.1.2）：10 领域含 **项目实战**、**代码调试**。
- **代码真相**（`backend/agents/agent_registry.py:14-85`）：实际 `domain_tags` 去重后是 **9 个**：`LLM基础, Prompt工程, LangChain, RAG, 向量数据库, Agent框架, HuggingFace, 模型微调, 项目部署`。**没有 `代码调试` 这个标签**；`agent_009` 的标签是 **`项目部署`**（不是 `项目实战`）。`agent_010` 名为"代码调试Agent"但标签是 `[LangChain, HuggingFace, Prompt工程]`，并不挂 `代码调试`。
- **问题**：覆盖率分母（文档称"每领域 20 个核心知识点 ×10 = 200"）与实际 9 个领域标签对不上；且把"项目部署"写成"项目实战"是事实错。
- **修改建议**：把领域清单改为代码真实的 9 个 tag（或把 `agent_009` 的 tag 改为 `项目实战` 让代码与文档一致——二选一，但**必须先统一**）；同时复核覆盖率分母。

---

## 二、中等（建议改，影响严谨性/诚实度）

### 4. 指标 labeling 把"幻觉率"和"专业知识谬误率"合并了（5.3）
- **文档写法**（5.3.1 标题"专业知识谬误率（幻觉率）"、实际值 3.0%）：把两个指标混成一个，且漏掉独立的 0.0% 行。
- **代码/报告真相**（`docs/metrics_validation_report.md:13-16`）：这是**两个独立指标**——`幻觉率 3.0%` 与 `专业知识谬误率 0.0%`，加上 `适配准确率 100%`、`覆盖率 87.9%`，共 **4 项**。
- **修改建议**：5.3 改成 4 个独立子节（覆盖率 / 适配 / 幻觉 / 谬误），数值用报告真实值（87.9 / 100 / 3.0 / 0.0）。**注意**：文档 5.3 的**数字本身是对的**（87.9/100/3.0），只是标签和拆分错了。

### 5. 指标验证方法写成"3 名领域专家标注"，实际是 LLM 裁判
- **文档写法**（5.3.1）："3 名领域专家独立标注每条事实陈述的正确性，多数投票"。
- **真相**（`docs/metrics_validation_report.md:15`、`metrics_summary.md:37-52`）：用的是硬化版 `MetricsLLMJudge`（**HIGH 档 qwen-max**）独立复核，并非人工专家标注。
- **修改建议**：把验证方法改成"独立 LLM 裁判（qwen-max HIGH 档）硬化复核，可清空缓存当场重算"，保持诚实（竞赛铁律：别把 LLM 复核吹成人工金标准，但也别假称人工专家）。

### 6. 测验阈值写成"唯一 0.85"，代码实际有三档
- **文档写法**（2.4.5 / 3.3.2）：`正确率<0.85 → 降维；≥0.85 → 进阶`，只提一个门槛。
- **代码真相**（`backend/api/routes/quiz.py:20-23`、**接口实际调用路径**）：明确三档——`<60% 强降维` / `60%~85% 轻度降维` / `≥85% 进阶`。`orchestrator.py:1254` 那条单一 0.85 是另一条内部路径，但**前端走的是 quiz.py 这条三档逻辑**。
- **修改建议**：文档补上 60% 这一档（降维分"强/轻"两级），与 quiz.py 对齐。

### 7. 前端技术栈/传输方式存疑（4.1 / 2.2）
- **文档写法**：前端 "React + ECharts/recharts + FastAPI 原生 WebSocket 实时推送"；2.2 称"每个状态切换通过 WebSocket(/ws/{task_id}) 推送"。
- **真相**：
  - 后端 **确实有** WS 端点 `/ws/{task_id}`（`backend/api/routes/ws.py:17`），架构描述这部分**写对了**；
  - 但**实际队友前端走轮询** `GET /api/status`（后端日志反复出现 `无WebSocket连接，跳过推送`）；且我们仓库的参考页是**原生 HTML+CSS**，不是 React。
- **问题**：若提交的前端其实是轮询/原生实现，文档 4.1 的"React+ECharts+WebSocket 实时推送"就言过其实。
- **修改建议**：**先让队友确认真实前端栈与传输方式**。若确为轮询+原生，则 4.1 改为"原生前端 + 轮询/WebSocket 双通道"，2.2 写明"WebSocket 与轮询均可，当前演示用轮询兜底"。不要在没核实前把 React/WS 当既定事实写死。

### 8. KB chunk 数量 34154 需对齐真实加载值
- **文档写法**：全文统一 `34154 chunks`（2.2 / 4.2.3 / 4.2.5 / 5.1.2）。
- **真相**：`bm25_retriever.py:4` 注释也写"预计算 34154"，说明是**设计目标值**；但此前后端启动日志曾观察到 **`[NumpyKB] 加载完成: 30532 chunks`**（working memory 记录）。当前工作区 `data/` 被 gitignore 未同步，**无法直接核实真值**。
- **修改建议**：提交前用你机器上的真实启动日志 `[NumpyKB] 加载完成: N chunks, dim=1024` 把全文 34154 统一替换成真实 N。另：文档称"单文件存储"，实际 numpy_kb 是 `chunks.json + embeddings.npy + index.pkl + metadata.json` **四个文件**（见 `numpy_knowledge_base.py`），"单文件"表述不准。

---

## 三、轻微 / 内部一致性（确认即可）

- **"单文件存储"** → 如上，实为 4 文件，措辞微调。
- **4.2.3 称 `/api/kb/stats` 返回 404** → 代码 `kb.py` 确实无该路由（只有 health/import/search），**一致✓**，保留即可。
- **WebSocket 路径 `/ws/{task_id}`** → 代码正确（ws.py:17），文档架构部分写对了✓。

---

## 四、已对齐（文档写对了，给你吃定心丸）

| 文档 claim | 代码证据 | 结论 |
|---|---|---|
| 审核权重 `0.35/0.35/0.30` | `init_db.py:318`、`config_repo.py:42` | ✅ 一致 |
| α 四级 `0.9→0.7→0.5→0.3`（阈值 50/100/200） | `memory_service.py:173-175`、`test_gap_fixes.py` | ✅ 一致 |
| Agent 共 11 卡片（10 领域 + 1 资源生成） | `agent_registry.py:1-87`（`agent_011` 为资源生成 Agent，空 domain_tags） | ✅ 一致 |
| G01–G10 agent_name 与文档对应 | `agent_registry.py:11/18/25/32/39/46/53/60/67/74` | ✅ 名称一致（仅 domain_tags 见 #3） |
| 指标数值 87.9/100/3.0 | `metrics_validation_report.md:13` | ✅ 数值对（标签见 #4） |
| WebSocket 端点 `/ws/{task_id}` | `ws.py:17` | ✅ 路径对 |
| demo_cache 等 15 表 | `init_db.py` 建表 | ✅ 基本一致 |

---

## 五、优先修改清单（按风险排序）

1. 🔴 FSM 状态表改成代码真实 16 态（#1）
2. 🔴 `/api/status` 示例改成真实 4 字段（#2）
3. 🔴 领域清单对齐代码 9 个 tag（#3）
4. 🟠 5.3 拆成 4 个独立指标并纠正 labeling（#4）
5. 🟠 指标验证方法改为"LLM 裁判"而非"人工专家"（#5）
6. 🟠 补 quiz 60% 三档（#6）
7. 🟠 核实并改正前端栈/传输（#7）
8. 🟠 用启动日志真实 chunk 数替换 34154（#8）

> 一句话总结：**文档的"数字大方向"基本对（权重、α、Agent 数、指标值），但"架构状态机、接口示例、领域命名、指标标签/方法、前端栈、KB 数"这几处有与代码不符或言过其实的地方，评审若对照代码会扣分。按上面 8 条改完即可放心提交。**
