# 前端对接指南（XH-202630 后端 API）

> 适用对象：负责前端体验（赛题"用户体验 15 分"）的同学
> 后端技术栈：FastAPI + Pydantic，所有业务接口返回 `application/json`
> 文档基准：`backend/main.py`、`backend/api/routes/*`、`backend/api/schemas.py`、`backend/schemas/resource_package.py`

---

## 0. 概览与约定

| 项 | 说明 |
|---|---|
| **Base URL** | 联调期由 Cloudflare 临时隧道域名决定（每次重启会换域名，见 §9）；本地自测为 `http://localhost:8000` |
| **HTTP 前缀** | 所有业务接口统一以 `/api` 开头：`/api/ask`、`/api/status`、`/api/report`、`/api/quiz_submit`、`/api/feedback`、`/api/kb/*` |
| **WebSocket 前缀** | **注意：`/ws/{task_id}` 没有 `/api` 前缀**（与 HTTP 不同，见 §2.3） |
| **交互式文档** | 后端启动后访问 `GET /docs` 即 Swagger UI，可直接试所有接口 |
| **健康检查** | `GET /health` → `{"status":"ok"}`；`GET /` → 服务元信息 |
| **CORS** | 开发态默认放行所有来源（`allow_origins=["*"]`）；生产由 `.env` 的 `CORS_ORIGINS` 收紧为前端域名白名单 |
| **认证** | 默认**关闭**（`.env` 的 `api_key` 为空）。开启后：HTTP 在请求头带 `X-API-Key`，WebSocket 在连接时带 `?api_key=` 查询参数或 `X-API-Key` 头 |
| **AI 内容标注** | 所有含 AI 生成内容的响应都带 `disclaimer` 字段（合规要求），前端建议原样展示在结果区 |

---

## 1. 两个必须分清的 ID

| 字段 | 含义 | 生命周期 | 怎么来 |
|---|---|---|---|
| **`session_id`** | 一次"学习会话"（同一个学生的连续学习过程） | 跨多次提问存在 | **前端自己生成并维护**（建议 UUID），每次请求带上 |
| **`task_id`** | 单次"提问任务" | 一次提问对应一个 | `POST /api/ask` 或 `POST /api/tasks` 的返回值 |

- **报告接口按 `session_id` 聚合**整个会话的学情，所以前端务必**持久化并复用同一个 session_id**。
- 典型流程：前端首次进入 → 生成 `session_id` → 之后所有 `/api/ask`、`/api/report`、`/api/quiz_submit`、`/api/feedback` 都带它。

---

## 2. 主流程：提问 → 进度 → 结果

后端 FSM 流水线状态枚举（进度展示用）：

```
PROFILING → DISPATCHING → GENERATING → REVIEWING
→ FOCUSING → JUDGING → FORMATTING → COMPLETE
```

另有 `PENDING`（已提交未开始）、`UNKNOWN`（查不到）。状态字符串即上述大写值。

### 2.1 `POST /api/ask`（同步，推荐联调用）

一步到位：提交问题，等后端跑完整条流水线后**直接返回最终结果**（含讲义/测验/裁判结论）。

**请求体**
```json
{
  "question": "什么是RAG检索增强生成？",
  "session_id": "sess_abc123",
  "history": null,
  "profile": null
}
```
| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `question` | string(≤4000) | 是 | 学生问题 |
| `session_id` | string | 是 | 见 §1 |
| `history` | list[dict] \| null | 否 | 同会话历史对话；首次留 `null` |
| `profile` | dict \| null | 否 | 可选学情画像（学历/测试结果等）。传入则跳过自动诊断直接生成；字段非法会自动降级为自动诊断 |

