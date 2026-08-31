# v6 项目材料文档审核报告（独立代码核查）

> 审核对象：`XH-202630-项目材料文档(6).docx`（v5.0 / 2026-08-22）
> 审核日期：2026-08-22
> 方法说明：**本版不依赖历史记忆**，将 docx 全文抽取到 `docs/_audit_source_v6.txt`（2107 行），对每一处硬 claim 实际 Grep/Read 当前 `backend/` 代码确证，附文件:行号证据。

---

## 一、本轮独立复核确认正确的 claim（节选，证明已实测而非凭记忆）

| # | 文档 claim | 位置 | 代码证据 | 结论 |
|---|-----------|------|---------|------|
| 1 | FSM 共 16 态（主链 9 + 异常 1 + 延伸 6） | 97 | `core/fsm.py` 枚举 16 个 | ✓ |
| 2 | 4 个核心接口 `/status` `/ws` `/report` `/kb/health` 真实存在 | 88/228 等 | `api/routes/{status,ws,report,kb}.py` | ✓ |
| 3 | `/status/{task_id}` 返回 `task_id/state/data/result` 四字段 | 992 | `api/routes/status.py` | ✓ |
| 4 | Agent 注册表 11 张卡、返回 10 个领域子 Agent | 321/583 | `agents/agent_registry.py:4,99`（`get_domain_agents` 返 10） | ✓ |
| 5 | StudentProfile 字段无虚构（knowledge_level/domain_confidence/intent_type/complexity_estimate/background/test_results） | 198 | `schemas/student_profile.py:30+` | ✓ |
| 6 | 知识库 34154 chunks / dim=1024 | 71/95/109/1452 | `data/numpy_kb/vectors.npy` shape `(34154,1024)` 实测 | ✓ |
| 7 | 实测指标 87.9% / 3.0% / 100% / 0.0% | 1692 | `docs` 回填值与 benchmark 一致 | ✓ |
| 8 | 裁判加权 0.35/0.35/0.30 | 547/1358 | `db/init_db.py:371`、`config_repo.py:42` | ✓ |
| 9 | 辩论机制（challenge/defense + 裁判团分歧）真实实现 | 698-739 | `domain_agent.py:628-671`、`judge_panel.py:414-441` | ✓ |
| 10 | `human_review_queue` 表真实存在 | 226/801 | `db/init_db.py:142`、`memory_service.py:249` | ✓ |
| 11 | `VerificationStatus` 枚举（已验证/待验证/矛盾） | 925 | `schemas/judge_verdict.py:23-26` | ✓ |
| 12 | 资源三形态 lecture/practice_guide/quiz | 175/743 | `schemas/resource_package.py:7-9,106-116` | ✓ |
| 13 | 模型档位 HIGH=qwen-max / MID=deepseek-chat / LOW=qwen-turbo | 1251-1253 | `services/llm_client.py:38-40,55,64-65` | ✓ |
| 14 | 报告三图：盲区热力图 + 难度曲线 + 学习路径图 | 4/91 | `api/routes/report.py:97/204/227` | ✓ |
| 15 | 可视化看板五组件 | 91-96 | 列表 5 项，与前端看板对应 | ✓ |
| 16 | 决策引擎五大机制（任务分配/状态管理/冲突仲裁/结果聚合/反馈路由） | 625 | 2.4.1–2.4.5 共 5 节 | ✓ |

---

## 二、需修正的问题（按严重度排序）

### 🔴 严重（硬错，评委可能逐字核对代码/文件）

**问题 1：numpy_kb 知识库文件清单全部写错**
- 文档位置：line 1454
- 文档原文：`numpy_kb 四件套文件存储（chunks.json + embeddings.npy + index.pkl + metadata.json，dim=1024）`
- 代码真相：`backend/services/rag/numpy_knowledge_base.py`
  - 文件头注释（4-7 行）：`vectors.npy / documents.json / metadatas.json / ids.json`
  - `REQUIRED_FILES = ("vectors.npy", "documents.json", "metadatas.json", "ids.json")`（line 61）
  - 加载逻辑（100-103 行）：`np.load("vectors.npy")` + `_load_json("documents.json"/"metadatas.json"/"ids.json")`
  - 实际目录 `data/numpy_kb/`：`documents.json / ids.json / metadatas.json / vectors.npy`（无 index.pkl）
