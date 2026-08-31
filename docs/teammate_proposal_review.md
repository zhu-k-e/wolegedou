# 队友本子代码级核查报告（第四轮 · 全程落实源码核实）

> 核查对象：`XH-202630-项目材料文档(2).docx`
> 核查方式：**逐条打开 `backend/` 真实源码 + 实测数据核对**，不再凭记忆。
> 本轮回查发现**前几轮有 6 处我自己的数字写错**，已在「自我纠错」段修正。

---

## 〇、本轮自我纠错（前几轮凭记忆写错，已修正）

| 条目 | 我之前写的（错） | 真实源码/数据 | 证据 |
|---|---|---|---|
| A1 KB 数 | 30532 chunks | **34154 chunks** | `data/numpy_kb/vectors.npy` shape `(34154, 1024)` 实测；`numpy_knowledge_base.py:20` 注释"3.4万规模" |
| A3 降维阈值 | 3 级 <60/60-85/≥85 | **二分 @0.85**（<0.85 降维、≥0.85 进阶） | `core/orchestrator.py:1254` `if accuracy < 0.85` |
| A4 α 阶梯 | 3 级 0.9/0.7/0.3 | **4 级 0.9/0.7/0.5/0.3** | `services/memory_service.py:22-26` `_ALPHA_STAGES=[(200,0.3),(100,0.5),(50,0.7)]` |
| B7 FSM 状态 | 11 态 | **16 态**（主9+异常2+延伸5） | `core/fsm.py:20-43` `FSMState` 枚举共 16 个 |
| E5 Chroma | "Chroma 只是可选 fallback（偏虚构）" | Chroma **是真实实现的 fallback 后端**（`chroma_knowledge_base.py` 存在）；错误在于"唯一向量库"+"10 collection" | `services/rag/kb_manager.py:99` auto 先试 numpy；`chroma_knowledge_base.py` 真实存在 |
| E6 requirements | "requirements.txt 不存在" | **存在（根目录）**；错误在路径 `cd backend &&` + 版本 `chromadb==0.5.*` | `requirements.txt` 实测在根；真实 `chromadb==1.5.9` |
| F3 画像缓存 | "编造、不存在" | **真实存在**（同 session 复用、跳过 LLM、省~3秒） | `agents/profile_agent.py:155-163` |

> 另有新增部署致命项：本子启动命令 `cd backend && uvicorn main:app` 会失败（见条目 13）。

---

## 一、必须改（虚构 / 与代码冲突 / 部署会失败）

### 1. KB 规模：本子 7000 → 真实 **34154** chunk
- 本子（line 88 附近）：领域知识库约 7000 chunk。
- 真实：`data/numpy_kb/vectors.npy` 实测 `(34154, 1024)`；`numpy_knowledge_base.py` 注释"3.4万规模"。
- 改法：改为 **34154**（或表述"约 3.4 万"）。

### 2. 模型档位：本子 MID=DeepSeek-V3 / HIGH=GPT-4o → 真实 MID=deepseek-chat、HIGH=qwen-max、LOW=qwen-turbo
- 真实（`.env.example:10/15/18`）：`DEEPSEEK_MODEL=deepseek-chat`、`OPENAI_MODEL=qwen-max`、`OPENAI_MINI_MODEL=qwen-turbo`。
- 注意：`config.py:23/28/31` 默认是 `deepseek-v4-flash / gpt-4o / gpt-4o-mini`，但部署由 `.env` 覆盖为上述 qwen/deepseek-chat 值。本子"HIGH=GPT-4o"侥幸撞上 config 默认值，却不是实际部署模型。
- 改法：照 `.env.example` 写 qwen-max / deepseek-chat / qwen-turbo。

### 3. 测验降维阈值：本子 4 级（<40/40-60/60-85/≥85）→ 真实 **单阈值 0.85 二分**
- 真实（`core/orchestrator.py:1254`）：`if accuracy < 0.85: 降维 else 进阶`。无 60% 档、无 3 级。
- 改法：改为"答题正确率 < 85% 触发降维解释，≥85% 进阶"。

### 4. α 动态阶梯：本子"冷 0.7 / ≥50 则 0.3" → 真实 **0.9 → 0.7(≥50) → 0.5(≥100) → 0.3(≥200)**
- 真实（`memory_service.py:22-26` + `config.py:75` `alpha_initial=0.9`）：4 级阶梯，冷启动 0.9。
- 改法：按 4 级写，注明冷启动 0.9。

### 5. 反向怀疑阈值：本子 refs≥5 / code≥20 / steps≥8（已废弃）→ 真实 **refs≥12 / code≥50 / steps≥20**
- 真实（`judge_panel.py:124-126`，2026-08-15 校准）：`_RS_REFS_THRESHOLD=12 / _RS_CODE_LINES_THRESHOLD=50 / _RS_STEPS_THRESHOLD=20`。
- 改法：改成 12/50/20，并注明"2026-08-15 校准上调"。

