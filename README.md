# 领域知识个性化生成与多智能体协同决策系统

**挑战杯揭榜挂帅 XH-202630 参赛项目**

---

## 项目简介

面向垂直领域技能培训场景，构建**多 Agent 协同决策系统**，实现：

- **学情诊断**：分析学习者知识盲区与能力等级，生成个性化画像
- **个性化知识生成**：基于多 Agent 候选生成 + 交叉审核 + 裁判裁决，动态生成高质量学习资源
- **防幻觉机制**：审核团队事实核查 + 裁判团辩论仲裁，多层级防控大模型幻觉
- **贡献记忆闭环**：EMA 评分 + 返工率追踪 + 动态淘汰，持续优化 Agent 池

---

## 技术栈

| 组件 | 技术 | 用途 |
|------|------|------|
| Web 框架 | FastAPI + uvicorn | 异步后端 API，适合多 LLM 调用编排 |
| LLM 调用 | OpenAI SDK（兼容协议） | 接入 DeepSeek / 通义千问等国内模型 |
| 数据校验 | Pydantic v2 | 请求/响应模型校验 + LLM 输出 Schema 约束 |
| 数据库 | SQLite（内置） | Agent 卡片、学情画像、贡献记忆等持久化 |
| 实时推送 | WebSocket | FSM 状态变更实时推送给前端 |
| 日志 | loguru | Agent 链路调试追踪 |
| 测试 | pytest | 单元测试（FSM 状态机 / JSON 三层兜底 / Schema 校验） |
| Python | 3.13 | 统一技术栈 |

---

## 模型分层

| 档位 | 模型（当前配置） | 用途 | 对应方案书 |
|------|-----------------|------|-----------|
| 中档 | DeepSeek-V3（deepseek-chat） | 候选生成 / 审核团队 / 资源生成 | §8.5 |
| 高档 | 通义千问 qwen-max | 聚焦输出 / 裁判团裁决 | §8.5 |
| 低档 | 通义千问 qwen-turbo | 轻量判断（意图裁决等） | §8.5 |

> 代码使用 OpenAI 兼容协议，换模型只需改 `.env` 不改代码。GPT-4o 不可用时可降级为 DeepSeek-V3（聚焦输出 + 加严审核）。

---

## 项目结构