**响应**（`AskResponse`，要点字段）
```json
{
  "task_id": "task_xxx",
  "session_id": "sess_abc123",
  "profile": { "knowledge_level": "ENTRY", "domain_confidence": {}, "domain_hint": [], "test_results": [] },
  "resource_package": { /* 见 §6，核心渲染对象 */ },
  "judge_verdict": { "verdict": "passed", "overall_verification_rate": 0.92, "traceability": [...] },
  "dispatch_info": { "domains": ["RAG"], "agents": [...] },
  "navigation_roadmap": "建议先掌握向量检索基础…",
  "clarification_options": ["想了解向量数据库选型？", "需要RAG落地代码？"],
  "error": null,
  "disclaimer": "⚠️ 以上内容由 AI 生成，仅供参考…",
  "from_cache": false
}
```
- 同步接口在免费隧道下可能因 >100s 超时断连；联调若遇到，改用下面的异步方案。

### 2.2 异步方案：`POST /api/tasks` + 轮询 `GET /api/status/{task_id}`

**提交**
```
POST /api/tasks
{ "question": "...", "session_id": "sess_abc123", "history": null, "profile": null }
→ 200 { "task_id": "task_xxx", "status": "PENDING" }
```

**轮询状态**
```
GET /api/status/task_xxx
→ {
     "task_id": "task_xxx",
     "state": "FOCUSING",            // FSM 状态字符串，见上
     "data": { ... },                // 当前阶段的中间数据（可选）
     "result": null                  // 未完成时为 null；COMPLETE 后与 /api/ask 返回结构一致
   }
```
- 轮询到 `state == "COMPLETE"` 时，`result` 即为完整结果（同 §2.1 响应里的 `resource_package` 等）。
- 建议轮询间隔 1–2s；也可改用 WebSocket（见下）实时推送，二选一即可。

### 2.3 `WS /ws/{task_id}`（实时进度，路径**无 `/api` 前缀**）

```
ws://<BASE>/ws/task_xxx
```
连接后，后端每次 FSM 状态切换会主动推送：
```json
{ "type": "fsm_state", "task_id": "task_xxx", "state": "PROFILING", "data": { "profile": {...} } }
```
- **路径是 `/ws/...` 不是 `/api/ws/...`**，这是最常见的对接坑。
- 认证开启时，连接 URL 带 `?api_key=xxx` 或握手头带 `X-API-Key`。
- 前端用推送的 `state` 做"当前步骤"动画；`state == "COMPLETE"` 后结果仍走 `GET /api/status/{task_id}` 的 `result` 取（WS 只推状态，不推完整结果体）。

---

## 3. 可视化报告（赛题核心得分点）

### `GET /api/report/{session_id}`

返回**知识盲区热力图 + 资源难度匹配曲线 + 学习路径规划图**三大组件的结构化数据，前端自行渲染图表。

> 前置条件：该 `session_id` 至少成功提问过一次（后端已生成学情画像），否则返回 **404**。

**响应**（`LearningReport`）
```json
{
  "session_id": "sess_abc123",
  "profile_summary": {
    "knowledge_level": "ENTRY",          // ENTRY / INTERMEDIATE / ADVANCED
    "domain_hint": [],
    "domain_confidence": { "RAG": "low", "向量数据库": "high" },
    "test_results": []
  },
  "knowledge_heatmap": {
    "nodes": [
      {
        "domain": "RAG",
        "agent_name": "agent_005",
        "status": "partial",             // mastered(绿) / partial(黄) / blind(红)
        "importance_score": 0.82,
        "interacted": true
      }
    ],
    "blind_count": 3,
    "summary": "还有 3 个领域盲区，建议优先补齐红色节点"
  },
  "difficulty_match": {
    "points": [
      {
        "domain": "RAG",
        "student_level": 0.4,            // 蓝线：学生掌握 0-1
        "resource_difficulty": 0.5,      // 红线：资源难度 0-1
        "match_status": "matched"        // matched / too_easy / too_hard
      }
    ],
    "overall_match_rate": 0.75
  },
  "learning_path": {
    "stages": [
      {
        "stage": 1,
        "title": "基础概念",
        "domains": ["LLM基础"],
        "estimated_hours": 4,
        "student_status": "blind",       // mastered / partial / blind
        "recommended": true              // 是否推荐优先学（盲区联动）
      }
    ]
  }
}
```