- **结论**：文档列的四文件名**无一正确**（chunks.json≠documents.json、embeddings.npy≠vectors.npy、index.pkl 不存在、metadata.json≠metadatas.json）。属严重虚构/过时描述。
- 修正：改为 `vectors.npy + documents.json + metadatas.json + ids.json（dim=1024）`。

**问题 2：单元测试规模与状态严重失实**
- 文档位置：line 2081「单元测试 22 项」；line 1303-1424「4.3 单元测试用例」表格
- 文档原文：声称「单元测试 22 项」；表格列测试点，状态列全部为「【待实测】」。
- 代码真相：
  - `backend/tests/` 实测 **15 个 `test_*.py` 文件、212 个 `def test_` 用例**（已用 grep 统计）。
  - 表格「4.3 单元测试用例」实际列 **23 行**测试点（非 22），且每行状态均为「【待实测】」——即文档展示的测试方案**一个都未执行/未回填**。
- **结论**：
  1. 数字错（22≠23 行表格，更≠实际 212 用例）；
  2. 测试章节形同空白——真实存在的 200+ 自动化用例完全未写入文档，反而列了一堆「待实测」假想点。竞赛「完整性 30 分」评委看到整章未实测会严重扣分。
- 修正：要么把「单元测试 22 项」改为真实统计（15 文件 / 212 用例）并补真实用例说明；要么标注清楚表格是「计划测试点」而非已执行项，并补充实际 pytest 结果。

**问题 3：版本说明（line 2105）宣称已修正的项，正文仍错——声明与内容不符**
- 文档位置：line 2105
- 文档原文：「本版修正 teammate 第二轮深度核查（StudentProfile Schema 重写 / FSM 真实 16 态 / **9 领域统一** / **降维三档** / **AST 危险集** / 指标拆 4 项 / …）」
- 真相对照：
  - 声称「AST 危险集」已修正 → 但正文 line 776 仍写 `{eval, exec, compile, __import__}`（错，见问题 5），**未修正**。
  - 声称「9 领域统一」 → 但正文 line 62、line 100 仍写「9 领域子 Agent」（应为 10），line 1450 仍写「10 个领域」（应为 9），**未统一**。
  - 声称「降维三档」已修正 → 但正文「降维三档」措辞仍把 ADVANCE 进阶档包含在内（见问题 9），**未修正**。
- **结论**：版本说明夸大修正范围，声明与实际内容冲突，易被评委视为不严谨。

### 🟠 高（涉及安全机制/实时可视化两个评分点）

**问题 4：WebSocket 推送虚构「Agent 列表 + 进度百分比」字段**
- 文档位置：line 228
- 文档原文：「每个状态切换通过 WebSocket（/ws/{task_id}）推送状态名称、**当前 Agent 列表**、中间产物摘要与**整体进度百分比**」
- 代码真相：`services/ws_manager.py` 的 `push_state(task_id, state, data)` 仅推 `{type, task_id, state, data}`；`core/orchestrator.py` 全部 `push_state` 调用只传 state + 各状态中间产物（profile/candidates/result 等）。**没有「当前 Agent 列表」字段，也没有「整体进度百分比」字段**。
- 注：line 88「实时推送资源包 + 逐条溯源链标注」基本真实（JUDGED 后推 result 含 ResourcePackage + 溯源链），但 line 228 多了两个不存在的字段。
- 修正：line 228 改为「推送状态名称 + 中间产物（含溯源链）摘要」，删除「当前 Agent 列表」「整体进度百分比」。

**问题 5：AST 危险集列举错误**
- 文档位置：line 776
- 文档原文：「真实代码危险集为 `{eval, exec, compile, __import__}`」
- 代码真相：`backend/services/code_checker.py:15-26` 实际为：
  - 危险函数名 **9 个**：`eval / exec / compile / __import__ / globals / locals / vars / open / input`
  - 危险模块 **13 个**：`os / sys / subprocess / shutil / pathlib / socket / requests / pickle / tempfile / platform / mmap / ctypes / multiprocessing`
- 修正：line 776 改为实际 9 函数 + 13 模块，或注明「详见 code_checker.py:_DANGEROUS_NAMES/_DANGEROUS_MODULES」。

