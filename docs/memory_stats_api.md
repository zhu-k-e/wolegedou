# 贡献记忆闭环接口对接说明（GET /api/memory_stats）

> 对应赛题「作品完整性 30 分」闭环最后一步：**交互反馈 → 动态决策更新**。
> 后端已实现贡献记忆闭环（每次任务完成后记录各 Agent 贡献、EMA 更新表现分、动态调整 α、淘汰低表现 Agent），
> 但此前**未暴露给前端读取**，导致前端无法展示、视频拍不到。本接口用于补上这一可视化。

## 1. 端点

```
GET /api/memory_stats
```

- **基础地址**：你们 cloudflared 隧道 URL（如 `https://xxxx.trycloudflare.com`）+ 上面的路径
- **鉴权**：当前联调环境 `api_key` 为空，无需鉴权；若部署时 `.env` 配置了 `api_key`，前端需在每个请求头带 `X-API-Key: <key>`。
- **参数**：无（返回全系统累计的贡献记忆状态，演示用足够）。

## 2. 调用时机

在 `/api/status/{task_id}` 返回任务 `COMPLETE` 之后调用，作为闭环第 5 步「多智能体协同优化反馈」展示。

## 3. 响应字段

| 字段 | 类型 | 含义 |
|------|------|------|
| `alpha` | float | 当前调度遴选权重 α（冷启动 0.9 → 数据积累后阶梯降至 0.3）。演示环境当前为 `0.3` |
| `agent_count` | int | 参与过任务的 Agent(function_tag) 总数 |
| `agents[]` | list | 各 Agent 表现明细，按 `importance_score` 降序 |
| `agents[].agent_id` | str | Agent ID |
| `agents[].agent_name` | str | Agent 名称（如「LLM基础Agent」） |
| `agents[].function_tag` | str | 职能标签（如「LLM原理与概念」） |
| `agents[].accuracy` | float | 历史准确率（EMA） |
| `agents[].count` | int | 参与任务次数 |
| `agents[].rework_rate` | float | 返工率（越低越好） |
| `agents[].importance_score` | float | 贡献重要度分（0–1，越高越被优先调度） |
| `agents[].is_suspended` | bool | 是否被淘汰暂停（`true`=已暂停候选资格） |
| `recent_contributions[]` | list | 最近 20 条贡献记录（`task_type<>'offline_eval'`，不含 benchmark 数据） |
| `recent_contributions[].task_id` | str | 任务 ID |
| `recent_contributions[].agent_id` | str | Agent ID |
| `recent_contributions[].function_tag` | str | 职能标签 |
| `recent_contributions[].review_score` | float | 裁判团评分 |
| `recent_contributions[].importance_score` | float | 本条贡献重要度 |
| `recent_contributions[].referee_verdict` | str | 裁判结论：`passed`/`revise`/`low_confidence_passed`/`failed` |
| `recent_contributions[].created_at` | str | 时间 |
| `eliminations[]` | list | 淘汰记录（表现持续差的 Agent 被移出候选池） |
| `eliminations[].agent_id` | str | Agent ID |
| `eliminations[].function_tag` | str | 职能标签 |
| `eliminations[].reason` | str | 淘汰原因 |
| `eliminations[].created_at` | str | 时间 |

## 4. 真实返回示例（节选）

```json
{
  "alpha": 0.3,
  "agent_count": 45,
  "agents": [
    {
      "agent_id": "agent_001",
      "agent_name": "LLM基础Agent",
      "function_tag": "LLM原理与概念",
      "accuracy": 0.8835,
      "count": 262,
      "rework_rate": 0.0008,
      "importance_score": 0.9415,
      "is_suspended": false
    },
    {
      "agent_id": "agent_009",
      "agent_name": "项目实战Agent",
      "function_tag": "项目架构与落地",
      "accuracy": 0.8245,
      "count": 90,
      "rework_rate": 0.0895,
      "importance_score": 0.8654,
      "is_suspended": false
    }
  ],
  "recent_contributions": [
    {
      "task_id": "task_1962d568c305",
      "agent_id": "agent_001",
      "function_tag": "LLM原理与概念",
      "review_score": 0.8833,
      "importance_score": 0.9415,
      "referee_verdict": "passed",
      "created_at": "2026-08-16 11:29:26"
    }
  ],
  "eliminations": [
    {
      "agent_id": "agent_xxx",
      "function_tag": "xxx",
      "reason": "连续N次importance_score<阈值",
      "created_at": "2026-08-xx"
    }
  ]
}
```

## 5. 前端展示建议（闭环第 5 步卡片）

在任务完成页末尾加一个「多智能体协同优化反馈」区块，展示：

1. **当前 α 值** —— 一行字：「系统调度权重 α = 0.30（数据积累后自动从 0.9 阶梯下降，越用越稳）」
2. **Agent 贡献分排行** —— 表格/条形：Agent 名称 | 职能 | 贡献分(importance_score) | 准确率 | 参与次数 | 状态
3. **最近贡献流** —— 时间线：Task xxx · Agent xxx · 裁判结论 passed · 评分 0.88
4. **淘汰记录** —— 若有，提示「某 Agent 因表现持续偏差已被移出候选池，进入离线评估」

这证明系统**会越用越聪明、会优胜劣汰**，正是赛题要求的「动态决策更新」。

## 6. 注意事项

- **必须重启后端**：本次新增了 `backend/api/routes/memory.py` 并在 `main.py` 注册。队友调用前请确保后端已重启（PyCharm 停止再运行，或命令行重启，注意 8000 端口僵尸进程）。
- 数据已隔离 benchmark：`recent_contributions` 已排除 `offline_eval` 记录，演示数据干净。
- 该接口为**只读**，不影响任何生成逻辑，可安全调用。
