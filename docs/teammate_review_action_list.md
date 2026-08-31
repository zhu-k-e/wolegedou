# 队友本子修订清单（可直接粘贴转发）

> 说明：以下每一条都是「你写的 → 实际 → 改法」，带代码证据。本轮（第四轮）已逐条用后端真实源码核实，**并纠正了我之前给你的几处错误数字**（见文末「我之前给你的旧数已更正」）。请队友逐条改完。

---

## 🚨 必改（虚构 / 与代码冲突 / 部署会失败）

### 1. KB 规模 7000 → 34154
- 你写：领域知识库约 7000 chunk
- 实际：`data/numpy_kb/vectors.npy` 实测 `(34154, 1024)`
- 改法：写 **34154**（或"约 3.4 万"）

### 2. 模型档位 DeepSeek-V3 / GPT-4o → qwen-max / deepseek-chat / qwen-turbo
- 你写：MID=DeepSeek-V3、HIGH=GPT-4o
- 实际（`.env.example`）：HIGH=`qwen-max`、MID=`deepseek-chat`、LOW=`qwen-turbo`
- 改法：照 `.env.example` 改

### 3. 降维分级 4 级 → 单阈值 0.85 二分
- 你写：<40 / 40-60 / 60-85 / ≥85 四级
- 实际（`core/orchestrator.py:1254`）：`accuracy < 0.85` 降维，否则进阶（无 60% 档）
- 改法：写"正确率 <85% 降维，≥85% 进阶"

### 4. α 阶梯写反且漏级 → 0.9→0.7(≥50)→0.5(≥100)→0.3(≥200)
- 你写：冷 0.7 / ≥50 则 0.3
- 实际（`memory_service.py:22-26` + `config.py:75`）：冷启动 0.9，4 级阶梯
- 改法：按 4 级写，注明冷启动 0.9

### 5. 反向怀疑阈值 refs≥5/code≥20/steps≥8 → 12/50/20
- 你写：refs≥5 / code≥20 / steps≥8
- 实际（`judge_panel.py:124-126`，2026-08-15 校准）：12 / 50 / 20
- 改法：改 12/50/20，注明校准日期

### 6. API 端点 POST /profile、/ask、GET /status → 全 /api 前缀、无 /profile
- 你写：POST /profile、/ask，GET /status
- 实际（`main.py:98-104`）：`/api/ask`、`/api/status`、`/api/feedback`、`/api/quiz`、`/api/kb`、`/api/report`、`/api/memory`、`/health`；**无 /profile**
- 改法：统一 `/api` 前缀，删 /profile 端点

### 7. learner_id 身份模型 + 第七章 AES-256 合规 → 后端零 learner_id、无加密
- 你写：learner_id 贯穿；《数据使用告知书》、AES-256 加密存储
- 实际：全 backend `grep learner_id` 零匹配（隔离键是 `session_id`）；`grep aes|encrypt` 零匹配（无加密代码）
- 改法：身份模型改 `session_id`；第七章改"按 session_id 隔离 + 30 天过期清理"，删 AES-256 等未实现描述

### 8. BKT 贝叶斯知识追踪 → 后端不存在
- 你写：大段贝叶斯公式 + 表格 P(known) 0.5→0.72
- 实际：`grep BKT|bayesian` 零匹配
- 改法：删 BKT 章节与表格，改述实际画像更新逻辑

### 9. K-Means 聚类标注 learning_style → 后端不存在
- 你写：K-Means K=4
- 实际：`grep KMeans|clustering` 零匹配
- 改法：删 K-Means，改述意图裁决 + 关键词硬映射

### 10. Chroma 唯一向量库 + 10 个 collection → 默认 numpy、Chroma 仅 fallback、无 10 collection
- 你写：Chroma 本地持久化 10 个 collection
- 实际（`kb_manager.py`）：`kb_backend=auto` 先试 numpy（4 件套文件，非 collection）；Chroma 若启用仅 1 个 collection `wolegedou_kb`
- 改法：写"默认 numpy 预计算向量（34154 chunks）；ChromaDB 可选 fallback；无 10 collection 概念"