**问题 6：领域 Agent 数与领域数自相矛盾**
- 文档位置：line 62、line 100（写「9 领域子 Agent」）；line 1450（写「10 个领域」）
- 真相：
  - `agents/agent_registry.py:4` 明确「10 个领域 Agent + 1 个资源生成 Agent」；`get_domain_agents()` 返回 **10** 个。
  - 10 个 agent 的 `domain_tags` 去重后恰为 **9 个领域**（LLM基础/Prompt工程/LangChain/RAG/向量数据库/Agent框架/HuggingFace/模型微调/项目部署）—— line 321、583、1758 的正确表述也是「10 agent + 9 领域 tag」。
  - 故：line 62/100 把 agent 数错写成 9；line 1450 把领域数错写成 10。与同文档正确表述（321/583/1758）直接冲突。
- 修正：line 62/100 改「10 个领域子 Agent 并行」；line 1450 改「9 个领域的官方文档」。

### 🟡 中 / 低

**问题 7：文档完全未提及 Docker / 容器化部署（覆盖遗漏）**
- 文档全文搜 `Docker / 容器 / 镜像 / docker-compose` **0 命中**。
- 代码侧 `D:/projects/wolegedou/Dockerfile` 真实存在（memory 记「已确认满足 Dockerfile+OMP workaround」）。
- 结论：非虚构 claim，但属**完整性覆盖缺口**——赛题有容器化/可复现要求，文档未写部署章节（仅 line 1136/1236 泛泛提「部署」「离线演示」），可能丢「完整性」分。
- 建议：补一节「容器化部署（Dockerfile + OMP 段错误 workaround）」。

**问题 8：溯源链示例 `verification_status` 值与代码枚举不符（轻微）**
- 文档位置：line 767 / 773 示例 JSON 写 `"verification_status": "verified"`（小写英文）
- 代码真相：`schemas/judge_verdict.py:24` 枚举值 `VERIFIED = "已验证"`（中文）。
- 修正：示例改为 `"已验证"`，与 judge_panel.py:679 映射一致。

**问题 9：「降维三档」措辞含进阶档（轻微，上轮已记）**
- 文档位置：line 2085「降维三档」；line 787-798 表格
- 真相：第三档（正确率 ≥85%）触发 `ADVANCE` **进阶挑战**，并非降维（`quiz.py:20-23` 难度自适应）。
- 修正：改称「难度自适应三档（强降维 / 轻降维 / 进阶）」或「反馈路由三档」，避免把进阶归入降维。

---

## 三、修改优先级汇总

| 优先级 | 问题 | 位置 | 性质 |
|--------|------|------|------|
| 🔴 严重 | numpy_kb 四文件名全错 | 1454 | 硬错（文件清单虚构） |
| 🔴 严重 | 单元测试 22 项 + 全「待实测」 | 1303-1424 / 2081 | 规模错 + 测试章节形同空白 |
| 🔴 严重 | 版本说明宣称已修正但正文仍错 | 2105 | 声明与内容不符 |
| 🟠 高 | WebSocket 虚构 Agent列表+进度% | 228 | 字段虚构 |
| 🟠 高 | AST 危险集列举错误 | 776 | 硬错（安全机制） |
| 🟠 高 | 领域 Agent 数/领域数自相矛盾 | 62/100/1450 | 内部不一致 |
| 🟡 中 | 未提 Docker/容器化部署 | 全文 | 覆盖遗漏 |
| 🟡 低 | 溯源示例 verified≠已验证 | 767/773 | 枚举值不符 |
| 🟡 低 | 降维三档措辞含进阶 | 2085/799 | 措辞混淆 |

---

## 四、结论

v6 相比 v5 已修复 StudentProfile/FSM/路由等硬伤，**架构层 claim 绝大部分经代码复核正确**（见第一节 16 项）。但本轮独立核查仍暴露 **3 个严重硬错 + 3 个高优先问题**，其中：
- `numpy_kb` 文件名（问题 1）和 AST 危险集（问题 5）若被评委核对文件/代码将直接判伪；
- 单元测试章节（问题 2）整章「待实测」与真实 212 用例脱节，是完整性最大失分点；
- 领域数矛盾（问题 6）与版本说明夸大（问题 3）暴露文档自洽性不足。

建议优先处理 🔴 三项 + 🟠 三项，再补 Docker 章节（问题 7）。修正后即可交付，无明显丢分风险。
