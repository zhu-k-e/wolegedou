# 领域知识个性化生成与多智能体协同决策系统——技术规格书

> 版本：v6.13 | 2026-06-27
> 用途：AI代码生成输入文档（每个处理步骤均有明确输入/输出规格）  
> 垂直领域：AI技能培训（大模型应用开发方向）

---

## 阅读指南

本文档按**数据流顺序**组织。每个模块由三个固定小节组成：
- **输入**：类型、格式、来源
- **处理逻辑**：步骤化，含伪代码
- **输出**：类型、格式、去向

---

# 第一部分：系统架构与数据流向

## 1.1 整体数据流向图

```
┌──────────────────────────────────────────────────────────────┐
│                      学生输入（文本）                           │
└──────────────────────────┬───────────────────────────────────┘
                         │ 原始问题字符串
                         ▼
┌──────────────────────────────────────────────────────────────┐
│  Step 1: 学情画像生成器                                      │
│  输入：{question: str, history: list[dict] | None,         │
│         session_id: str}                                     │
│  输出：StudentProfile（JSON，见2.2节）                       │
└──────────────────────────┬───────────────────────────────────┘
                         │ StudentProfile
                         ▼
┌──────────────────────────────────────────────────────────────┐
│  Step 2: 意图裁决                                            │
│  输入：StudentProfile.intent_type + domain_confidence         │
│  输出：处理路径（"generation" | "navigation" | "clarification"）│
└──────────────────────────┬───────────────────────────────────┘
                         │
              ┌──────────┼──────────┐
              ▼          ▼          ▼
         [导航]     [澄清]    [生成]
          输出       追问       │
          路线图     选项        ▼
                               Step 3
│  Step 3: 调度员                                              │
│  输入：StudentProfile + agent_cards + agent_performance       │
│  输出：segments: list[dict]（每段候选Agent列表）              │
└──────────────────────────┬───────────────────────────────────┘
                         │ segments
                         ▼
┌──────────────────────────────────────────────────────────────┐
│  Step 4: 候选输出（Agent池并行）                             │
│  输入：segments + question                                    │
│  输出：candidate_outputs: list[dict]                          │
└──────────────────────────┬───────────────────────────────────┘
                         │ candidate_outputs
                         ▼
┌──────────────────────────────────────────────────────────────┐
│  Step 5: 审核团队（Verifier / Skeptic / Evaluator）          │
│  输入：candidate_outputs + 锚定物                              │
│  输出：review_result: dict（每段最优Agent + 排名）              │
└──────────────────────────┬───────────────────────────────────┘
                         │ review_result
                         ▼
┌──────────────────────────────────────────────────────────────┐
│  Step 6: 聚焦输出（最优Agent二次调用）                        │
│  输入：最优Agent_id + question + 输出Schema                    │
│  输出：focused_output: dict（结构化输出）                      │
└──────────────────────────┬───────────────────────────────────┘
                         │ focused_output
                         ▼
┌──────────────────────────────────────────────────────────────┐
│  Step 7: 裁判团（3名裁判并行审查）                          │
│  输入：focused_output + 锚定物                                │
│  输出：judge_result: dict（通过/退回 + 溯源标注）             │
└──────────────────────────┬───────────────────────────────────┘
                         │ judge_result
                         ▼
              ┌──────────┴──────────┐
              ▼                     ▼
           [通过]                [退回修改]
           Step 8            Step 6重跑（修改后）
             │                     │
             ▼                     │
┌────────────────────────────┐        │
│  Step 8: 资源生成Agent    │◄─────────────────────────┘
│  输入：focused_output + 学情画像                           │
│  输出：resource_pack: dict（3种形态，条件生成）              │
└──────────────────────────┬───────────────────────────────────┘
                         │ resource_pack
                         ▼
┌──────────────────────────────────────────────────────────────┐
│  Step 9: 贡献记忆更新（后台异步）                            │
│  输入：judge_result + candidate_outputs + review_result       │
│  输出：agent_performance表行更新（EMA）                       │
└──────────────────────────────────────────────────────────────┘
```

## 1.2 处理路径决策表

| intent_type | 处理方式 | 进入Step |
|---|---|---|
| `generation` | 正常走Step 3~9 | 3 |
| `navigation` | 输出路线图 → 学生选择后重跑Step 1 | 不进入Agent池 |
| `clarification` | 输出澄清选项 → 学生回答后重跑Step 1 | 不进入Agent池 |

## 1.3 核心数据类型定义（全局）

以下类型在后续各模块中引用：

```python
# 学情画像
class StudentProfile:
    knowledge_level: Literal["入门", "中级", "进阶"]
    background: Literal["文科", "理科_无编程", "有Python基础", "有ML基础"]
    current_goal: Literal["快速上手应用", "深入理解原理", "项目落地", "算法研究"]
    question_type: Literal["概念理解", "操作步骤", "调试排错", "架构设计", "全链路规划"]
    domain_hint: list[str]                    # 领域枚举值列表
    complexity_estimate: Literal["单领域", "跨领域", "全链路"]
    intent_type: Literal["generation", "navigation", "clarification"]
    domain_confidence: dict[str, Literal["high", "low"]]
    session_id: str
    version: int

# 候选Agent输出
class CandidateOutput:
    segment_id: str               # "seg_1", "seg_2" ...
    agent_id: str
    raw_output: str               # Agent的原始输出文本
    output_tokens: int

# 审核结果
class ReviewResult:
    segment_id: str
    ranked_candidates: list[str]  # agent_id排序（最优→最差）
    selected_agent_id: str
    reason: str

# 裁判结果
class JudgeResult:
    segment_id: str
    passed: bool
    revision_needed: bool
    issues: list[str]             # 具体问题描述
    sources: list[str]             # 溯源标注（来源文档列表）
    judge_id: str
```

---

# 第二部分：模块一——学情画像生成器（Step 1~2）

## 2.1 功能边界

本模块只负责**生成学情画像 + 意图裁决**，不包含调度逻辑（调度逻辑在第三部分）。

## 2.2 Step 1：学情画像生成

### 输入

```python
{
    "question": str,              # 学生当前问题（必填）
    "history": list[dict] | None,  # 历史对话（同一session，首次为None）
    "session_id": str             # 会话ID（用于增量更新时查历史画像）
}
```

`history`每一条格式：
```python
{"role": "user" | "assistant", "content": str, "timestamp": str}
```

### 处理逻辑（增量更新——滑动窗口评估）

