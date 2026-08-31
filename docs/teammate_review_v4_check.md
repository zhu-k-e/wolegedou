# 队友本子 v4.0 复核报告（代码级，逐条坐实）

> 复核日期：2026-08-19
> 方法：逐条打开 `backend/` 真实源码 + 实测数据核对，不凭记忆。
> 配套：本文件是 v4.0 的"通过/未过"清单；旧版详细底稿见 `teammate_proposal_review.md`，可粘贴修订清单见 `teammate_review_action_list.md`。

---

## 一、✅ 这一轮已正确修正（队友听进去了，共 14 项）

| # | 本子现在的写法 | 代码核实 |
|---|---|---|
| 1 | 身份模型改用 `session_id`，第七章删掉"用户授权流程 / AES-256 加密" | backend 全仓零 `learner_id`/`user_id`/`account_id`，零 `aes`/`encrypt`（grep 确认）✅ |
| 2 | 删除 BKT 贝叶斯追踪、K-Means 聚类章节 | 全仓零 `BKT`/`KMeans`/`bayesian`/`clustering`（之前是虚构）✅ |
| 3 | 模型档位 LOW=qwen-turbo / MID=deepseek-chat / HIGH=qwen-max | `.env.example` 与 4.2.4 环境变量一致✅ |
| 4 | 反向怀疑阈值 refs≥12 / code≥50 / steps≥20 | `judge_panel.py` 常量一致✅ |
| 5 | Agent 知识源"统一 numpy_kb，无 source 字段" | `agent_registry.py` Agent 卡片确无 source 字段✅ |
| 6 | 知识库"预计算，无需构建流水线"（3 步） | `kb_manager.py` 默认 `auto` 优先 numpy；无 `download_docs.py` 等脚本✅ |
| 7 | intent 枚举 generation/navigation/clarification | `profile_agent.py` 一致✅ |
| 8 | 覆盖率 87.9% 诚实披露，目标 ≥90% | 实测值一致，未造假✅ |
| 9 | SQLite 15 张表 | `db/init_db.py` DDL 实测 15 表✅ |
| 10 | 删除 socket.io，改"FastAPI 原生 WebSocket" | `api/routes/ws.py` 是原生 WebSocket✅（但**路径仍错**，见下方 #3） |
| 11 | RAG 伪代码 top_k=3 | `numpy_knowledge_base.py` 默认 `top_k: int = 3`✅ |
| 12 | importance_score = 0.5×acc + 0.3×(1-rework) + 0.2×count | `memory_service.py:115-119` 一字不差✅ |
| 13 | 架构图"POST /api/ask（profile 字段）、无 /profile 端点" | `ask.py:32` `/ask` + `ask.py:76` 读 `request.profile`；无 `/profile`✅ |
| 14 | 隐私章节"无账号层、session_id 隔离、最小化采集" | 与代码一致✅ |

---

## 二、🔴 仍须修改（9 项，含代码证据 + 改法）

### 1. KB chunk 数 30532 → 真实 **34154**（A1，未改）
- 出现位置：2.2 架构图、4.1 技术栈、4.2.3、5.1.2、4.2.5 健康检查示例
- 证据：实测 `data/numpy_kb/vectors.npy` → `shape=(34154, 1024)`
- 改法：全文 30532 → 34154；4.2.5 健康检查预期 `kb_chunks` 也改为 34154

### 2. 启动命令 `cd backend && uvicorn main:app` 必失败（部署致命，未改）
- 位置：4.2.4 第 3 步
- 证据：`main.py:13-17` 用绝对导入 `from backend.config / backend.api.routes ...`；`main.py:132` `__main__` 用 `uvicorn.run("backend.main:app")`；`Dockerfile` 也是 `uvicorn backend.main:app`
- 改法：删掉 `cd backend`，改为**从项目根目录**执行 `uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload`

### 3. WebSocket 路径 `/api/ws/{task_id}` → 真实 `/ws/{task_id}`（F1 路径，未改）
- 位置：2.2 架构图、4.1 技术栈（协议已改对，但路径带错 `/api` 前缀）
- 证据：`ws.py:17` `@router.websocket("/ws/{task_id}")`；`main.py:105` `include_router(ws.router, tags=["WebSocket"])` **无 prefix**
- 改法：两处 `/api/ws/{task_id}` → `/ws/{task_id}`。**否则前端（队友经 cloudflared 联调）连 WS 会 404**