```text
wolegedou/
├── README.md                       # 项目说明（本文件）
├── requirements.txt                # Python 依赖
├── .env.example                    # 环境变量模板（复制为 .env 使用）
├── .gitignore
│
├── backend/                        # 后端主目录
│   ├── main.py                     # FastAPI 应用入口
│   ├── config.py                   # 全局配置（读取 .env）
│   │
│   ├── api/                        # API 路由层
│   │   ├── schemas.py              # 请求/响应 Pydantic 模型
│   │   └── routes/                 # 5 个路由模块
│   │       ├── ask.py              # POST /api/ask        学生提问（主流程入口）
│   │       ├── status.py           # GET  /api/status/{task_id}  任务状态查询
│   │       ├── feedback.py         # POST /api/feedback    学生反馈
│   │       ├── quiz.py             # POST /api/quiz_submit 答题提交
│   │       └── ws.py               # WS   /ws/{task_id}    实时状态推送
│   │
│   ├── core/                       # 核心编排层
│   │   ├── fsm.py                  # FSM 状态机定义（14 个状态 + 转移规则）
│   │   ├── orchestrator.py         # 编排器（FSM 驱动多 Agent 协同主循环）
│   │   └── exceptions.py           # 自定义异常
│   │
│   ├── agents/                     # 多 Agent 模块
│   │   ├── base_agent.py           # Agent 基类（统一 LLM 调用 + JSON 三层兜底）
│   │   ├── agent_registry.py       # 11 个 Agent 卡片静态注册
│   │   ├── profile_agent.py        # 学情诊断 Agent（画像生成 + 三步调度 + 启发式追问）
│   │   ├── matcher.py              # 调度员（标签匹配 + 综合遴选 + 早停机制）
│   │   ├── domain_agent.py         # 领域 Agent（候选生成 + 自评估 + 辩论）
│   │   ├── review_team.py          # 审核团队（Verifier / Skeptic / Evaluator）
│   │   ├── judge_panel.py          # 裁判团（Supporter / Challenger / Judge + 分歧解决）
│   │   └── resource_agent.py       # 资源生成 Agent（讲义 / 实操 / 测试题 + 降维/进阶）
│   │
│   ├── schemas/                    # Pydantic 数据模型
│   │   ├── student_profile.py      # 学情画像
│   │   ├── candidate_output.py     # 候选输出
│   │   ├── review_feedback.py      # 审核反馈
│   │   ├── focused_output.py       # 聚焦输出
│   │   ├── judge_verdict.py        # 裁判裁决
│   │   └── resource_package.py     # 资源包
│   │
│   ├── services/                   # 服务层
│   │   ├── llm_client.py           # LLM 客户端（分层模型调用）
│   │   ├── json_validator.py       # JSON 三层兜底校验器
│   │   ├── memory_service.py       # 贡献记忆服务（EMA / 淘汰 / 反馈）
│   │   ├── knowledge_base.py       # 知识库接口（RAG 检索，等队友文档接入）
│   │   └── ws_manager.py           # WebSocket 连接管理
│   │
│   ├── db/                         # 数据库层
│   │   ├── database.py             # SQLite 连接管理
│   │   ├── init_db.py              # 建表 + 种子数据
│   │   └── repositories/           # 数据访问层
│   │       ├── agent_repo.py       # Agent 卡片 + 性能记录
│   │       ├── config_repo.py      # 系统配置 + 快照
│   │       ├── memory_repo.py      # 贡献记忆
│   │       └── profile_repo.py     # 学情画像
│   │
│   └── tests/                      # 单元测试
│       ├── test_fsm.py             # FSM 状态转移测试
│       ├── test_json_validator.py  # JSON 三层兜底测试
│       └── test_schemas.py         # Schema 校验测试
│
├── data/                           # 运行数据
│   └── wolegedou.db                # SQLite 数据库（自动创建）
│
└── docs/                           # 比赛方案文档
    ├── proposal.md                 # 方案书 v7.0 终版
    ├── proposal_techspec.md        # 技术规格书
    ├── feasibility_report.md       # 可行性报告
    └── ...                         # 其他论证文档
```

---

## 快速开始

### 1. 安装依赖

```bash
python -m venv .venv
.venv/Scripts/activate          # Windows
# source .venv/bin/activate      # macOS/Linux
pip install -r requirements.txt
```

### 2. 配置 API Key

复制 `.env.example` 为 `.env`，填入你的 API Key：

```bash
cp .env.example .env
```

编辑 `.env`，至少配置中档模型（DeepSeek）：

```env
# 中档模型（必填）— 候选生成 / 审核 / 资源生成
DEEPSEEK_API_KEY=sk-your-deepseek-key
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_MODEL=deepseek-chat

# 高档模型（必填）— 聚焦输出 / 裁判团裁决
# 可用通义千问替代 GPT-4o，只需改 base_url 和 model
OPENAI_API_KEY=sk-your-key
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENAI_MODEL=qwen-max
OPENAI_MINI_MODEL=qwen-turbo
```

> **换模型不用改代码**：代码用 OpenAI 兼容协议，只要服务商支持 `/v1/chat/completions` 接口，改 `.env` 即可切换。

### 3. 启动服务

```bash
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

启动后：
- 首页：http://localhost:8000
- 健康检查：http://localhost:8000/health
- **Swagger 文档**：http://localhost:8000/docs
- WebSocket：ws://localhost:8000/ws/{task_id}

### 4. 运行测试

```bash
python -m pytest backend/tests/ -v
```

---

## 多 Agent 协同流程

系统通过 **FSM 状态机**驱动多 Agent 协同，主流程 9 个状态 + 延伸路径 5 个状态：

```
学生提问
    │
    ▼
┌──────────────┐
│  PROFILING   │  学情诊断Agent → 生成学情画像（知识等级/盲区/意图）
└──────┬───────┘
       ▼
┌──────────────┐
│ DISPATCHING  │  调度员 → 三步调度（意图裁决→领域解析→候选遴选）+ 早停
└──────┬───────┘
       ▼