**前端渲染建议**
- **热力图**：用 `knowledge_heatmap.nodes[].status` 映射颜色——`mastered`→绿、`partial`→黄、`blind`→红；`blind_count` 做醒目提示。
- **匹配曲线**：横轴取 `difficulty_match.points[].domain`，画两条线：蓝线 `student_level`、红线 `resource_difficulty`；`match_status != "matched"` 的点高亮。
- **学习路径**：把 `learning_path.stages` 画成时间轴/流程图，`recommended == true` 的阶段置顶或加"推荐"标记。
- 三组件数据同源（都来自学情画像），可联动：点热力图红点 → 高亮路径图对应阶段。

---

## 4. 延伸交互

### `POST /api/quiz_submit`（答题 → 触发降维/进阶）
```json
请求：{ "task_id": "task_xxx", "session_id": "sess_abc123",
        "answers": [ {"question":"...","user_answer":"...","is_correct": true} ] }
响应：{ "task_id":"task_xxx", "accuracy": 0.8,
        "action": "redimension",         // redimension(降维) / advance(进阶) / recheck(复核)
        "new_resources": {...或null},     // 降维后新资源包（结构同 §6）
        "advance_question": {...或null},  // 进阶挑战题
        "followup_questions": ["...","..."] }
```
- 正确率 <60% → `redimension`；60%–85% → 轻度 `redimension`；≥85% → `advance`。

### `POST /api/feedback`（学生反馈 → 更新记忆/触发复核）
```json
请求：{ "task_id":"task_xxx", "session_id":"sess_abc123",
        "agent_id":"agent_005", "function_tag":"...",
        "feedback_type":"helpful",        // helpful / not_helpful / content_error / difficulty_mismatch
        "comment":"讲解很清楚" }
响应：{ "success": true, "message":"反馈已记录: helpful", "extension_triggered": null }
```
- `content_error` → 触发 `recheck`；`difficulty_mismatch` → 触发 `redimension`。

---

## 5. 知识库（运维/调试用，前端一般不需）

| 接口 | 用途 |
|---|---|
| `GET /api/kb/health` | 知识库状态（stub/chromadb、chunk 数、依赖） |
| `POST /api/kb/import` | 导入文档目录 `{"path":"data/raw_docs","agent_ids":null}` |
| `GET /api/kb/search?query=...&top_k=5` | 检索测试，不经过 LLM，直接看知识库返回 |

---

## 6. 核心渲染对象：`resource_package`

`/api/ask` 响应与 `/api/status` 完成态 `result` 里的 `resource_package` 结构如下（前端渲染讲义/指南/测验就靠它）：

```json
{
  "task_id": "task_xxx",
  "lecture": {                              // 定制化讲义（必选）
    "title": "RAG 检索增强生成详解",
    "content_markdown": "## 概念\nRAG 是...\n```python\n...\n```",
    "difficulty_note": "已按 ENTRY 水平适配，先理解再实操",
    "knowledge_refs_display": [             // 溯源标注（可展示给学生）
      { "source": "《RAG实战》第3章", "verification_status": "已验证" }
    ]
  },
  "practice_guide": {                       // 实操指南（含代码时生成，否则 null）
    "goal": "跑通一个最小 RAG demo",
    "env_setup": "pip install langchain chromadb",
    "steps_markdown": "1. 准备文档\n2. 建向量库\n...",
    "expected_output": "终端打印 top-3 相关片段",
    "common_issues": ["chromadb 版本冲突", "..."]
  },
  "quiz": {                                 // 分阶测试题（3–5 道，否则 null）
    "questions": [
      {
        "question": "RAG 中检索器的作用是？",
        "type": "选择",                      // 判断 / 选择 / 简答 / 代码补全 / 设计分析
        "options": ["A...","B...","C..."],   // 仅选择题有
        "answer": "B",
        "explanation": "检索器负责从知识库召回相关片段…",
        "difficulty": "基础"                 // 基础 / 应用 / 综合 / 进阶
      }
    ]
  },
  "focused_output_ref": "fo_xxx",
  "profile_ref": "sp_xxx"
}
```
- `lecture.content_markdown` 是 Markdown，前端直接渲染即可（含代码块）。
- `practice_guide` 与 `quiz` 可能为 `null`（取决于问题类型），前端做**空值保护**。

