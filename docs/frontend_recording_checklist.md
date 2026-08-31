# 前端对接与演示录制对账清单（后端已确认事项）

> 用途：发给前端队友，录制竞赛演示视频前逐项核对。所有结论均基于 `backend/` 真实源码核实，非推测。
> 最后更新：2026-08-20

---

## 0. 结论速览（避免再走弯路）

- **后端连接已证实正常**：队友前端走真实后端（日志可见真实 KB 检索、状态机流转、贡献记忆落库），不存在"演示数据"问题，无需担心假数据。
- **队友前端用的是轮询，不是 WebSocket**：日志反复出现 `无WebSocket连接，跳过推送`，前端靠 `GET /api/status` 轮询拿状态。所以"WS 路径写错"的坑对你**不适用**（那是参考页 `frontend_reference.html` 的坑，非你代码）。
- **后端已就位**，下面是前端需要配合渲染 / 核对的点。

---

## 1. 测验阈值：唯一 0.85

- 后端判定：`accuracy < 0.85` → 降维（redimension）；`≥ 0.85` → 进阶（advance）。见 `orchestrator.py:1254`。
- **前端不要自己硬编码 60% / 80%**。直接消费后端返回的 `action` 字段来显示"降维/进阶"，不要再画一道本地阈值。
- 正确展示文案示例：
  - `action === "redimension"` → "正确率未达 85%，已为你降维重讲"
  - `action === "advance"` → "正确率达标（≥85%），已生成进阶挑战"

---

## 2. 裁判三维度分数（后端现已返回，前端需渲染）

- 后端在 `AskResponse` 中已新增字段 `review_summary`（之前漏了，现已补上）：
  ```json
  "review_summary": {
    "fact_accuracy": 0.85,       // 事实准确性
    "logic_completeness": 0.95,  // 逻辑完整性
    "pedagogical_fit": 0.90      // 教学适用性
  }
  ```
- 前端应把这三个值渲染成**三条量化分数条 + 定性结论**，而不是只显示一行"通过/未通过"文字。
- 来源接口：`/api/ask` 返回、`/api/status/{task_id}` 的 result 里都有。

---

## 3. 知识引用去重（后端已做，前端直接渲染即可）

- 后端在构建展示引用 `knowledge_refs_display` 时已按 `(source, content_summary)` 权威去重（保留首次、顺序稳定）。
- 前端返回的引用数组天然干净，**无需前端再写去重逻辑**。
- 渲染方式：遍历 `lecture.knowledge_refs_display`（或资源包里的对应字段），每条显示：
  - 来源名 `source`
  - 验证状态徽标 `verification_status`（取值：`已验证` / `待验证` / `矛盾`）
- 建议：文件名过长做截断（`...` 省略 + hover 看全名），别撑破面板。

---

## 4. 启发式追问渲染（重点，视频目前看不到就是因为没渲染）

### 4.1 它是什么（纠正术语）

| 名称 | 后端状态 | 说明 |
|---|---|---|
| 测验（5题） | `QUIZ_EVAL` | 真正的测试，按 0.85 判分 |
| 降维 | `REDIMENSION` | 测验<85% → 重新出降维讲解+资源包（**不是测试**） |
| 进阶 | `ADVANCE` | 测验≥85% → 追加 1 道进阶挑战题（**不是测试**） |
| **启发式追问** | `HEURISTIC_FOLLOWUP` | 上面两者**结束后**的收尾，生成 1~2 个引导追问（**不计分、非测试**） |

- `HEURISTIC_FOLLOWUP` 是 `REDIMENSION`/`ADVANCE` **之后**的独立收尾状态（`orchestrator.py:10` 状态机明确排序）。它不是降维或进阶本身。
- 视频文案应为："学生做完测验 → 系统自动降维重讲 / 或给进阶挑战 → **最后再根据本次内容追问 1~2 个问题引导深入**"。

### 4.2 后端返回合同（`QuizSubmitResponse`，`schemas.py:92`）