┌──────────────┐
│  GENERATING  │  领域Agent候选生成（每段2个Agent并行）+ 双低触发RAG增强
└──────┬───────┘
       ▼
┌──────────────┐
│  REVIEWING   │  审核团队3角色 → Verifier事实核查 / Skeptic检查清单 / Evaluator四维度
└──────┬───────┘
       ▼
┌──────────────┐
│   FOCUSING   │  聚焦输出Agent → 多候选融合 + JSON三层兜底校验
└──────┬───────┘
       ▼
┌──────────────┐
│   JUDGING    │  裁判团3角色 → Supporter / Challenger / Judge
│              │  分歧时：少数方举证→多数方回应→裁判长裁决 + 候选Agent辩论
└──────┬───────┘
       │ 通过
       ▼
┌──────────────┐
│  FORMATTING  │  资源生成Agent → 讲义 / 实操指南 / 分阶测试题
└──────┬───────┘
       ▼
┌──────────────┐
│   COMPLETE   │  贡献记忆写入（EMA评分 + 返工率 + importance更新）
└──────┬───────┘
       │ 延伸路径（学生答题/反馈触发）
       ▼
┌──────────────────────────────────────────┐
│ QUIZ_EVAL → REDIMENSION（降维解释）        │  正确率<85%
│           → ADVANCE（进阶挑战）            │  正确率≥85%
│           → RECHECK（审核复检）            │  反馈内容有误
│           → HEURISTIC_FOLLOWUP（启发式追问）│  动态追问导学
└──────────────────────────────────────────┘
```

---

## API 接口

### 1. 学生提问（主流程）

```http
POST /api/ask
```

```json
{
  "question": "什么是注意力机制？",
  "session_id": "session_001",
  "history": []
}
```

响应：

```json
{
  "task_id": "task_xxx",
  "session_id": "session_001",
  "profile": { "knowledge_level": "入门", ... },
  "resource_package": { "lecture": {...}, "practice": {...}, "quiz": [...] },
  "judge_verdict": { "verdict": "passed", ... },
  "dispatch_info": { "segments": [...], "agents": [...] }
}
```

### 2. 查询任务状态

```http
GET /api/status/{task_id}
```

### 3. 学生反馈

```http
POST /api/feedback
```

反馈类型：`helpful` / `not_helpful` / `content_error` / `difficulty_mismatch`

### 4. 答题提交

```http
POST /api/quiz_submit
```

根据正确率自动触发降维（<85%）或进阶（≥85%）。

### 5. WebSocket 实时推送

```text
WS /ws/{task_id}
```

FSM 每次状态变更推送：

```json
{
  "type": "fsm_state",
  "task_id": "task_xxx",
  "state": "PROFILING",
  "data": { ... }
}
```

---

## Agent 池（11 个）

| ID | Agent 名称 | 主要功能 |
|----|-----------|---------|
| agent_001 | LLM 基础 Agent | LLM 原理与概念（Token / Embedding / 注意力机制） |
| agent_002 | Prompt 工程 Agent | Prompt 设计与优化（Few-shot / CoT / 模板设计） |
| agent_003 | LangChain 组件 Agent | LangChain 组件开发（Chain / Tool / Memory） |
| agent_004 | RAG 架构 Agent | RAG 系统搭建（文档切分 / 向量检索） |
| agent_005 | Agent 框架 Agent | LLM Agent 开发（ReAct / Function Calling） |
| agent_006 | HuggingFace 调用 Agent | HF 模型使用（模型加载 / Pipeline / 推理部署） |
| agent_007 | 模型微调 Agent | 模型微调训练（LoRA / QLoRA / 数据集准备） |
| agent_008 | 向量数据库 Agent | 向量存储与检索（Chroma / FAISS / 索引优化） |
| agent_009 | 项目实战 Agent | 项目架构与落地（需求分析 / 技术选型 / 部署） |
| agent_010 | 代码调试 Agent | 代码排错与修复（报错分析 / 依赖冲突） |
| agent_011 | 资源生成 Agent | 多形态资源生成（讲义 / 实操指南 / 分阶测试题） |

---

## 数据库

SQLite 数据库位于 `data/wolegedou.db`，共 9 张表：

| 表名 | 用途 |
|------|------|
| agent_cards | 11 个 Agent 卡片静态信息 |
| agent_performance | Agent 动态表现（accuracy / count / rework_rate / importance / is_suspended） |
| contribution_memory | 贡献记忆记录（裁判裁决后写入） |
| student_profiles | 学情画像历史（按 session_id + version） |
| student_feedback | 学生反馈记录 |
| system_config | 系统配置（alpha / ema_smooth / 权重等） |
| elimination_log | Agent 淘汰日志 |
| offline_evaluation_queue | 离线评测队列 |
| human_review_queue | 人工复核队列 |

数据库在首次启动时自动建表并写入种子数据（11 个 Agent 卡片 + 系统配置初始值）。

---

## 核心机制

### 1. FSM 状态机编排

主流程 9 个状态 + 延伸路径 5 个状态，状态转移有严格规则约束（见 `core/fsm.py`）。编排器按状态顺序驱动各 Agent 协同，异常时进入 `ERROR` 或 `REVISING` 状态。

### 2. JSON 三层兜底校验

LLM 输出可能格式不规范，系统通过三层兜底确保解析成功：

1. **第一层**：直接 JSON 解析 + Pydantic 校验
2. **第二层**：正则提取（从 markdown 代码块 / 嵌套文本中提取 JSON）+ 字段类型修复
3. **第三层**：调 LLM 修复格式（把原始输出 + Schema 描述发给 LLM 让它重写）

### 3. 贡献记忆闭环

每次任务完成后，系统记录每个参与 Agent 的贡献：

- **EMA 评分**：指数移动平均，追踪 Agent 历史表现
- **返工率**：被裁判退回的比例
- **importance 权重**：综合 EMA + 返工率，影响后续调度权重（冷启动期 count<5 时固定 0.5）
- **动态淘汰**：importance 连续低于阈值 → 暂停该 Agent
- **学生反馈**：helpful / not_helpful 微调 accuracy

### 4. 防幻觉机制

- **审核团队**：Verifier 事实核查 + Skeptic 检查清单自算分 + Evaluator 四维度评估
- **裁判团**：Supporter 支持 + Challenger 反向怀疑 + Judge 裁决
- **分歧解决**：少数方举证 → 多数方回应 → 僵持裁判长裁决 + 候选 Agent 辩论

---

## 当前状态

### 已完成

- [x] 方案书 v7.0 终版
- [x] FSM 状态机编排器（主流程 + 延伸路径）
- [x] 11 个 Agent 注册池 + 差异化 prompt
- [x] 学情诊断 Agent（画像生成 + 三步调度）
- [x] 审核团队 3 角色（Verifier / Skeptic / Evaluator）+ 跨段审查
- [x] 裁判团 3 角色（Supporter / Challenger / Judge）+ 完整分歧解决
- [x] 聚焦输出 Agent + JSON 三层兜底校验
- [x] 资源生成 Agent（讲义 / 实操 / 测试题 + 降维 / 进阶）
- [x] 贡献记忆闭环（EMA / 淘汰 / 学生反馈）
- [x] 延伸闭环（降维 / 进阶 / 复检 / 追问）
- [x] 候选自评估双低触发 RAG 增强
- [x] 调度早停机制
- [x] FastAPI 后端 + 5 个 API 路由 + WebSocket
- [x] 单元测试（26 个，全部通过）
- [x] DeepSeek + 通义千问 API 验证通过

### 待完成

- [ ] 知识库 RAG 实际文档入库（等知识库团队提供领域文档）
- [ ] 前端界面（前端团队负责）
- [ ] 端到端集成测试
- [ ] 部署上线

---

## 团队分工

| 角色 | 负责模块 |
|------|----------|
| 后端 | `backend/` 全部（Agent / 编排器 / API / 数据库 / 服务） |
| 知识库 | 领域文档准备 + RAG 入库（接入 `backend/services/knowledge_base.py`） |
| 前端 | Web 界面（调后端 API + WebSocket） |

---

## License

MIT