---

## 7. 错误码与状态码

| 场景 | HTTP / 状态 | 说明 |
|---|---|---|
| 报告无画像 | `404` | 该 `session_id` 未提问过，前端应先引导提问 |
| API Key 错误 | `401` | `{"detail":"无效或缺失 API Key…"}`（仅开启认证时出现） |
| 业务异常 | `500` | 后端报错；`/api/ask` 同步失败会在响应里带 `"error"` 字段而非抛 500（已容错） |
| 任务未完成 | `state` 非 `COMPLETE` | 轮询/WS 时 `result` 为 `null`，继续等 |

---

## 8. 联调示例

**curl（同步提问）**
```bash
curl -X POST http://localhost:8000/api/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"什么是RAG？","session_id":"sess_demo01"}'
```

**JavaScript（fetch + 轮询，推荐）**
```js
const BASE = "https://<隧道域名>";   // 或 http://localhost:8000
const sessionId = "sess_" + crypto.randomUUID();

// 1) 异步提交
const { task_id } = await fetch(`${BASE}/api/tasks`, {
  method: "POST", headers: {"Content-Type":"application/json"},
  body: JSON.stringify({ question: "什么是RAG？", session_id: sessionId })
}).then(r => r.json());

// 2) 轮询直到 COMPLETE
let result = null;
while (true) {
  const st = await fetch(`${BASE}/api/status/${task_id}`).then(r => r.json());
  if (st.state === "COMPLETE") { result = st.result; break; }
  await new Promise(r => setTimeout(r, 1500));
}

// 3) 取可视化报告
const report = await fetch(`${BASE}/api/report/${sessionId}`).then(r => r.json());
// 渲染 report.knowledge_heatmap / difficulty_match / learning_path
```

**WebSocket（实时进度）**
```js
const ws = new WebSocket(`ws://<BASE-host>/ws/${task_id}`);  // 注意：无 /api 前缀
ws.onmessage = (e) => {
  const msg = JSON.parse(e.data);   // { type:"fsm_state", state:"FOCUSING", ... }
  updateStepIndicator(msg.state);
};
```

---

## 9. 联调注意事项（避坑）

1. **WebSocket 路径没有 `/api` 前缀**：`/ws/{task_id}`，不是 `/api/ws/...`。
2. **`session_id` 要自己生成并复用**：报告按它聚合，每次刷新页面若重新生成会导致画像丢失、报告 404。
3. **`report` 前置条件**：必须该会话先成功提问过一次，否则 404。
4. **CORS + 凭据**：开发态 `allow_origins=["*"]` 且与 `allow_credentials=True` 并存；前端若用 `fetch` 带 `credentials:"include"` 会被浏览器拦截，联调期建议前端**不**带凭据、或后端把前端域名写入 `CORS_ORIGINS`。
5. **Cloudflare 隧道域名会变**：当前联调隧道每次重启会换新域名，旧 URL 立即失效（报 Error 1033/530）。重启后需向后端同学要新域名；Windows 双击 URL 可能弹"找不到应用程序"，复制到浏览器地址栏即可。
6. **隧道 >100s 超时**：`/api/ask` 同步全链路约 20–38s，一般安全；若问题复杂超时，改用 `/api/tasks` + 轮询/WS。
7. **`practice_guide` / `quiz` 可能为空**：渲染前判空，不要假设一定有。
8. **`disclaimer` 字段**：含 AI 生成内容，建议原样展示以满足合规。

---

> 后端同学（L）负责维护此文档与接口实现；接口若有变更会同步更新本文件。联调问题直接找后端。
