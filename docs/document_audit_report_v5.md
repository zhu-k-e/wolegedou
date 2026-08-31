# 项目材料文档 v5 深度审核报告

> 审核对象：`XH-202630-项目材料文档(5).docx`（用户 2026-08-21 提供的最新版，七章＋附录 A–G）
> 审核方法：把 .docx 抽成纯文本（`docs/_audit_source_v5.txt`），逐条对照 `backend/` 真实源码核实硬 claim（数字、Agent、FSM、接口、Schema、指标、技术栈、公式）。
> 对照基线：上一轮 v4.1 审核（`docs/document_audit_report.md`）已指出的问题，本轮确认**多数仍在 v5 中原样存在**，并新挖出一批。
> 核心原则：**竞赛铁律——每个指标必须真测，低可以、假不行。** 任何"看起来很厉害但代码没有 / 与代码契约不符"的声明都是风险点。

---

## 一、严重（必须改，评审对照代码会直接穿帮）

### S1. FSM 16 状态名虚构（2.2 表格1 + 行136）
- **文档**：主链 9 态 + 异常 2 态（`TIMEOUT_ERROR`/`SYSTEM_ERROR`）+ 延伸 5 态（`REVISING`/`RETRYING`/`DEBATING`/`FALLBACK`/`HUMAN_REVIEW`）。
- **代码真相**（`core/fsm.py:20-43`）：真实 16 态 = 主 9（`IDLE…COMPLETE`）+ **异常仅 1 个 `ERROR`** + 延伸 6（`REVISING`/`QUIZ_EVAL`/`REDIMENSION`/`ADVANCE`/`RECHECK`/`HEURISTIC_FOLLOWUP`）。
- **问题**：`TIMEOUT_ERROR`、`SYSTEM_ERROR`、`RETRYING`、`DEBATING`、`FALLBACK`、`HUMAN_REVIEW` **在代码里根本不是 FSM 状态**（辩论/降级/人工复核是函数或队列机制，非枚举态）。评审 grep `FSMState` 会找到 16 个但名字全对不上。
- **改法**：表格1 改成代码真实 16 态；把"辩论/降级/人工复核"挪到"机制说明"而非状态枚举。

### S2. `/api/status/{task_id}` 响应示例伪造（4.2.5 节 + 行944/951-962）
- **文档**：示例返回 `status/fsm_state/numpy_kb:"connected"/kb_chunks:34154/kb_dim:1024/sqlite/model_mid/model_high`。
- **代码真相**（`api/routes/status.py:23-30`）：真实只返回 **`task_id`/`state`/`data`/`result`** 四字段，无任何 kb/服务连通性字段。
- **改法**：示例改成真实四字段；把 KB 信息挪到 `/api/kb/health`（返回 `mode/chunk_count/chromadb_available/message`，也不含 dim）。行 944 "返回 FSM 当前状态与各服务连通性"一并改掉。

### S3. "10 个领域"命名与代码 domain_tags 不符（2.2 / 2.3.2 表格4 / 5.1.2 / 附录B/C）
- **文档**：10 领域含 **项目实战**（G09）、**代码调试**（G10）。
- **代码真相**（`agents/agent_registry.py:66-77`）：真实 9 个 domain_tags——`agent_009` 标签是 **`[Agent框架, 项目部署]`**（非"项目实战"，primary 是"项目架构与落地"）；`agent_010` 标签是 **`[LangChain, HuggingFace, Prompt工程]`**（**根本没有"代码调试"标签**）。
- **连带影响**：`DOMAIN_HINT_ENUMS`（`schemas/student_profile.py:96-99`）真实只有 9 个值（含 `项目部署`，无 `代码调试`）。所以：
  - 学情雷达图"10 领域"（2.2 行92）、knowledge_state"10 领域"（附录B）→ 实为 9 个 domain_hint 值。
  - 覆盖率分母"每领域 20 知识点 ×10 = 200"（5.3.3 行1205）→ 应为 9×20 = **180**。
- **改法**：全文档把"项目实战→项目部署"，删除"代码调试"领域（或改代码让两者一致，**先统一**）。