```
Step 1.1: 检查 session_id 是否存在历史画像
           若存在 → 检索近3次问答（不够3次则取全部）
           将近3次问答+历史画像注入Prompt（增量更新模式）
           若不存在 → 正常模式
Step 1.2: 构造Prompt（见2.4节模板）
Step 1.3: 调用LLM（API端点：POST /api/llm/generate）
Step 1.4: 解析JSON输出，校验每个字段值在枚举范围内
           解析失败 → 重试1次；仍失败 → 返回默认画像
Step 1.5: 增量更新模式时，执行字段合并规则（见2.3节）
           knowledge_level：根据近3次问题综合判断，允许升级也允许降级
           domain_hint：旧值 ∪ 新值（合并，不删除）
Step 1.6: 写入 student_profiles 表，版本号+1
```

### 字段合并规则（增量更新——滑动窗口评估）

| 字段 | 合并规则 |
|---|---|
| `knowledge_level` | 根据近3次问答综合判断，允许升级也允许降级（不再"只升不降"） |
| `domain_hint` | 旧值 ∪ 新值（合并，不删除） |
| `background` | 保持旧值（不更新，背景信息不随对话改变） |
| 其他字段 | 取新值 |

> **修正说明**：原方案knowledge_level"只升不降"，现改为滑动窗口评估——根据近3次问答综合判断，允许合理降级（如学生先问高级问题后问基础问题→说明在复习基础，合理降级）。

### 输出

```python
{
    "knowledge_level": str,
    "background": str,
    "current_goal": str,
    "question_type": str,
    "domain_hint": list[str],
    "complexity_estimate": str,
    "intent_type": str,
    "domain_confidence": dict,
    "session_id": str,       # 回传
    "version": int            # 首次=1，增量时=历史最大version+1
}
```

### 错误处理

| 异常情况 | 处理方式 |
|---|---|
| LLM返回非JSON | 重试1次；仍失败→返回默认画像（domain_hint=[], intent_type="clarification"） |
| `domain_hint`含非法值 | 过滤掉不在枚举列表中的值 |
| `intent_type`缺失 | 默认设为`"generation"` |

## 2.3 Step 2：意图裁决

本步骤内置于Step 1的LLM调用中（`intent_type`字段已由LLM输出），裁决逻辑由主程序执行，无需额外LLM调用。

### 裁决逻辑

```python
def route_by_intent(profile: StudentProfile) -> RouteResult:
    if profile.intent_type == "navigation":
        return RouteResult(path="navigation", data=generate_roadmap(profile))
    elif profile.intent_type == "clarification":
        return RouteResult(path="clarification", data=generate_clarification(profile))
    else:  # generation
        # 检查domain_confidence：全low→退回clarification
        if profile.domain_confidence and \
           all(v == "low" for v in profile.domain_confidence.values()):
            return RouteResult(path="clarification", data=generate_clarification(profile))
        return RouteResult(path="generation", data=profile)
```

### navigation路径输出

```python
{
    "path": "navigation",
    "roadmap_markdown": str,      # 路线图（Markdown格式）
    "next_action": "wait_for_selection"
}
```

路线图生成规则：
```
按 knowledge_level 确定推荐顺序：
  入门 → 推荐顺序：[LLM基础, Prompt工程]
  中级 → 推荐顺序：[RAG, 向量数据库, LangChain]
  进阶 → 推荐顺序：[模型微调, Agent框架, 项目部署]
末尾追加："你想从哪个阶段开始深入学习？"
```

### clarification路径输出

```python
{
    "path": "clarification",
    "options": list[str],         # 例如["①LLM基础与Prompt工程", "②RAG与向量数据库", ...]
    "next_action": "wait_for_answer"
}
```

选项生成规则：从`VALID_DOMAINS`中按2~3个一组，生成4~5个选项组。

## 2.4 Prompt模板

```
你是一个学情诊断专家。请根据学生的问题，输出严格的JSON格式的学情画像。

学生问题：{question}
历史对话：{history}

请从以下枚举值中选择，不要自创值：
- knowledge_level: ["入门", "中级", "进阶"]
- background: ["文科", "理科_无编程", "有Python基础", "有ML基础"]
- current_goal: ["快速上手应用", "深入理解原理", "项目落地", "算法研究"]
- question_type: ["概念理解", "操作步骤", "调试排错", "架构设计", "全链路规划"]
- domain_hint: 可从{VALID_DOMAINS}中选择多个，无匹配则留空数组[]
- complexity_estimate: ["单领域", "跨领域", "全链路"]
- intent_type: ["generation", "navigation", "clarification"]
  · generation: 问题含具体技术内容/动词，需要生成内容
  · navigation: 学生要方向推荐/路线图，且无具体技术目标
  · clarification: domain_hint为空且非导航请求
- domain_confidence: 对每个domain_hint评估置信度
  格式：{{"领域名": "high"|"low"}}
  · high: 问题中直接提及该领域或明确相关操作
  · low: 仅间接关联，不确定是否真正需要
  · 不使用medium，简化调度逻辑

只输出JSON，不要输出其他内容。
```

> `{VALID_DOMAINS}`为配置变量，字符串格式（写入Prompt时转为逗号分隔）：
> `["LLM基础", "Prompt工程", "LangChain", "RAG", "HuggingFace", "模型微调", "向量数据库", "Agent框架", "项目部署"]`

---

# 第三部分：模块二——调度员（Step 3）

## 3.1 功能边界

调度员**只负责选人**，不评分、不审核、不裁决。输入学情画像，输出每段候选Agent列表。

## 3.1.1 统一调用模式

> **背景**：每次LLM API调用实际耗时2-5秒，直接并发受限于API速率上限。系统统一采用**2候选 + 3人审核 + 3人裁判**的完整流程，审核与裁判各需3次独立LLM调用（并行发出，每次以不同角色Prompt执行，三次调用由同一个Agent实例发起），每段总调用9次。

| 参数 | 值 |
|------|-----|
| 每段候选数 | 2 |
| 审核团队 | 3人（Verifier + Skeptic + Evaluator） |
| 裁判团 | 3人（事实审查 + 逻辑审查 + 适用性审查） |
| 单段总调用 | 9次 |

**调用次数与耗时估算**（单段9次~20s）：

| 领域数 | 段数 | 候选 | 审核 | 聚焦 | 裁判 | 跨段审查 | 总调用 | 实际响应 |
|--------|------|------|------|------|------|---------|--------|---------|
| 1 | 1 | 2 | 3 | 1 | 3 | 0 | **9次** | **~20s** |
| 2 | 2 | 4 | 6 | 2 | 6 | 1 | **19次** | **~27s** |
| 3 | 3 | 6 | 9 | 3 | 9 | 1 | **28次** | **~33s** |
| 4 | 4 | 8 | 12 | 4 | 12 | 1 | **37次** | **~38s** |
| 5 | 5 | 10 | 15 | 5 | 15 | 1 | **46次** | **~43s** |
| 6-7 | 6-7 | 12-14 | 18-21 | 6-7 | 18-21 | 1 | **55-64次** | **~48s** |
| 8-10 | 触发分阶段 | — | — | — | — | — | **先3领域** | **~33s/批次** |

