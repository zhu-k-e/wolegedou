# 学情诊断报告 API（方案书 8.2.2 节三组件）

> 对齐赛题要求：*"支持生成可视化的个人学情与资源匹配度报告，包含知识盲区定位、资源难度匹配曲线、学习路径规划图等"*

## 端点

```
GET /api/report/{session_id}
```

学生提问后（画像已生成），前端调此接口获取报告数据，自行渲染三个可视化组件。

## 请求示例

```
GET /api/report/demo-15
```

如果该 session 还没有学情画像（未提问过），返回 404。

## 响应结构

```json
{
  "session_id": "demo-15",
  "profile_summary": {
    "knowledge_level": "ENTRY",
    "domain_hint": ["RAG", "LLM基础"],
    "domain_confidence": {"RAG": "high", "LLM基础": "low"}
  },
  "knowledge_heatmap": {
    "nodes": [
      {"domain": "LLM基础", "agent_name": "LLM基础Agent", "status": "partial", "importance_score": 0.49, "interacted": true},
      {"domain": "RAG", "agent_name": "RAG架构Agent", "status": "mastered", "importance_score": 0.8, "interacted": true},
      {"domain": "Prompt工程", "agent_name": "Prompt工程Agent", "status": "blind", "importance_score": 0.5, "interacted": false}
    ],
    "blind_count": 7,
    "summary": "你的知识盲区集中在 7 个核心领域，建议从「基础概念」开始系统学习"
  },
  "difficulty_match": {
    "points": [
      {"domain": "RAG", "student_level": 0.8, "resource_difficulty": 0.83, "match_status": "matched"},
      {"domain": "LLM基础", "student_level": 0.4, "resource_difficulty": 0.31, "match_status": "matched"}
    ],
    "overall_match_rate": 1.0
  },
  "learning_path": {
    "stages": [
      {"stage": 1, "title": "基础概念", "domains": ["LLM基础"], "estimated_hours": 4, "student_status": "partial", "recommended": false},
      {"stage": 2, "title": "Prompt工程", "domains": ["Prompt工程"], "estimated_hours": 3, "student_status": "blind", "recommended": true},
      {"stage": 5, "title": "RAG架构", "domains": ["RAG", "LangChain"], "estimated_hours": 5, "student_status": "blind", "recommended": true}
    ]
  }
}
```

## 字段说明

### 组件1：知识盲区热力图 `knowledge_heatmap`

| 字段 | 类型 | 说明 |
|------|------|------|
| `nodes[].domain` | string | 领域名（如 LLM基础、RAG、Prompt工程） |
| `nodes[].agent_name` | string | 关联的主 Agent 名 |
| `nodes[].status` | string | `mastered`(绿已掌握) / `partial`(黄部分掌握) / `blind`(红盲区) |
| `nodes[].importance_score` | float | Agent Card 历史评分 0-1 |
| `nodes[].interacted` | bool | 学生是否已交互该领域 |
| `blind_count` | int | 盲区领域数 |
| `summary` | string | 汇总建议文本 |

**颜色编码**（对齐方案书 8.2.2）：
- 🟢 绿色 `mastered`：学生已掌握（画像 domain_confidence 标 high）
- 🟡 黄色 `partial`：部分掌握（标 low，或未交互但系统 importance≥0.7）
- 🔴 红色 `blind`：知识盲区（未交互且 importance<0.7）

**前端渲染建议**：网格热力图，9 个领域节点。红色节点可点击跳转"推荐学习该知识点"。

### 组件2：资源难度匹配曲线 `difficulty_match`

| 字段 | 类型 | 说明 |
|------|------|------|
| `points[].domain` | string | 知识标签（横轴） |
| `points[].student_level` | float | 学生掌握水平 0-1（蓝线） |
| `points[].resource_difficulty` | float | 资源难度 0-1（红线） |
| `points[].match_status` | string | `matched` / `too_easy` / `too_hard` |
| `overall_match_rate` | float | 整体匹配率 0-1 |

**匹配判断**：|学生水平 - 资源难度| < 0.2 → matched；学生 > 资源 → too_easy（可进阶）；学生 < 资源 → too_hard（需降维）。

**前端渲染建议**：双轴折线图，横轴为 domain，蓝线=学生水平，红线=资源难度。偏差大的点标注 ⚠️。

### 组件3：学习路径规划图 `learning_path`

| 字段 | 类型 | 说明 |
|------|------|------|
| `stages[].stage` | int | 阶段序号 1-7 |
| `stages[].title` | string | 阶段标题 |
| `stages[].domains` | string[] | 涉及领域 |
| `stages[].estimated_hours` | int | 预计学习时间（小时） |
| `stages[].student_status` | string | `mastered` / `partial` / `blind` |
| `stages[].recommended` | bool | 是否推荐优先学习（盲区联动） |

**7 阶段路径**（基于 AI 知识依赖关系）：
1. 基础概念（LLM基础）4h
2. Prompt工程 3h
3. 模型调用与微调（HuggingFace + 模型微调）6h
4. 向量检索（向量数据库）3h
5. RAG架构（RAG + LangChain）5h
6. Agent框架 4h
7. 项目实战（项目部署）6h

**前端渲染建议**：横向流程图/路径图，每个阶段一个节点。`recommended=true` 的节点高亮标注"推荐优先学习"。点击节点可跳转该阶段的深度学习（触发 generation 路径）。

## 数据来源

| 组件 | 数据源 |
|------|--------|
| 热力图 | 学情画像 `domain_confidence` + Agent Card `importance_score` |
| 匹配曲线 | 学情画像 `knowledge_level` + `task_resource_stats` 表（quiz difficulty 分布） |
| 路径图 | 7 阶段固定路径模板 + 学情画像 + 热力图联动 |

`task_resource_stats` 表在每次 `/api/ask` 返回时自动写入（从 resource_package 聚合 quiz difficulty），无需额外操作。