```json
{
  "task_id": "task_xxx",
  "accuracy": 0.83,
  "action": "redimension",            // redimension / advance / recheck
  "new_resources": { "...": "..." },  // action=redimension 时：降维资源包
  "advance_question": { "...": "..." }, // action=advance 时：进阶挑战题
  "followup_questions": [             // 👈 启发式追问，list[str]，可能 null/空
    "你能举一个 RAG 在实际项目里检索失败的例子吗？",
    "如果知识库里没有相关内容，系统应该怎么回答？"
  ]
}
```

- **`followup_questions` 和降维/进阶结果在同一个响应里一起返回**，前端不用再发第二次请求。
- 类型：`Optional[list[str]]`（纯文本问题数组），可能为 `null` 或空数组 → **必须判空**。

### 4.3 渲染逻辑（三步）

1. 提交测验拿到 `r = QuizSubmitResponse`；
2. 按 `r.action` 先展示自适应主体（redimension→降维讲解 / advance→进阶挑战题）；
3. 最后，只要 `r.followup_questions` 非空，渲染独立区块"💡 系统想进一步问你："。

### 4.4 前端代码（vanilla JS 示例）

```js
// 假设 r 是 /api/quiz_submit 的返回
function renderQuizResult(r) {
  // 1) 先展示降维/进阶主体
  if (r.action === 'redimension' && r.new_resources) {
    showReducedResources(r.new_resources);      // 你的降维讲解渲染
  } else if (r.action === 'advance' && r.advance_question) {
    showAdvanceQuestion(r.advance_question);    // 你的进阶挑战渲染
  }

  // 2) 启发式追问收尾区块（核心）
  const box = document.getElementById('followupBox');
  const list = document.getElementById('followupList');
  if (Array.isArray(r.followup_questions) && r.followup_questions.length > 0) {
    list.innerHTML = '';
    r.followup_questions.forEach(q => {
      const li = document.createElement('li');
      li.className = 'followup-item';
      li.textContent = q;                       // 纯文本，直接显示
      list.appendChild(li);
    });
    box.style.display = 'block';                // 显示区块
  } else {
    box.style.display = 'none';                 // 没有就隐藏，别留空框
  }
}
```

对应 HTML：
```html
<div id="followupBox" style="display:none" class="followup-panel">
  <div class="followup-title">💡 系统想进一步问你：</div>
  <ul id="followupList"></ul>
</div>
```

### 4.5 给队友的三个注意点

- **判空**：`followup_questions` 可能为 `null`/空，必须 `Array.isArray && length>0` 才显示，否则会留个空面板。
- **它不是测试**：只是 1~2 条引导问题，不计分、不判对错。文案写"系统想进一步问你"而非"请作答"。
- **可选增强**：如果想让追问可点，点某条就把该问题作为新提问 `POST /api/ask`（开启新一轮学情闭环）——加分项，非必需。

---

## 5. 真实接口清单（供核对你前端调用的路径）

| 用途 | 方法 + 路径 | 备注 |
|---|---|---|
| 提交问题 | `POST /api/tasks` | 专为隧道/超时场景加的入口（`ask.py:117`） |
| 轮询任务状态 | `GET /api/status/{task_id}` | 你前端靠它拿进度（非 WS） |
| 提问详情 | `GET /api/ask` 返回 / `POST /api/ask` | 含 `review_summary` 三维度分 |
| 学情报告 | `GET /api/report/{session_id}` | 含 `difficulty_match`（难度匹配曲线数据） |
| 贡献记忆 | `GET /api/memory_stats` | 含 α、11 个 Agent、贡献排行、淘汰记录 |
| 提交测验 | `POST /api/quiz_submit` | 返回 `QuizSubmitResponse`（见 §4.2） |
| WebSocket（可选） | `/ws/{task_id}` | 你前端走轮询，此项可不用；注意真实路径**无 `/api` 前缀** |

> 核对要点：把你前端实际调用的路径对照上表，尤其确认没有写成 `/api/ws/`（那是错的，真实是 `/ws/`）——不过你既然用轮询，这条基本与你无关。

---