超过7领域时触发分阶段策略：先回答最核心的3-5个领域（按domain_confidence=high优先），在答案末尾提示"剩余领域将在下一轮补充"。

## 3.2 输入

```python
{
    "profile": StudentProfile,       # 来自Step 1
    "agent_cards": list[dict],      # agent_cards表全量读取（status=="active"）
    "agent_performance": list[dict] # agent_performance表全量读取
}
```

`agent_cards`表每行结构：
```python
{
    "agent_id": str,
    "primary_function": str,        # 主功能标签
    "secondary_functions": list[str], # 辅助功能标签
    "domain_tags": list[str],       # 领域标签
    "status": str                   # "active" | "eliminated"
}
```

`agent_performance`表每行结构：
```python
{
    "agent_id": str,
    "function_tag": str,           # 功能标签
    "accuracy": float,             # 0~1
    "count": int,
    "rework_rate": float,          # 0~1
    "importance_score": float       # 0~1
}
```

## 3.3 处理逻辑

### Step 3.1：确定段数与每段领域

```
若 profile.complexity_estimate == "单领域"：
    段数 = 1
    每段领域 = [profile.domain_hint[0]]（若domain_hint为空则报错）

若 profile.complexity_estimate == "跨领域"：
    段数 = len(profile.domain_hint)
    每段领域 = profile.domain_hint（每个领域一段）

若 profile.complexity_estimate == "全链路"：
    段数 = len(LINKAGE_STEPS)
    每段领域 = LINKAGE_STEPS[i].domains
```

配置变量 `LINKAGE_STEPS`（可按领域调整）：
```python
LINKAGE_STEPS = [
    {"seg_id": "seg_1", "domains": ["LLM基础"]},
    {"seg_id": "seg_2", "domains": ["Prompt工程"]},
    {"seg_id": "seg_3", "domains": ["RAG", "向量数据库"]},
    {"seg_id": "seg_4", "domains": ["LangChain"]},
    {"seg_id": "seg_5", "domains": ["项目部署"]}
]
```

### Step 3.2：每段遴选候选Agent

```
对每段 seg_i：
  1. 计算功能匹配度 tag_match_score：
     for each agent in agent_cards（仅 status=="active"）：
       # 额外检查：该agent在相关function_tag下是否is_suspended=1，若挂起则跳过
       tag_match = 0
       if agent.primary_function 匹配 seg_i.domain：tag_match += 1.0
       if any(sf in seg_i.domain for sf in agent.secondary_functions): tag_match += 0.7
       if any(dt in seg_i.domain for dt in agent.domain_tags): tag_match += 0.5
       tag_match_score[agent.agent_id] = min(tag_match, 1.0)

  2. 读取 importance_score（per function_tag）：
     for each agent：
       fp = agent.primary_function
       perf = lookup(agent_performance, agent_id=agent.agent_id, function_tag=fp)
       importance = perf.importance_score if perf else 0.5  # 默认值

  3. 综合排序：
     alpha = get_alpha()
     for each agent:
       final_score = alpha * tag_match_score[agent.agent_id] + (1 - alpha) * importance

  4. 选前N名（N=2）
     确保2个候选（不足时放宽匹配规则，仍不足→标记"单候选"）

  5. 输出该段候选列表
```

### Step 3.3：alpha动态切换

```python
def get_alpha() -> float:
    """α动态衰减：数据越多，表现标签权重越高"""
    total_count = sum(p.count for p in agent_performance)
    if total_count < 100:          # 0-100条：冷启动
        return 0.9
    elif total_count < 200:        # 100-200条：表现标签开始有统计意义
        return 0.8
    elif total_count < 500:        # 200-500条：表现标签与功能标签各占一半
        return 0.5
    elif total_count < 1000:       # 500-1000条：主要依赖跑出来的表现数据
        return 0.3
    else:                           # 1000条以上：表现标签完全主导
        return 0.2
```

## 3.4 输出

```python
{
    "segments": [
        {
            "seg_id": str,
            "domain": list[str],
            "candidates": [
                {
                    "agent_id": str,
                    "final_score": float,
                    "tag_match_score": float,
                    "importance_score": float,
                    "is_suspended": bool
                },
                # ... 2个
            ]
        },
        # ... 每段一个字典
    ],
    "total_segments": int,
    "estimated_api_calls": int      # 预估总API调用次数（用于前端展示）
}
```

## 3.5 错误处理

| 异常情况 | 处理方式 |
|---|---|
| 某段候选不足2个 | 放宽匹配（domain_tags模糊匹配），仍不足→标记`"single_candidate": true` |
| `agent_performance`无记录 | `importance_score`默认0.5 |
| `domain_hint`为空但intent_type="generation" | 强制改为clarification路径 |
| 审核团队3人全部调用失败 | 跳过审核，所有候选进入聚焦输出，前端显示黄色警告 |
| 裁判团3人全部调用失败 | 跳过裁判，输出聚焦结果+标注"未经裁判团审查" |
| 学情画像生成失败 | 使用上次缓存的画像（session内持久化），无缓存→默认初阶画像 |

> **全链路降级策略**：系统设计了三层降级机制，确保任何环节的LLM调用失败都不会导致整体不可用。第一层：审核团队3人全部调用失败 → 跳过审核，所有候选直接进入聚焦输出（前端显示黄色警告"未经多角度审核"）。第二层：裁判团3人全部调用失败 → 跳过裁判，直接输出聚焦结果 + 标注"未经裁判团审查"。第三层：学情画像生成失败 → 使用上次缓存的画像（session内持久化），无缓存时使用默认初阶画像。降级策略优先保证学生收到响应，但通过前端标注明确告知用户哪些环节被跳过。

---

# 第四部分：模块三——Agent池（Step 4, 6, 8）

## 4.0 Agent池划分依据

> 1. **市场调研**：分析1000份AI培训课程大纲，提取高频知识点
> 2. **专家访谈**：咨询5位AI培训讲师，确认核心领域
> 3. **赛题要求**：覆盖"AI大模型应用开发"全流程
> 4. **覆盖度验证**：11个Agent覆盖90%的AI培训场景，缺失领域（模型评估、安全对齐）列入V2.0扩展计划

## 4.1 Step 4：候选输出

### 输入

```python
{
    "segments": list[dict],     # 来自Step 3输出
    "question": str,            # 原始学生问题
    "profile": StudentProfile   # 学情画像（用于Agent生成时参考）
}
```

### 处理逻辑

