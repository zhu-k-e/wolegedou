# 前端对接指南

本指南面向前端开发者 / 评审，说明如何与本后端进行联调。

## 1. 基础信息

- 后端默认地址：`http://localhost:8000`
- 接口前缀：`/api`
- WebSocket 路径：`ws://localhost:8000/ws/{task_id}`（**无 `/api` 前缀**）
- 接口文档（Swagger）：`http://localhost:8000/docs`
- CORS：默认允许所有来源（`allow_origins=["*"]`），生产环境可在 `.env` 中设置 `CORS_ORIGINS` 收紧。

## 2. 核心流程

```
1. 调用 POST /api/ask 提交问题
   -> 返回 task_id、session_id、profile、resource_package、review_summary 等
2. 同时连接 ws://localhost:8000/ws/{task_id} 接收 FSM 状态流
3. 可选：调用 POST /api/quiz_submit 提交答题结果，触发降维/进阶
4. 可选：调用 GET /api/report/{session_id} 获取学情诊断报告
5. 可选：调用 POST /api/feedback 提交反馈
```

## 3. 主要接口

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/ask` | 学生提问，驱动多智能体生成资源包 |
| GET | `/api/status/{task_id}` | 查询任务状态（也可通过 WebSocket 实时获取） |
| WS | `/ws/{task_id}` | 任务状态实时推送 |
| POST | `/api/quiz_submit` | 提交测验答案，触发 redimension/advance/recheck |
| POST | `/api/feedback` | 对 Agent 输出进行反馈 |
| GET | `/api/report/{session_id}` | 学情诊断报告（热力图 / 难度曲线 / 学习路径） |
| GET | `/api/kb/health` | 知识库健康检查 |
| GET | `/health` | 服务健康检查 |

## 4. /api/ask 请求示例

```json
{
  "question": "什么是RAG",
  "session_id": "sess_001",
  "profile": {
    "background": "有Python基础",
    "knowledge_level": "中级",
    "current_goal": "项目落地",
    "question_type": "操作步骤",
    "domain_hint": ["RAG"]
  }
}
```

`profile` 为可选；字段非法时系统自动降级为自动诊断，不影响主流程。

## 5. 学情诊断报告

详见 `docs/report_api.md`，返回结构包含：

- `knowledge_heatmap`：知识盲区热力图
- `difficulty_match`：资源难度匹配曲线
- `learning_path`：学习路径规划图

## 6. 注意事项

- 首次启动后，冷启动状态下 `/api/kb/health` 的 `embedding_backend` 可能为 `null`，完成一次 `/api/ask` 查询后会变为 `"flag"`。
- 如需在外网演示，可自行配置 Nginx 反向代理或 cloudflared 等隧道工具；**请勿将开发隧道地址写入正式文档**。