### 4. requirements.txt 描述与事实相反（E6，未改，且更错）
- 位置：4.2.2 "核心清单，实际由环境管理，**无 requirements.txt 文件**" + `cd backend && pip install ...`
- 证据：根目录**真实存在** `requirements.txt`（1713 字节，含 `chromadb==1.5.9`、`websockets==16.1`、`torch==2.7.1+cpu`、要求 Python 3.13）
- 改法：改为"项目根目录已提供 `requirements.txt`"，安装命令改为**从根目录** `pip install -r requirements.txt`（不要在 `cd backend` 后找）

### 5. α 阶梯漏掉 0.5 档（A4，未改完）
- 位置：2.3.4（写了 3 级：<50→0.9 / ≥50→0.7 / ≥200→0.3）
- 证据：`memory_service.py:22-26` `_ALPHA_STAGES = [(200,0.3),(100,0.5),(50,0.7)]`，默认 0.9 → **实际 4 级，多一个 ≥100→0.5**
- 改法：补一行"充分积累期（记忆条数 ≥100）：α = 0.5"

### 6. FSM 状态数 11 → 真实 **16**（B7，未改）
- 位置：2.2 表头"共定义 11 个状态（主链 9 态 + 延伸 REVISING / ERROR）"、附录 A 动画"FSM 11 状态"
- 证据：`fsm.py:24-43` 枚举 16 个：主 9（IDLE/PROFILING/DISPATCHING/GENERATING/REVIEWING/FOCUSING/JUDGING/FORMATTING/COMPLETE）+ 异常 2（REVISING/ERROR）+ 延伸 5（QUIZ_EVAL/REDIMENSION/ADVANCE/RECHECK/HEURISTIC_FOLLOWUP）
- 改法：2.2 表头与附录 A 改为"16 个状态（主链 9 + 异常 2 + 延伸 5）"

### 7. 降维阈值编造"轻度降维 60~85%"中档（A3，未改）
- 位置：3.3.1、3.3.2（<60% 降维 / 60~85% 轻度降维 / ≥85% 进阶）
- 证据：`orchestrator.py:1254` `if accuracy < 0.85: redimension else: advance` —— **二分，无 60% 边界、无"轻度降维"中档**
- 改法：删除"轻度降维 60~85%"这一档，改为"正确率 <85% → 降维解释；≥85% → 进阶挑战"

### 8. 知识库验证命令 `curl /api/kb/stats` → 真实 `GET /api/kb/health`（G1，新发现）
- 位置：4.2.3 第 3 步
- 证据：`kb.py:62` `@router.get("/kb/health")`；全文件无 `/kb/stats` 路由
- 改法：`curl http://localhost:8000/api/kb/health`

### 9. 审核 verdict 阈值 0.80/0.60 在代码里无对应分支（E7，待对齐）
- 位置：2.3.3（通过 ≥0.80 / 0.60~0.80 有条件 / <0.60 不通过）
- 证据：`review_team.py:247` 取 `review_weights`(0.35/0.35/0.30 真实)，`review_team.py:261` 算 `composite = v*w1+s*w2+e*w3`，`review_team.py:292` **直接取 composite 最高分为 winner**，无独立 pass/conditional/fail 阈值分支（本子自己已注"待对齐"）
- 改法：把 verdict 描述改为"三段加权 composite 排序选优，得分最高者胜出"，删掉 0.80/0.60 阈值；或补实现该阈值逻辑

---

## 三、🟡 概念/措辞（可接受，建议微调）

- **"19 个协作单元（11 agent_cards + 8 编排角色）"**：11 个 `agent_cards` 真实（agent_001–011 = 10 领域 + 1 资源格式化）；8 编排角色 = Analyzer+Matcher+Verifier+Skeptic+Evaluator+3 Judge 是概念计数（评审/裁判/Analyzer/Matcher 不在 agent_cards 表）。doc 已分清"卡片 vs 角色"，可接受。
- **4.2.5 健康检查示例 JSON**：字段（fsm_state/kb_chunks/sqlite/model reachability）属示意，真实 `GET /api/status/{task_id}` 返回 task state + result；如填 `kb_chunks` 应写 34154。建议标注"示例"。

---

## 四、优先级提示（转给队友）

- **最高优先（不改系统跑不起来 / 评委一核就露馅）**：#2 启动命令、#3 WS 路径、#4 requirements、#8 kb/stats（4 条部署类，任一错都会让评委按本子搭环境失败）；#1 KB 34154（数字会穿帮）。
- **次优先（架构描述与代码不符）**：#5 α 0.5 档、#6 FSM 16 态、#7 降维二分、#9 审核 verdict。
- 第 14 项（覆盖率 87.9% 诚实）继续保持，严禁改成 90%+ 造假。