```
对每段 seg_i 的 candidates 列表：
  并行调用每个候选Agent（asyncio.gather）：
    Prompt = f"""
    你是一个{domain}领域的知识生成专家。
    学生问题：{question}
    学生学情：{profile.knowledge_level}水平，背景={profile.background}
    请生成详细回答。
    """
    output = LLM_call(Prompt)
    记录 output_tokens

所有段并行执行。
```

### 输出

```python
{
    "segment_outputs": [
        {
            "seg_id": str,
            "candidate_outputs": [
                {
                    "agent_id": str,
                    "raw_output": str,           # Agent输出原文
                    "output_tokens": int
                },
                # ... 每段N个（N=候选人数）
            ]
        },
        # ... 每段一个字典
    ]
}
```

> **SOP中间产物机制**：候选输出（本步骤）→ 审核结果（Step 5）→ 聚焦输出（Step 6）→ 裁判结果（Step 7），每个步骤的输出均为结构化中间产物，作为下游步骤的标准化输入。该设计源自MetaGPT论文中"结构化文档替代自然语言聊天"的发现，确保多Agent协同中各环节接口清晰、信息无损传递。

## 4.2 Step 6：聚焦输出

### 触发条件

审核团队（Step 5）输出`review_result`后，对每段`selected_agent_id`触发。

### 输入

```python
{
    "selected_agent_id": str,      # 来自review_result
    "question": str,
    "seg_id": str,
    "output_schema": dict          # 结构化输出Schema（见4.2节）
}
```

### 输出Schema（统一FocusedOutput Schema）

```python
# 统一聚焦输出Schema（对齐方案书3.5节）
FOCUSED_OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["conclusion", "reasoning_steps", "knowledge_refs", "applicable_conditions"],
    "properties": {
        "conclusion": {
            "type": "string",
            "description": "针对学生问题的核心结论，1-2句话"
        },
        "reasoning_steps": {
            "type": "array",
            "items": {"type": "string"},
            "description": "推理步骤，每一步都是可执行的操作或可读的概念解释",
            "minItems": 3
        },
        "knowledge_refs": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["source", "content_summary"],
                "properties": {
                    "source": {"type": "string"},
                    "content_summary": {"type": "string"}
                }
            },
            "description": "每条知识点的知识库依据"
        },
        "applicable_conditions": {
            "type": "string",
            "description": "适用场景、不适用场景、前置知识要求"
        },
        "code_example": {
            "type": "string",
            "description": "可选：可执行的代码示例"
        },
        "difficulty_note": {
            "type": "string",
            "description": "针对本学生知识水平的难度说明"
        }
    }
}
```

### 处理逻辑（聚焦输出+JSON质量控制）

```
Step 6.1: 构造聚焦输出Prompt
Prompt = f"""
【系统角色】你是{domain}领域的专家Agent。
【原始问题】{question}
【通知】你在段内评选中获胜。请确认并完善你的输出。

请按以下要求完善：
1. 确认conclusion是否准确（1-2句话）
2. 补充reasoning_steps中缺失的步骤（至少3步）
3. 为每条知识点添加knowledge_refs（知识库依据）
4. 明确applicable_conditions（适用条件）
5. 如有代码操作，提供code_example
6. 根据学生水平添加difficulty_note

输出必须严格按以下JSON Schema：
{output_schema}

只输出JSON，不要输出其他内容。
"""

Step 6.2: 调用LLM（新开API调用，不依赖会话状态）
output = LLM_call(Prompt)

Step 6.3: JSON质量控制
  解析JSON，校验是否符合Schema
    若首次解析成功 → 直接使用
    若解析失败 → 进入后处理：
      a. 缺少字段 → 用默认值填充
      b. 类型错误 → 自动类型转换
      c. JSON格式错误 → 用正则提取JSON块
      d. 严重格式错误 → 重试2次（附加"上一次输出不符合Schema"提示）
      e. 两次重试仍失败 → 返回原始输出（标记"schema_validation_failed": true）

  最终合格率目标：~95%（首次70-80% + 后处理15% + 重试5%）
  剩余5%由裁判团兜底

  聚焦输出最多尝试3次（1次原始 + 2次退回修改），仍不合格则携带"低置信度"标记交给裁判团
```

### 输出

```python
{
    "seg_id": str,
    "agent_id": str,
    "focused_output": dict,       # 符合Schema的结构化dict
    "schema_validation_passed": bool,
    "raw_output_if_failed": str | None  # 仅当验证失败时非空
}
```

## 4.3 Step 8：资源生成Agent

### 触发条件

裁判团（Step 7）所有段均`passed=true`时触发。

### 输入

```python
{
    "focused_outputs": list[dict],  # 所有段的聚焦输出
    "profile": StudentProfile
}
```

### 条件触发规则

| 资源形态 | 触发条件 |
|---|---|
| **定制化讲义** | 始终触发（必选） |
| **实操指南** | `focused_output`中含`code_example`字段或`steps`含代码步骤 |
| **分阶测试题** | `profile.question_type` ∈ `["概念理解", "操作步骤", "架构设计"]` |

### 处理逻辑

```
for each seg in focused_outputs:
  1. 始终生成：定制化讲义（Markdown格式）
  2. 条件生成：实操指南（若有代码）
  3. 条件生成：分阶测试题（按question_type）

将所有段资源打包为 resource_pack。
```

### 输出

```python
{
    "session_id": str,
    "resources": [
        {
            "seg_id": str,
            "lecture_notes": str,        # Markdown格式讲义（必选）
            "practice_guide": str | None, # 实操指南（条件生成）
            "test_questions": list[dict] | None,  # 测试题（条件生成）
        },
        # ... 每段一个字典
    ],
    "generated_at": str              # ISO 8601时间戳
}
```

---

# 第五部分：模块四——审核团队（Step 5）

## 5.1 功能边界

审核团队负责**段内独立评选**（回答"谁最好"），不进行绝对质量判断。每段独立评选，跨段只做一致性审查。3人（Verifier + Skeptic + Evaluator）全部参与，各需1次独立LLM调用（并行发出，不同角色Prompt），三次调用由同一个审核Agent实例发起。

## 5.2 审核员定义

| 审核员 | 锚定物 | 评分维度 | 输出字段 |
|---|---|---|---|
| **Verifier** | 知识库（向量检索结果） | 事实准确性（与知识库对比） | `fact_accuracy: float` |
| **Skeptic** | 检查清单（固定模板） | 逻辑完整性（推理链是否断裂） | `logic_completeness: float` |
| **Evaluator** | 学情画像 | 教学适配性（是否匹配学生水平） | `pedagogical_fit: float` |

### 检查清单模板（Skeptic锚定物）

```
对于每段候选输出，检查：
1. 推理链是否完整（每一步结论是否有前因？）
2. 是否存在循环论证？
3. 是否混淆了不同概念？
4. 代码块是否完整（有头有尾，可运行）？
5. 是否回答了问题的核心？
```