### S4. ★新·StudentProfile Schema 整体虚构（2.3.1 表格3 + 附录B）
- **文档表格3 声称字段**：`session_id / knowledge_state(10领域0~1概率) / background(dict) / skill_gaps(list) / learning_style(string) / intent_type(enum) / domain_hint(string) / confidence(float)`。
- **代码真相**（`schemas/student_profile.py:65-92`，权威 API 契约）：真实字段 = `knowledge_level / background(**枚举4值：文科/理科_无编程/有Python基础/有ML基础**) / current_goal(**枚举**) / question_type(枚举) / domain_hint(**list[str]**) / complexity_estimate(枚举) / intent_type(枚举) / domain_confidence(**dict[str, high/low]**) / test_results / session_id / version / changed_fields`。
- **硬伤**：
  1. **`knowledge_state`、`skill_gaps`、`learning_style` 在代码里完全不存在**（全仓 grep 无此字段）。掌握度用的是 `domain_confidence`（每个 domain_hint 标 high/low），**不是 0~1 概率**。
  2. **`background` 是 4 值枚举，不是 `{education/major/relevant_courses}` 字典**——附录 B 示例 `background:{education:本科, major:网络工程}` **违反枚举 schema，非法**。
  3. `domain_hint` 是**列表**不是字符串；还有 `current_goal/question_type/complexity_estimate` 等文档未提及的枚举字段。
- **连带推翻**：学情雷达图"10 领域知识掌握度(0~1)"、盲区热力图"知识点×掌握概率矩阵"——其数据基础（0~1 概率）与代码（high/low）不符。前端若真展示 0~1 概率雷达，需确认数据源（可能由 test_results 推，而非画像直接给出）。
- **改法**：2.3.1 表格3 整表改为代码真实字段；附录 B 示例改为符合枚举 schema 的合法 profile（background 用枚举值、domain_confidence 用 high/low）；雷达/热力图改称"领域置信度(high/low)"或说明其由 test_results 推导。

---

## 二、中等（建议改，影响严谨性/诚实度）

### M1. 指标把"幻觉率"和"专业知识谬误率"合并（5.3.1）
- 文档标题"专业知识谬误率（幻觉率）"、值 3.0%，漏掉独立的 0.0% 行。实为 4 独立指标：覆盖率 87.9% / 适配 100% / **幻觉 3.0%** / **谬误 0.0%**（`docs/metrics_validation_report.md`）。
- 数字本身对，标签和拆分错。改法：5.3 拆成 4 个独立子节。

### M2. 验证方法伪称"3 名领域专家标注"（5.3.1 行1181）
- 实际是硬化 `MetricsLLMJudge`（qwen-max HIGH 档）独立复核，非人工专家。改法：如实写"独立 LLM 裁判硬化复核，可清空缓存重算"。

### M3. quiz 阈值只写单一 0.85（2.4.5 / 3.3.2）
- 代码（`api/routes/quiz.py:20-23`）实为三档：`<60% 强降维` / `60%~85% 轻降维` / `≥85% 进阶`。补上 60% 一档。

### M4. 前端栈"React+ECharts+WebSocket 实时推送"言过其实（2.2 / 4.1 表格20 / 4.2 部署）
- WS 端点 `/ws/{task_id}` 确实存在（`api/routes/ws.py`），但**实际队友前端走轮询 `GET /api/status`**（后端日志反复 `无WebSocket连接，跳过推送`），仓库参考页是**原生 HTML+CSS** 非 React。文档 4.1 还写了 Node 18+/20 + `cd frontend && npm install/dev`、`localhost:5173`——若前端是原生页面，整段部署说明不成立。
- **改法**：先让队友确认真实栈。`React` 未证实时改为"原生前端 + 轮询/WebSocket 双通道"，2.2 写明"WebSocket 与轮询均可，当前演示用轮询兜底"，部署章节按真实前端调整。

### M5. KB chunk 数 34154 未对齐真值（2.2 行109/133、4.2.3 行911、5.1.2 行1036）
- 启动日志真实格式 `services/rag/numpy_knowledge_base.py:157` = `[NumpyKB] 加载完成: N chunks, dim=1024`。工作区曾实测 **30532**（设计目标 34154）。提交前用本机真实日志把全文 34154 统一替换成真实 N。

### M6. ★新·AST 危险调用集写错（3.2.4 节 + 7.3）
- 文档示例 `DANGEROUS_CALLS = {eval, exec, subprocess, os.system, __import__}`。
- 代码真相（`services/code_checker.py:16`）：真实集合 = **`{eval, exec, compile, __import__}`**。文档把 `compile` 错写成 `subprocess`/`os.system`。功能存在，但示例代码与实现不符，评审照抄会跑出不同结果。
- **改法**：示例改成 `{eval, exec, compile, __import__}`。