### 6. API 端点：本子 POST /profile、/ask、GET /status → 真实全 `/api` 前缀、无 /profile
- 真实（`main.py:98-104`）：`/api/ask`、`/api/status`、`/api/feedback`、`/api/quiz`、`/api/kb`、`/api/report`、`/api/memory`；`/health`；**无 `/profile` 端点**。
- 改法：统一加 `/api` 前缀；删 /profile 端点描述（画像由 /api/ask 注入或 /api/report 查）。

### 7. learner_id 身份模型 + 第七章合规：本子大量据此编造 → 后端**零 learner_id**
- 真实：`grep -r "learner_id"` 全 backend **零匹配**；隔离键是 `session_id`（无账号层）。
- 因此本子第七章"《数据使用告知书》用户授权流程、AES-256 加密存储、反馈关联 learner_id"在 backend 无对应实现：`grep -ri "aes|encrypt|cryptography"` 全 backend **零匹配**（无加密代码）。
- 改法：身份模型一律改为 `session_id`；第七章合规描述改为"按 session_id 隔离 + 30 天过期清理（`config.py:96` `conversation_retention_days=30`）"，删 AES-256 等未实现描述。

### 8. BKT 贝叶斯知识追踪：本子大段公式 + 表格"P(known) 0.5→0.72" → 后端**不存在**
- 真实：`grep -ri "BKT|bayesian|knowledge_tracing"` 全 backend **零匹配**。
- 改法：删除 BKT 章节与 TABLE 23，改述实际实现的画像更新逻辑（`profile_agent.py` 的 LLM 生成 + 关键词兜底 + 反馈降级）。

### 9. K-Means 聚类：本子"K-Means K=4 标注 learning_style" → 后端**不存在**
- 真实：`grep -ri "KMeans|kmeans|clustering"` 全 backend **零匹配**；`profile_agent.py` 用 LLM 枚举 + 关键词硬映射，无聚类。
- 改法：删除 K-Means 描述，改述实际意图裁决 + 关键词映射（`profile_agent.py:32-66` 的 `_TECH_KEYWORD_MAP`）。

### 10. 向量库描述：本子"Chroma 唯一向量库 + 10 个 collection" → 真实默认 numpy、Chroma 仅 fallback、无 10 collection
- 真实（`kb_manager.py:48` `kb_backend="auto"` → `:99` 先试 numpy；`numpy_knowledge_base.py` 是 4 个文件 `vectors.npy/documents.json/metadatas.json/ids.json`，**非 collection**；Chroma 若启用只有 1 个 collection `wolegedou_kb`，见 `config.py:42`）。
- 改法：改为"默认 numpy 预计算向量（4 件套、34154 chunks）；ChromaDB 为可选 fallback；无'10 个 collection'概念"。

### 11. 知识库构建 6 步流水线：本子 `download_docs.py→…→init_chroma.py→verify_kb.py` → 仓库**一个都不存在**
- 真实：`ls backend/scripts/` 只有 benchmark/validate/coverage 类脚本；`init_chroma.py`、`verify_kb.py`、`build_knowledge_base.py` 等均不存在。Docker 部署是 `Dockerfile:32` 直接 `COPY data/` 烤入向量，`docker-entrypoint.sh` 合并分卷，**无需运行时构建**。
- 后果：评委按本子 4.2.3 跑第一步即 `FileNotFoundError`，系统搭不起来。
- 改法：改为真实部署方式——（a）Docker：`docker build` 后 `COPY data/` 已含向量；（b）本地：下载 `data/numpy_kb/` 四件套放到 `KB_NUMPY_DIR`，启动自动加载（`kb_manager.py:126-144`）。

### 12. WebSocket：本子依赖 `socket.io-client` → 后端是**原生 FastAPI WebSocket**，路径 `/ws/{task_id}`
- 真实（`api/routes/ws.py:17` `@router.websocket("/ws/{task_id}")`；`main.py:105` 注册 ws 路由**无 /api 前缀**）；`requirements.txt:13` 只有 `websockets==16.1`，**无 socket.io 依赖**。
- 后果：前端用 socket.io-client 握手必然失败（你们前端联调早已踩过此坑）。
- 改法：依赖改 `websockets`（原生）；前端用浏览器/标准 WS 客户端连 `ws://host/ws/{task_id}`。

### 13. 启动命令：本子 `cd backend && uvicorn main:app` → **会失败**
- 真实：`main.py` 用绝对导入 `from backend.config import ...`；`Dockerfile:42` CMD=`uvicorn backend.main:app --host 0.0.0.0 --port 8000`。从 `backend/` 内运行 `uvicorn main:app` 会因找不到 `backend` 包而 `ModuleNotFoundError`。
- 改法：从**项目根目录**运行 `uvicorn backend.main:app --host 0.0.0.0 --port 8000`（或 `python -m backend.main`）。