### 11. 知识库构建 6 步流水线（download_docs→init_chroma→verify_kb）→ 脚本全不存在
- 你写：`python scripts/init_chroma.py --rebuild` 等 6 步
- 实际：`backend/scripts/` 只有 benchmark/validate 脚本，无 init_chroma/verify_kb/build_knowledge_base；Docker 直接 `COPY data/` 烤入向量
- 改法：改真实部署——Docker 构建即含向量；本地放 `data/numpy_kb/` 四件套后启动自动加载

### 12. WebSocket 依赖 socket.io-client → 原生 FastAPI WebSocket，路径 /ws/{task_id}
- 你写：前端依赖 socket.io-client
- 实际（`api/routes/ws.py:17` + `main.py:105` 无 /api 前缀）：原生 WS，路径 `/ws/{task_id}`；`requirements.txt` 只有 `websockets`，无 socket.io
- 改法：依赖改 `websockets`；前端连 `ws://host/ws/{task_id}`

### 13. 启动命令 cd backend && uvicorn main:app → 会失败
- 你写：`cd backend && uvicorn main:app --host 0.0.0.0 --port 8000 --reload`
- 实际（`Dockerfile:42` CMD=`uvicorn backend.main:app`）：`main.py` 用绝对导入 `from backend.xxx`，从 backend/ 内运行找不到 `backend` 包
- 改法：从**项目根目录**运行 `uvicorn backend.main:app --host 0.0.0.0 --port 8000`

### 14. 依赖清单路径+版本错：cd backend && pip install -r requirements.txt + chromadb==0.5.* → 根目录 + 1.5.9
- 你写：`cd backend && pip install -r requirements.txt`，`chromadb==0.5.*`
- 实际：`requirements.txt` 在**项目根**；真实 `chromadb==1.5.9`
- 改法：根目录 `pip install -r requirements.txt`；版本改 1.5.9

---

## ⚠️ 内部矛盾（本子自己打架）
- FSM 状态：文字"10" vs 表格/代码 → 真实枚举 **16 个**（`core/fsm.py`）
- 智能体数：文字"18" vs 表格 19 vs 代码 **11**（`agent_registry.py`）
- 反馈限幅：±0.02 vs ±0.03 → 代码 **±0.02**（`memory_service.py:232`）

---

## 📊 指标回填（别造假）
- 幻觉率 **3.0%** / 适配率 **100%** / 覆盖率 **87.9%**（诚实未达赛题 90%，会扣 5–10 分）
- 本子 5.3.3 写 ≥95% 高于赛题 90% → 改回 ≥90% 并填 87.9%，**严禁填 90%/95%**

---

## 🔧 次要 / 数据口径
- SQLite 表数：你写 9 → 真实 **15 张**（`db/init_db.py` DDL）
- GPU：你写显存≥24GB → 实际 `torch==2.7.1+cpu`，本地部署**无需 GPU**
- 检索 top_k：你写 10/5 → 真实 **3**（`config.py:39`）
- intent 枚举：你写 generate/navigate/clarify → 真实 **generation/navigation/clarification**（`profile_agent.py:97`）
- Python 版本：你写 3.10+ → 真实 **3.13**（`Dockerfile:5`）

---

## ✅ 你写对的地方（别乱改）
bge-m3 1024 维 · 审核权重 0.35/0.35/0.30 · importance 公式 0.5/0.3/0.2 · 30+ 关键词硬映射 · 自进化贡献记忆闭环 · AST 危险调用检测 · FSM 主链 9 态 + 双候选并行 · WS 实时推送设计意图（仅协议/路径错）

---

## 📌 我之前给你的旧数已更正（本轮第四轮源码核实发现）
1. KB：我之前说 30532 → 真实 **34154**（旧 benchmark 日志过期）
2. 降维：我之前说 3 级 <60/60-85 → 真实 **单阈值 0.85 二分**
3. α 阶梯：我之前说 3 级 0.9/0.7/0.3 → 真实 **4 级 0.9/0.7/0.5/0.3**
4. FSM：我之前说 11 态 → 真实 **16 态**
5. 画像缓存（之前标 F3"编造"）：**实际真实存在**，撤销该条
6. requirements.txt（之前标 E6"不存在"）：**实际存在（根目录）**，改为路径/版本错
7. Chroma（之前偏"虚构"）：**是真实 fallback 后端**，改为"非唯一 + 无 10 collection"