### M7. ★新·"单文件存储"与"四件套"自相矛盾（2.2 行133 vs 4.2.3 行910）
- 2.2 写 numpy_kb "单文件存储（34154 chunks，dim=1024）"；4.2.3 又写 `chunks.json + embeddings.npy + index.pkl + metadata.json 四件套`。真实是四文件。文档自己打架。
- **改法**：统一删掉"单文件存储"，改"四文件预计算向量库"。

### M8. ★新·覆盖率分母错（5.3.3 行1205）
- "每领域预定义 20 个核心知识点"×10 = 200。真实 domain_tags 仅 9 个（S3），分母应为 **180**。87.9% 数值本身没问题，但"200 知识点"基数表述错。改法：改成 9×20=180，或说明计分口径。

### M9. ★新·画像字段数三处不一致（表格3 / 单元测试表 / 附录B）
- 2.3.1 表格3 列 **8 字段**；4.3 单元测试表行985 写"结构化画像 JSON（**7 字段**齐全）"；附录 B 示例实际有 **12 字段**。三处数字互相矛盾，且三者都与真实 schema（S4）不符。改法：统一为代码真实字段集。

### M10. ★新·测试 persona "5 组"却只列 3 组（5.1.3 行1047、5.3.2 行1191 vs 5.2 仅 P1/P3/P5）
- 5.1.3 称"5 组差异化画像"，5.3.2 称"5 组 × 各 20 题 = 100 题评估"；但 5.2 只详述 P1/P3/P5 共 3 组。声称 5 组只给 3 组。
- 改法：补齐 P2/P4 用例，或把表述改为"3 组典型用例（覆盖零基础/进阶/转岗梯度），基准共 100 题"。

### M11. ★新·Matcher 早停 Top-1 分支未提及（2.3.2 / 2.4.1 / 2.4.4）
- 文档多次写"每段任务选出得分最高的 **2 个候选 Agent** 并行生成"。但代码（`agents/matcher.py:182,228`）有早停：**连续 2 轮 importance_score 波动 <0.05 → 只选 Top-1**（省 API 调用）。文档未说明存在 Top-1 分支。
- 改法：补一句"冷启动/稳定期每段 2 候选并行；importance_score 波动 <0.05 时早停为 Top-1 以省调用"。

### M12. ★新·functional_match / importance_score 公式与代码不一致（2.3.4 行404-407）
- 文档 `functional_match = |candidate.domain_tags ∩ task.domain_tags| / |task.domain_tags|`。
- 代码（`agents/matcher.py:285-314`）真实是 tiered 评分：domain 命中主标签→1.0、命中次标签→0.7、出现在 secondary_functions 文本→0.5，**不是交集比例**。
- 文档 `importance_score = 0.5×acc + 0.3×(1-rework) + 0.2×freq`——全仓 grep **未找到该公式的明确实现**（importance_score 只是 agent_performance 表字段，由更新逻辑写入，具体加权未在 matcher 内出现）。
- 改法：functional_match 改成代码真实 tiered 逻辑；importance_score 公式标注"待与 agent_performance 更新逻辑核对"或给出真实实现位置。

---

## 三、轻微 / 内部一致性（确认即可）

- **附录 B profile 违反枚举 schema**：见 S4，示例 `background/goal/domain_hint` 均不符真实枚举/列表类型，需整体重写成合法样例。
- **响应时间目标 ≤20s vs 真实 ~84s/问**（5.4 表35 行1224）：文档标"【待实测】"未造假，但真实单次问答约 84s，≤20s 设计目标大概率达不到。若后续填实测值，须填真实 ~84s，勿填 ≤20s。
- **单次成本 $0.27/次**（6.2/6.3 行1266）：财务声明不可独立验证，建议标注"按 deepseek-chat+qwen-max+qwen-turbo 分层估价的估算值"。
- **"19 协作单元"框架**（2.3.4 行384）：11 卡片(G01–G10+Formatter) + 8 角色(Analyzer/Matcher/Verifier/Skeptic/Evaluator/3 裁判) 属概念性表述，与"至少 3 个 Agent"对齐、可保留；但裁判团 3 人是否严格算 3 个独立"协作单元"属口径问题，不强制。
- **4.2.3 称 `/api/kb/stats` 返回 404**：代码 `kb.py` 确无该路由，一致✓。