### 14. 依赖清单：本子 `cd backend && pip install -r requirements.txt` + `chromadb==0.5.*` → 路径错 + 版本错
- 真实：`requirements.txt` 在**项目根**（不在 backend/）；真实 `chromadb==1.5.9`（`requirements.txt:24`）。
- 改法：从根目录 `pip install -r requirements.txt`；版本改 1.5.9（或删具体版本号，跟仓库）。

---

## 二、内部矛盾（本子自己打架）

- **FSM 状态数**：文字"10" vs 表格/代码。真实枚举 **16 个**（`fsm.py`）。本子两处都错。
- **智能体数**：文字"18" vs 表格加总 19 vs 代码 **11**（`agent_registry.py` 8-87，`agent_001`–`agent_011`）。
- **反馈限幅**：±0.02 vs ±0.03。真实代码 `memory_service.py:232` 是 **±0.02**，±0.03 那处错。

---

## 三、指标必须如实回填（竞赛铁律：低可接受、假不行）

- 本子第五章多为「【待实测】」。真实硬化实测值：**幻觉率 3.0% / 适配率 100% / 覆盖率 87.9%**（覆盖率诚实未达赛题 90%，会扣 5–10 分）。
- 本子 5.3.3 把覆盖率目标写 ≥95%，高于赛题 90%——建议改回 ≥90% 并填 **87.9%**，**严禁填 90%/95% 造假**。
- 来源：`scripts/validate_metrics.py` 跑 `data/metrics_llm_judge_cache.json` 全量真值比对。

---

## 四、次要 / 数据口径（建议同步）

- **SQLite 表数**：本子"9 张"→ 真实 `init_db.py` DDL 共 **15 张**（agent_cards/agent_performance/contribution_memory/student_feedback/system_config/student_profiles/elimination_log/offline_evaluation_queue/human_review_queue/demo_cache/session/conversations/task_resource_stats/task_metrics/task_resources）。注：代码注释自己写"13张/12张"也不准。
- **GPU 要求**：本子"显存 ≥24GB（RTX4090/A100）"过度。`requirements.txt:27` `torch==2.7.1+cpu`，numpy 检索纯 CPU；向量已预计算，无运行时 bge-m3 推理。**本地部署无需 GPU**。
- **检索 top_k**：本子写 10/5 → 真实 `config.py:39` `kb_top_k=3`。
- **intent 枚举**：本子缩写 generate/navigate/clarify → 真实 `profile_agent.py:97` `generation/navigation/clarification`。
- **Python 版本**：本子"3.10+" → 真实 `Dockerfile:5` `python:3.13-slim`、`requirements.txt:4` 注明强依赖 3.13（bge-m3/FlagEmbedding）。
- **verification_rate 0.96**：是本子示例/实测值，非硬编码默认；系统按"已验证条数/总声明数"实时算（`judge_panel.py:215/287`）。勿当代码常量。
- **审核 verdict 阈值**：本子"0.80/0.60"在 `review_team.py` 中无对应；真实通过阈值在 `judge_panel.py`：快速通道 `overall_rate≥0.9` 通过、严格模式 `<0.8` 降级（无 0.6）。

---

## 五、本子写对的地方（不误报，队友别乱改）

- bge-m3 1024 维（`config.py:38` `BAAI/bge-m3`、`numpy_knowledge_base.py:4` `(N,1024)`）✓
- 审核权重 0.35/0.35/0.30（`init_db.py:318` 种子值）✓
- importance_score 公式 `0.5*acc + 0.3*(1-rework) + 0.2*归一化频数`（`memory_service.py:115-119`，本子 line 284 一致）✓
- 30+ 关键词硬映射表（`profile_agent.py:32-66` `_TECH_KEYWORD_MAP`）✓
- 自进化贡献记忆闭环（`memory_service.py` `record_task_completion` + `contribution_memory` 表）✓
- AST/危险调用代码检测（`services/code_checker.py`）✓
- FSM 主链 9 态 + 2 候选并行（`orchestrator.py` `asyncio.gather` 双候选）✓
- WebSocket 实时推送 FSM 状态的设计意图（只是协议/路径写错）✓

---

## 附录：本轮回查真实源码位置
`backend/config.py` · `core/fsm.py` · `core/orchestrator.py` · `services/memory_service.py` · `services/rag/kb_manager.py` · `services/rag/numpy_knowledge_base.py` · `agents/judge_panel.py` · `agents/profile_agent.py` · `agents/agent_registry.py` · `agents/review_team.py` · `db/init_db.py` · `main.py` · `api/routes/ws.py` · `.env.example` · `requirements.txt` · `Dockerfile` · `data/numpy_kb/vectors.npy`（实测 shape）。