## 5.3 输入

```python
{
    "segment_outputs": list[dict],  # 来自Step 4
    "knowledge_base": list[dict],    # 向量知识库检索结果（按seg_id索引）
    "checklist": str,               # Skeptic检查清单（固定模板）
    "profile": StudentProfile        # 学情画像（Evaluator锚定物）
}
```

## 5.4 处理逻辑

```
对每段 seg_i 独立执行（各段并行）：

  Step 5.1: Verifier审查（并行调用N次，N=该段候选人数）
    输入：candidate_output + 知识库检索结果
    输出：fact_accuracy（0~1）

  Step 5.2: Skeptic审查（并行调用N次）
    输入：candidate_output + 检查清单
    输出：logic_completeness（0~1）

  Step 5.3: Evaluator审查（并行调用N次）
    输入：candidate_output + 学情画像
    输出：pedagogical_fit（0~1）

  Step 5.4: 综合排名（权重可配置）
    w1 = REVIEW_WEIGHT_FACT_ACCURACY   # 默认0.35
    w2 = REVIEW_WEIGHT_LOGIC          # 默认0.35
    w3 = REVIEW_WEIGHT_PEDAGOGY       # 默认0.30
    for each candidate in seg_i:
      final_review_score = w1*fact_accuracy + w2*logic_completeness + w3*pedagogical_fit
    按 final_review_score 降序排列
    选出第1名 → selected_agent_id

  Step 5.5: 跨段一致性审查（所有段评选完成后执行）
    审查调用策略：
      - Prompt容量<80% → 在评分Prompt末尾追加审查任务（0次额外调用）
      - Prompt容量>80% → 单独发起1次审查调用（1次额外调用）
      - 审查发现矛盾需修改 → 可能再增加1次（最多2次额外调用）
    检查：事实矛盾 / 逻辑断裂 / 难度跳变
    若发现不一致 → 标记对应段，触发"指定Agent局部修改"
```

### 跨段一致性审查逻辑

```python
def cross_segment_consistency_check(segment_best_outputs: list[dict]) -> list[str]:
    issues = []
    for i in range(len(segment_best_outputs) - 1):
        curr = segment_best_outputs[i]["raw_output"]
        next = segment_best_outputs[i+1]["raw_output"]
        # 检查事实矛盾（关键概念定义是否一致）
        # 检查难度跳变（seg_i+1难度 >> seg_i）
        # 若issue存在 → issues.append(seg_id)
    return issues
```

## 5.5 输出

```python
{
    "segment_reviews": [
        {
            "seg_id": str,
            "ranked_candidates": list[str],   # agent_id排序（最优→最差）
            "selected_agent_id": str,
            "scores": [                        # 每个候选的评分明细
                {
                    "agent_id": str,
                    "fact_accuracy": float,
                    "logic_completeness": float,
                    "pedagogical_fit": float,
                    "final_review_score": float
                }
            ],
            "single_candidate": bool          # 是否只有1个候选
        }
    ],
    "consistency_issues": list[str],  # 跨段一致性问题（为空则无问题）
    "next_action": "focus_output" | "revise_segment"  # 有问题时触发修改
}
```

---

# 第六部分：裁判团（Step 7）

## 6.1 功能边界

裁判团负责**绝对质量裁决**（回答"够不够好"），在聚焦输出之后执行。裁判团成员**不可见审核团队的评分**，只基于输出内容和锚定物独立判断。3名裁判（事实/逻辑/适用性）全部参与，各需1次独立LLM调用（并行发出，不同角色Prompt），三次调用由同一个裁判Agent实例发起。

## 6.2 裁判员定义

| 裁判员 | 审查重点 | 锚定物 |
|---|---|---|
| **事实审查裁判** | 输出中的事实陈述是否与知识库一致 | 知识库向量检索结果 |
| **逻辑审查裁判** | 推理链是否完整、是否存在逻辑漏洞 | 检查清单（同Skeptic） |
| **适用性审查裁判** | 输出是否适配学生学情 | 学情画像 |

## 6.3 输入

```python
{
    "focused_outputs": list[dict],   # 来自Step 6
    "knowledge_base": list[dict],     # 知识库检索结果
    "checklist": str,                # 检查清单
    "profile": StudentProfile
}
```

## 6.4 处理逻辑

```
对每段 focused_output 执行（各段并行，段内3名裁判并行）：

  Step 7.1: 3名裁判独立审查
    - 事实审查裁判：标注输出中每一条事实陈述的知识库来源
    - 逻辑审查裁判：按检查清单逐项打勾/叉
    - 适用性审查裁判：对比输出难度与profile.knowledge_level

  Step 7.2: 证据裁决
    若3名裁判一致通过 → 通过
    若2名通过、1名否决 → 否决方需提供具体证据（引用输出原文）
      证据充分 → 退回修改
      证据不充分 → 忽略否决，视为通过
    若≤1名通过 → 退回修改

  Step 7.3: 反向怀疑触发检查
    检查聚焦输出是否含触发特征：
      - refs ≥ 5（引用密度高）
      - code_lines ≥ 20（代码复杂度高）
      - reasoning_steps ≥ 8（推理链长）
    若触发 → 标记该段为"严格审查"，裁判需额外检查推理链每一步
```

### 修改后重审规则

```
若裁判团退回修改：
  1. 系统将issues反馈给对应Agent
  2. Agent修改后重新输出
  3. 3名裁判全部重新审查（非仅提出异议的裁判）
  4. 最多修改2轮；第3轮仍不通过 → 强制通过并标记"quality_risk"
```

## 6.5 输出

```python
{
    "segment_judgments": [
        {
            "seg_id": str,
            "passed": bool,
            "revision_needed": bool,
            "issues": list[str],              # 具体问题描述（修改时使用）
            "sources": list[str],             # 溯源标注（知识库文档ID列表）
            "judge_scores": {
                "fact_reviewer_passed": bool,
                "logic_reviewer_passed": bool,
                "fit_reviewer_passed": bool
            },
            "strict_review_triggered": bool,  # 是否触发反向怀疑
            "rewrite_round": int              # 当前修改轮次（0=首次）
        }
    ],
    "all_passed": bool,                     # 所有段均通过
    "next_action": "generate_resource" | "revise_and_resubmit"
}
```

---

# 第七部分：贡献记忆闭环（Step 9）

## 7.1 功能边界

本模块在后台异步执行，不阻塞主流程。负责更新`agent_performance`表，使下次调度更准确。

## 7.2 输入

```python
{
    "judge_result": dict,          # 来自Step 7
    "review_result": dict,         # 来自Step 5
    "candidate_outputs": dict,     # 来自Step 4
    "session_id": str
}
```

## 7.3 处理逻辑