---

## 四、已核对正确（放心，给你吃定心丸）

| 文档 claim | 代码证据 | 结论 |
|---|---|---|
| **15 张表**（agent_cards…task_resources） | `db/init_db.py` 建表 15 个，名称全对 | ✅ 完全一致 |
| 审核权重 0.35/0.35/0.30 + 三角色映射 | `agents/review_team.py:245-293` + `config_repo.get_review_weights()` | ✅ 一致 |
| 30+ 技术关键词硬映射表 + 意图兜底 | `agents/profile_agent.py:32-56,349-367` `_TECH_KEYWORD_MAP` | ✅ 存在 |
| Matcher 自身 0 次 LLM 调用 | `agents/matcher.py`（仅读 DB 算分，无 LLM 调用） | ✅ 一致 |
| 反向怀疑阈值 12/50/20 | `agents/judge_panel.py:125-140` | ✅ 一致 |
| RRF 融合 k=60 | `config.py:55` `kb_rrf_k=60` | ✅ 一致 |
| 检索 top_k=3 | `services/rag/numpy_knowledge_base.py:263` | ✅ 一致 |
| bge-m3 dim=1024 | `services/rag/numpy_knowledge_base.py:4,77,157` | ✅ 一致 |
| 裁判团 3 人独立裁决（3 类裁判） | `agents/judge_panel.py:34/62/87/110` JudgeFact/JudgeLogic/JudgeApplicability | ✅ 一致 |
| agent_registry 无 source 字段 | `agents/agent_registry.py`（卡片仅 agent_id/primary_function/domain_tags） | ✅ 一致 |
| 模型档位 HIGH=qwen-max / MID=deepseek-chat / LOW=qwen-turbo | `config.py` + `.env`（与文档 4.1 表格20 一致） | ✅ 一致 |
| α 四级 0.9→0.7→0.5→0.3（阈值 50/100/200） | `memory_service.py` + `agents/matcher.py:184` | ✅ 一致 |
| FSM 修改上限 2 次 | `FSM_MAX_REVISIONS=2` | ✅ 一致 |
| 生成用 MID 档（ModelTier.MID） | `domain_agent.py` 生成调用 MID | ✅ 一致 |
| 指标数值 87.9/100/3.0 | `docs/metrics_validation_report.md` | ✅ 数值对（标签见 M1） |

> 注：本轮验证纠正了"15 表/权重/关键词表/Matcher 0 LLM/反向怀疑/RRF/top_k/dim/裁判团"等此前未核或仅粗略核过的项——**这些文档写对了**，不是漏洞。

---

## 五、优先修复清单（按评审风险排序）

1. 🔴 **S4** StudentProfile Schema 整表重写 + 附录 B 合法样例（牵动雷达/热力图数据基础，最致命）
2. 🔴 **S1** FSM 状态表改成代码真实 16 态
3. 🔴 **S2** `/api/status` 示例改成真实 4 字段
4. 🔴 **S3** 领域清单对齐代码 9 个 tag（项目实战→项目部署，删代码调试）
5. 🟠 **M7** 删"单文件存储"，统一"四文件"
6. 🟠 **M6** AST 危险集 compile 替换 subprocess/os.system
7. 🟠 **M8** 覆盖率分母 200→180
8. 🟠 **M1** 5.3 拆 4 个独立指标
9. 🟠 **M2** 验证方法改"LLM 裁判"非人工专家
10. 🟠 **M3** 补 quiz 60% 三档
11. 🟠 **M4** 核实并改正前端栈/部署说明
12. 🟠 **M5** 用启动日志真实 chunk 数替换 34154
13. 🟠 **M9/M10** 画像字段数统一、测试 persona 数量统一
14. 🟠 **M11/M12** Matcher 早停分支、functional_match/importance_score 公式对齐代码
15. 🟡 附录 B 样例按枚举 schema 重写；响应时间/成本标注口径

> 一句话总结：**v5 比 v4.1 多了大量可核查细节，但"StudentProfile Schema 整体虚构"是本轮最严重的新漏洞（牵动雷达/热力图数据基础与附录 B 样例合法性），且上一轮的 FSM 状态名、/api/status 伪造示例、领域命名错三处仍原样未改。** 同时已确认 15 表/权重/关键词表/Matcher/反向怀疑/RRF/top_k/dim/裁判团等十余项文档写对了。按上面清单改完即可放心提交。
