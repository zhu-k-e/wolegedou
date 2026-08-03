# 前端对接：异步任务接口（解决联调超时）

> 适用场景：前端通过 cloudflared 等隧道联调时，`/api/ask` 同步阻塞（单次 1~2 分钟）会被隧道 100s HTTP 超时 + 前端 30s 超时切断，永远拿不到响应。

## 方案

后端新增**异步任务接口**，把"提交"和"取结果"拆开：

1. `POST /api/tasks` 提交问题 → **立即返回 `task_id`（<100ms）**，后端后台跑
2. `GET /api/status/{task_id}` 轮询状态/结果（短请求，不踩隧道超时）

旧的 `POST /api/ask`（同步阻塞）**保留**，本地调试仍可用。

## 接口契约

### 1. 提交任务

```
POST /api/tasks
Content-Type: application/json

{
  "question": "什么是RAG？",
  "session_id": "sess_abc",
  "history": []          // 可选，同一 session 首次为空
}

→ 200 OK
{
  "task_id": "task_xxxxxxxxxxxx",
  "status": "PENDING"
}
```

### 2. 轮询状态/结果（推荐）

```
GET /api/status/{task_id}

→ 进行中:
{
  "task_id": "task_xxx",
  "state": "GENERATING",     // PROFILING→DISPATCHING→GENERATING→REVIEWING→FOCUSING→JUDGING→FORMATTING
  "data": { },               // 当前阶段附加数据（如有）
  "result": null
}

→ 完成:
{
  "task_id": "task_xxx",
  "state": "COMPLETE",
  "data": { },
  "result": {
    "task_id": "task_xxx",
    "session_id": "sess_abc",
    "profile": { },                  // 学生画像
    "resource_package": { },          // 讲义 / 指南 / 测试题
    "judge_verdict": { },             // 裁判团裁决
    "review_summary": { },
    "knowledge_refs_count": 15,
    "dispatch_info": { },
    "navigation_roadmap": "...",
    "clarification_options": [ ]
  }
}

→ 失败:
{
  "task_id": "task_xxx",
  "state": "ERROR",
  "result": { "error": "..." }
}
```

**前端轮询逻辑**：每 2~3 秒请求一次 `/api/status/{task_id}`：

- `state == "COMPLETE"` → 取 `result` 渲染（`result` 字段与原来 `/api/ask` 返回**完全一致**，渲染层无需改）
- `state == "ERROR"` → 展示 `result.error`
- 其他 → 继续轮询（可用 `state` 显示进度文案）

> ⚠️ **绝对不要给轮询循环设"总墙钟超时"**（例如「超过 30 秒/120 秒就放弃」）。后端可能跑 96 秒、140 秒甚至更久，**必须一直 poll 到 `state==COMPLETE` 或 `state==ERROR` 才停止**。每次 `/api/status` 请求本身都 <1 秒，不会触发任何超时，所以放心轮询即可。

### 3. WebSocket 实时进度（可选增强）

```
WS /ws/{task_id}
```

连接后，每次 FSM 状态变更推送 `{type, task_id, state, data}`。可用于实时进度条。**轮询已足够，WS 是增强项。**

## 前端最小改动清单

1. 调 `/api/ask` 等响应 → 改为调 `/api/tasks` 拿 `task_id`，随即启动轮询。
2. 轮询 `GET /api/status/{task_id}`，`state==COMPLETE` 取 `result` 渲染（字段同前，渲染逻辑基本不动）。
3. （可选）加进度条：轮询时显示 `state` 文案，或连 WS 收实时状态。

## 兼容性说明

- 入参（`AskRequest`）和结果字段（即 `AskResponse` 的字段）与原 `/api/ask` **完全一致**。
- `STATUS` 响应里新增 `result` 字段（任务未完成时为 `null`），老字段 `state` / `data` 不变。