## 6. 录制前必须补齐 / 修正的前端缺口（汇总自调试视频逐帧分析）

以下问题是在实测录屏里发现的、属于前端展示层、需在你代码里修：

1. **缺「资源难度匹配曲线」**（**纯前端缺口，后端已返回真实数据**）：报告页应有「画像 / 盲区热力图 / 学习路径 / 难度匹配曲线」四图，目前缺第 4 个。后端 `/api/report/{session_id}` 已返回 `difficulty_match`（数据来自 `task_resource_stats` 表，每次生成资源包都会写入，真实有数据）。
   - **返回合同**（`LearningReport.difficulty_match`，schemas.py:130）：
     ```json
     "difficulty_match": {
       "points": [
         {"domain":"LLM基础","student_level":0.6,"resource_difficulty":0.4,"match_status":"matched"}
       ],
       "overall_match_rate": 0.85
     }
     ```
     字段含义：`student_level` 学生掌握水平 0-1（蓝线）、`resource_difficulty` 资源难度 0-1（红线）、`match_status`：`matched`/`too_easy`/`too_hard`。
   - **画法**：报告页加第 4 个 tab「资源难度匹配」。每个 domain 画两条对比（学生水平蓝 vs 资源难度红，折线或分组柱状图均可）；`match_status` 配色 matched=绿 / too_easy=黄 / too_hard=红；顶部用 `overall_match_rate` 显示「整体难度匹配率 XX%」。可用 Chart.js / ECharts，或纯 DOM+SVG。
   - **⚠️ 录制前提**：该曲线依赖 session 真实跑过至少一次「问答+生成资源」。若录制用的 session 没真实生成过资源，`points` 会为空、曲线空白。录制前先在该 session 真实跑一轮。
2. **裁判团三维度面板**：见 §2，把 `review_summary` 渲染成三条分数条（事实/逻辑/教学），不要只显示一行文字。
3. **「实操指南」展示不清晰**：后端始终生成三形态（讲义/实操指南/测试题），但录屏里只看到讲义+测验。请给实操指南一个独立卡片或 tab。
4. **启发式追问 UI 缺失**：见 §4，录屏看不到追问区块，需补渲染。
5. **quiz 阈值标签错误**：录屏里显示 60% 升档 / 低于 60% 降档，与后端 0.85 矛盾。改为直接消费 `action` 字段（§1）。
6. **调试 JSON 横幅**：报告页的"查看原始报告 JSON"在录制/发布前**隐藏**（不删代码，仅隐藏）。
7. **知识引用重复/超长**：后端已去重（§3），前端只需 1:1 渲染 + 文件名截断即可。

---

## 7. 录制时间隐患（单次问答 ≈ 84 秒）

- 真实跑批实测：单次完整问答（含 RAG 检索、候选/聚焦、裁判、资源生成）约 **84 秒**（`主FSM完成 ... 耗时=84.39s`）。
- 10 分钟视频若每个问题都现场等 84 秒，时间直接爆。建议：
  - 录制前**预跑预热**（让模型/检索缓存热起来，首次会偏慢）；
  - 对"等待生成"的段落做**剪辑/快进**，不要实时干等；
  - 挑选**响应较快**的用例演示，避免长链路问题。

---

## 8. 代码安全检查提示

- 后端资源生成会触发代码安全检查（`.run()`、`os` 导入等会被 `WARNING` 标记），属**正常防护**，资源仍正常生成。
- 但视频里若实操指南露出 `import os` 或 `.run()` 这类代码，评委可能多想。建议录制时**避开含此类代码的用例**，选纯讲解/无危险操作的示例。

---

## 附：视频应展示的闭环（供队友构图参考）

学情画像 →（提交问题）→ 多 Agent 调度可视化（8 步流水线）→ 内容生成（讲义/实操/测验三形态）→ 裁判三维度评分 → 学情报告（盲区热力图 / 学习路径 / 难度曲线）→ 测验（85% 门槛判降维/进阶）→ 启发式追问收尾 → 贡献记忆闭环（α / 11 Agent）。以上全部为真实后端跑出的数据。