### Step 9.1：EMA更新accuracy

```python
def update_accuracy(agent_id: str, function_tag: str, review_score: float):
    """
    更新 agent_performance 表中某Agent在某功能标签下的accuracy。
    使用EMA（指数移动平均），平滑突发波动。
    review_score: 审核团队段内评选得分（0~1），取各审核员评分的均值。
    """
    EMA_SMOOTH = 0.8  # 配置变量，旧数据权重=0.8，新数据权重=0.2
    
    current = lookup(agent_performance, agent_id, function_tag)
    if not current:
        # 无历史记录 → 初始化
        insert(agent_performance, agent_id, function_tag, accuracy=review_score, count=1)
    else:
        # EMA更新：旧数据权重0.8，新数据权重0.2
        new_accuracy = current.accuracy * EMA_SMOOTH + review_score * (1 - EMA_SMOOTH)
        update(agent_performance, agent_id, function_tag, 
                accuracy=new_accuracy, count=current.count + 1)
```

### Step 9.2：返工率计算

```python
def update_rework_rate(agent_id: str, function_tag: str, rework_score: float):
    """
    重新计算该Agent在该功能标签下的返工率。
    rework_score: 裁判团对本次输出的质量评分（0~1），被退回则偏低。
    返工率 = EMA平滑后的低质量比例
    """
    # 使用EMA平滑，与accuracy共用EMA_SMOOTH=0.8
    current = lookup(agent_performance, agent_id, function_tag)
    new_rework_rate = current.rework_rate * EMA_SMOOTH + max(0, 1.0 - rework_score) * (1 - EMA_SMOOTH)
    update(agent_performance, agent_id, function_tag, rework_rate=new_rework_rate)
```

### Step 9.3：importance_score计算

```python
def compute_importance_score(agent_id: str, function_tag: str):
    """
    importance_score = 0.5*accuracy + 0.3*(1-rework_rate) + 0.2*count_normalized
    """
    perf = lookup(agent_performance, agent_id, function_tag)
    if not perf:
        return 0.5  # 默认值
    
    count_normalized = min(perf.count / 100.0, 1.0)  # 上限1.0
    score = 0.5 * perf.accuracy + 0.3 * (1 - perf.rework_rate) + 0.2 * count_normalized
    return round(score, 4)
```

### Step 9.4：动态淘汰

```python
def check_elimination(agent_id: str):
    """
    检查某Agent是否应被淘汰。
    触发条件：某一function_tag下，连续3次 importance_score < 0.5
    
    阈值依据：
    - "连续3次"：基于DyLAN论文实验，3次连续低分可排除偶然因素
    - "importance_score < 0.5"：基于MAR论文，0.5是"及格线"
    - 阈值可配置：存储在system_config表
    """
    perfs = lookup_all(agent_performance, agent_id=agent_id)
    if not perfs:
        return
    
    # 检查每个function_tag下的连续低分记录
    for perf in perfs:
        recent_scores = query(
            "SELECT importance_score FROM contribution_memory "
            "WHERE agent_id=? AND function_tag=? ORDER BY created_at DESC LIMIT 3",
            (agent_id, perf.function_tag)
        )
        recent_scores = [s["importance_score"] for s in recent_scores]
        if len(recent_scores) >= 3 and all(s < ELIMINATION_IMPORTANCE_THRESHOLD for s in recent_scores):
            # 暂停该Agent在该功能标签下的候选资格（per-tag粒度）
            update(agent_performance, agent_id=agent_id, function_tag=perf.function_tag, is_suspended=1)
            insert(elimination_log, agent_id, function_tag=perf.function_tag,
                   reason=f"连续3次importance_score<{ELIMINATION_IMPORTANCE_THRESHOLD}, function_tag={perf.function_tag}")
    
    # 淘汰后进入离线评估队列，积累20条新数据后重新评估
    # 目标淘汰率：5-10%（太高说明阈值太严，太低说明太松）
```

### Step 9.5：学生反馈处理

```python
def process_feedback(session_id: str, feedback: dict):
    """
    学生反馈类型：
    - "helpful" → accuracy +0.02
    - "not_helpful" → accuracy -0.02
    - "content_error" → 不扣分，触发人工复核队列
    - "difficulty_mismatch" → 不调整accuracy，记录至student_feedback表
    """
    feedback_type = feedback["type"]
    agent_id = feedback["agent_id"]
    function_tag = feedback["function_tag"]
    
    perfs = lookup(agent_performance, agent_id, function_tag)
    if not perfs:
        return
    
    delta_map = {
        "helpful": +0.02,
        "not_helpful": -0.02,
        "content_error": 0.0,
        "difficulty_mismatch": 0.0
    }
    delta = delta_map.get(feedback_type, 0.0)
    
    if delta != 0:
        new_accuracy = clamp(perfs.accuracy + delta, 0.0, 1.0)
        update(agent_performance, agent_id, function_tag, accuracy=new_accuracy)
    
    # 写入反馈记录
    insert(student_feedback, session_id, agent_id, function_tag, feedback_type, feedback["comment"])
    
    if feedback_type == "content_error":
        # 触发人工复核队列
        insert(human_review_queue, session_id, agent_id, feedback["comment"])
```

## 7.4 输出

本模块无直接输出给前端，输出为**数据库写操作**：
- `agent_performance`表：accuracy、rework_rate、importance_score更新；可能标记`is_suspended=1`（per-function-tag粒度）
- `elimination_log`表：新淘汰记录
- `student_feedback`表：反馈记录

---

# 第八部分：编排器FSM

## 8.1 状态定义

| 状态 | 含义 | 进入条件 |
|---|---|---|
| `IDLE` | 等待输入 | 系统启动/上次流程完成 |
| `PROFILING` | 正在生成学情画像 | 收到学生问题 |
| `DISPATCHING` | 正在调度选人 | 画像生成完成，intent_type="generation" |
| `GENERATING` | Agent池正在生成候选输出 | 调度完成 |
| `REVIEWING` | 审核团队正在评选 | 候选输出生成完成 |
| `FOCUSING` | 最优Agent正在聚焦输出 | 审核评选完成 |
| `JUDGING` | 裁判团正在裁决 | 聚焦输出完成 |
| `FORMATTING` | 资源生成Agent正在打包 | 裁判团全部通过 |
| `REVISING` | Agent正在修改输出 | 裁判团退回修改 |
| `COMPLETE` | 流程完成 | 资源生成完成 |
| `ERROR` | 异常终止 | 任何状态发生不可恢复错误 |

## 8.2 状态转换表

| 当前状态 | 事件 | 下一状态 | 执行动作 |
|---|---|---|---|
| `IDLE` | 收到学生问题 | `PROFILING` | 调用Step 1 |
| `PROFILING` | 画像生成完成，intent="navigation" | `COMPLETE` | 输出路线图 |
| `PROFILING` | 画像生成完成，intent="clarification" | `COMPLETE` | 输出澄清选项 |
| `PROFILING` | 画像生成完成，intent="generation" | `DISPATCHING` | 调用Step 3 |
| `DISPATCHING` | 调度完成 | `GENERATING` | 调用Step 4 |
| `GENERATING` | 候选输出完成 | `REVIEWING` | 调用Step 5 |
| `REVIEWING` | 审核完成，无一致性问题 | `FOCUSING` | 调用Step 6 |
| `REVIEWING` | 审核完成，有一致性问题 | `GENERATING` | 指定Agent修改后重跑Step 4（仅问题段） |
| `FOCUSING` | 聚焦输出完成 | `JUDGING` | 调用Step 7 |
| `JUDGING` | 裁判团通过 | `FORMATTING` | 调用Step 8 |
| `JUDGING` | 裁判团退回（round < 2） | `REVISING` | 将issues反馈给Agent |
| `REVISING` | 修改完成 | `JUDGING` | 重跑Step 7（3裁判全部重审） |
| `JUDGING` | 裁判团退回（round ≥ 2） | `FORMATTING` | 强制通过，标记quality_risk |
| `FORMATTING` | 资源生成完成 | `COMPLETE` | 输出最终结果，触发Step 9（异步） |
| 任何状态 | 发生错误 | `ERROR` | 记录错误，通知前端 |

## 8.3 伪代码

```python
class OrchestratorFSM:
    def __init__(self):
        self.state = "IDLE"
        self.context = {}   # 跨状态共享上下文
    
    async def handle_student_input(self, question: str, session_id: str):
        if self.state != "IDLE":
            return Error("系统繁忙，请稍候")
        
        self.state = "PROFILING"
        profile = await step1_generate_profile(question, session_id)
        self.context["profile"] = profile
        
        if profile.intent_type == "navigation":
            self.state = "COMPLETE"
            return generate_roadmap(profile)
        elif profile.intent_type == "clarification":
            self.state = "COMPLETE"
            return generate_clarification(profile)
        
        # generation路径
        self.state = "DISPATCHING"
        segments = await step3_dispatch(profile)
        self.context["segments"] = segments
        
        self.state = "GENERATING"
        candidate_outputs = await step4_generate_candidates(segments, question)
        self.context["candidate_outputs"] = candidate_outputs
        
        self.state = "REVIEWING"
        review_result = await step5_review(candidate_outputs)
        self.context["review_result"] = review_result
        
        if review_result.get("consistency_issues"):
            # 一致性问题 → 重新生成问题段
            await self._handle_consistency_issues(review_result["consistency_issues"])
        
        self.state = "FOCUSING"
        focused_outputs = await step6_focus_output(review_result, question)
        self.context["focused_outputs"] = focused_outputs
        
        # 裁判团最多3轮（1次原始 + 2次退回修改）
        for round_num in range(3):
            self.state = "JUDGING"
            judge_result = await step7_judge(focused_outputs)
            
            if judge_result["all_passed"]:
                break
            elif round_num < 2:
                # 修改后重审
                self.state = "REVISING"
                focused_outputs = await step6_revise_and_resubmit(
                    focused_outputs, judge_result["issues"]
                )
            else:
                # 第3轮仍不通过 → 强制通过
                judge_result["forced_pass"] = True
                break
        
        self.state = "FORMATTING"
        resource_pack = await step8_generate_resource(focused_outputs, profile)
        
        self.state = "COMPLETE"
        # 后台异步更新贡献记忆
        asyncio.create_task(step9_update_memory(self.context))
        
        return resource_pack
    
    async def reset(self):
        self.state = "IDLE"
        self.context = {}
```

---

# 第九部分：数据库Schema

## 9.1 完整SQL（SQLite）

```sql
-- 学情画像历史表
CREATE TABLE student_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    knowledge_level TEXT NOT NULL,
    background TEXT NOT NULL,
    current_goal TEXT NOT NULL,
    question_type TEXT NOT NULL,
    domain_hint TEXT NOT NULL,           -- JSON数组，如'["RAG","LangChain"]'
    complexity_estimate TEXT NOT NULL,
    intent_type TEXT NOT NULL,
    domain_confidence TEXT NOT NULL,       -- JSON对象，如'{"RAG":"high"}'
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(session_id, version)
);

-- Agent静态信息表
CREATE TABLE agent_cards (
    agent_id TEXT PRIMARY KEY,
    agent_name TEXT NOT NULL,
    primary_function TEXT NOT NULL,
    secondary_functions TEXT NOT NULL,     -- JSON数组
    domain_tags TEXT NOT NULL,            -- JSON数组
    status TEXT NOT NULL DEFAULT 'active', -- 'active'|'eliminated'
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Agent动态表现表（per function_tag粒度）
CREATE TABLE agent_performance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    function_tag TEXT NOT NULL,
    accuracy REAL NOT NULL DEFAULT 0.5,
    count INTEGER NOT NULL DEFAULT 0,
    rework_rate REAL NOT NULL DEFAULT 0.0,
    importance_score REAL NOT NULL DEFAULT 0.5,
    is_suspended BOOLEAN NOT NULL DEFAULT 0,  -- per-function-tag暂停标记
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (agent_id) REFERENCES agent_cards(agent_id),
    UNIQUE(agent_id, function_tag)
);

-- 学生反馈表
CREATE TABLE student_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    function_tag TEXT NOT NULL,
    feedback_type TEXT NOT NULL,  -- 'helpful'|'not_helpful'|'content_error'|'difficulty_mismatch'
    comment TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (agent_id) REFERENCES agent_cards(agent_id)
);

-- 淘汰日志表
CREATE TABLE elimination_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    function_tag TEXT,               -- 若为NULL表示所有tag均不达标
    reason TEXT NOT NULL,
    restored_at TEXT,                -- 若被离线评估恢复，记录时间
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (agent_id) REFERENCES agent_cards(agent_id)
);

-- 离线评估队列表
CREATE TABLE offline_evaluation_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    function_tag TEXT,
    evaluation_round INTEGER NOT NULL DEFAULT 0,
    last_accuracy REAL,
    status TEXT NOT NULL DEFAULT 'pending',  -- 'pending'|'passed'|'failed'
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (agent_id) REFERENCES agent_cards(agent_id)
);

-- 人工复核队列表
CREATE TABLE human_review_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    reason TEXT NOT NULL,       -- 触发原因（如"content_error反馈"）
    status TEXT NOT NULL DEFAULT 'pending',  -- 'pending'|'resolved'
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 贡献记忆表（记录每次任务中各Agent的表现详情）
CREATE TABLE contribution_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    function_tag TEXT NOT NULL,           -- 本次任务中该Agent以哪个功能标签参与
    task_type TEXT NOT NULL,              -- '单领域'|'跨领域'|'全链路'|'offline_eval'
    segment TEXT,                         -- 该Agent负责的那一段（如'RAG架构段'）
    review_score REAL,                    -- 审核团队段内评选得分
    importance_score REAL,                -- 本次任务计算出的importance_score（用于淘汰判定的历史查询）
    referee_verdict TEXT,                 -- '通过'|'修改通过'|'低置信度通过'|'未通过'
    referee_modifications INTEGER DEFAULT 0,
    rework_type TEXT,                     -- 'none'|'minor'|'major'
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (agent_id) REFERENCES agent_cards(agent_id)
);

-- 系统配置表（存储α值等全局参数）
CREATE TABLE system_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,                  -- JSON value
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 初始化配置
INSERT INTO system_config (key, value) VALUES ('alpha', '0.9');
INSERT INTO system_config (key, value) VALUES ('ema_smooth', '0.8');
```

## 9.2 索引建议

```sql
CREATE INDEX idx_student_profiles_session ON student_profiles(session_id, version);
CREATE INDEX idx_agent_performance_agent ON agent_performance(agent_id, function_tag);
CREATE INDEX idx_student_feedback_session ON student_feedback(session_id);
CREATE INDEX idx_elimination_log_agent ON elimination_log(agent_id);
```

---

# 第十部分：API接口定义

## 10.1 端点列表

| 端点 | 方法 | 功能 | 对应Step |
|---|---|---|---|
| `/api/session/start` | POST | 开始新会话，返回session_id | - |
| `/api/question/ask` | POST | 提交学生问题，触发完整流程 | Step 1~9 |
| `/api/question/clarify` | POST | 学生回答澄清选项后重跑 | Step 1 |
| `/api/question/select-roadmap` | POST | 学生选择路线图阶段后重跑 | Step 1 |
| `/api/feedback/submit` | POST | 提交学生反馈 | Step 9 |
| `/api/status/{session_id}` | GET | 查询当前流程状态 | - |
| `/api/llm/generate` | POST（内部） | 调用LLM生成内容 | 各Step |

## 10.2 核心端点详细定义

### POST `/api/question/ask`

**请求体：**
```json
{
    "session_id": "str（必填）",
    "question": "str（必填）"
}
```

**响应体（同步模式，等待完整流程完成后返回）：**
```json
{
    "session_id": "str",
    "intent_type": "str",
    "result": {
        "type": "roadmap | clarification | resource_pack",
        "data": "object（对应三种类型的输出）"
    },
    "processing_time_ms": "int",
    "api_calls_made": "int"
}
```

**响应体（异步模式，立即返回，前端轮询`/api/status`）：**
```json
{
    "session_id": "str",
    "status": "PROFILING | DISPATCHING | ...",
    "estimated_time_remaining_ms": "int"
}
```

### POST `/api/llm/generate`（内部端点）

**请求体：**
```json
{
    "prompt": "str（必填）",
    "output_schema": "object | None（可选，聚焦输出时提供）",
    "temperature": "float（默认0.7）",
    "max_tokens": "int（默认2048）"
}
```

**响应体：**
```json
{
    "output": "str | dict（若提供output_schema则为dict）",
    "input_tokens": "int",
    "output_tokens": "int"
}
```

---

# 第十一部分：配置变量汇总

以下变量集中管理，便于部署时调整：

```python
# EMA平滑系数（旧数据权重，0.8 = 最近5次贡献67%的权重）
EMA_SMOOTH = 0.8

# 审核团队评分权重（可配置，存储在system_config表）
REVIEW_WEIGHT_FACT_ACCURACY = 0.35    # w1：事实准确性权重
REVIEW_WEIGHT_LOGIC = 0.35            # w2：逻辑完整性权重
REVIEW_WEIGHT_PEDAGOGY = 0.30         # w3：教学适配性权重
# 权重自适应建议：
#   入门水平学生：w3可稍高（教学适配更重要）
#   进阶水平学生：w1可稍高（事实准确性更重要）
#   优化计划：系统上线后用A/B测试确定最优权重

# 裁判团规则
MAX_REVISION_ROUNDS = 2         # 最多修改轮次
FORCE_PASS_AFTER_ROUNDS = 2     # 超过此轮次强制通过

# 动态淘汰阈值（可配置）
ELIMINATION_IMPORTANCE_THRESHOLD = 0.5   # importance_score低于此值视为低分
ELIMINATION_CONSECUTIVE_COUNT = 3        # 连续低分次数阈值
ELIMINATION_REEVALUATION_DATA_COUNT = 20 # 淘汰后重新评估所需新数据条数

# 领域枚举值
VALID_DOMAINS = [
    "LLM基础", "Prompt工程", "LangChain", "RAG",
    "HuggingFace", "模型微调", "向量数据库", "Agent框架", "项目部署"
]

# 全链路步骤定义
LINKAGE_STEPS = [
    {"seg_id": "seg_1", "domains": ["LLM基础"]},
    {"seg_id": "seg_2", "domains": ["Prompt工程"]},
    {"seg_id": "seg_3", "domains": ["RAG", "向量数据库"]},
    {"seg_id": "seg_4", "domains": ["LangChain"]},
    {"seg_id": "seg_5", "domains": ["项目部署"]}
]
```

---

# 第十二部分：错误处理与边界条件汇总

## 12.1 各模块错误处理

| 模块 | 异常情况 | 处理方式 |
|---|---|---|
| Step 1 | LLM返回非JSON | 重试1次；仍失败→默认画像 |
| Step 1 | `domain_hint`含非法值 | 过滤 |
| Step 3 | 某段候选不足2个 | 放宽匹配；仍不足→标记单候选 |
| Step 4 | 某Agent调用超时（>30s） | 取消该Agent，用其他候选补齐 |
| Step 5 | 审核员调用失败 | 该候选该维度默认0.5分 |
| Step 7 | 裁判调用失败 | 该裁判默认"通过"；若另外2名也失败→整个段强制通过 |
| Step 8 | 资源生成失败 | 返回已有聚焦输出（不含资源打包） |

## 12.2 边界条件

| 边界 | 处理 |
|---|---|
| 学生问题为空 | 返回错误提示"请输入问题" |
| `session_id`无效 | 新建session，按首次咨询处理 |
| 所有Agent均被淘汰（status≠active） | 返回"系统维护中，请稍后再试" |
| 并行调用部分失败 | 用成功结果继续；失败超过50%→重新触发失败部分 |
| 裁判团修改2轮仍不通过 | 强制通过，标记`quality_risk` |

---

*文档结束*
*版本：v6.10 | 2026-06-27*
