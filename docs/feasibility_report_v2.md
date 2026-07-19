# 方案书 v6.16 第二次可行性全面检查报告

> 检查对象：`proposal.md` v6.16（2026-07-13，3614行）
> 检查范围：全文（第一至第十一部分 + 附录A-E）
> 检查维度：技术可行性 · 逻辑一致性 · 架构连通性 · 实现合理性 · Schema完整性 · 伪代码与设计描述一致性 · 数据流闭环 · 潜在矛盾与风险
> 检查日期：2026-07-13

---

## 总览

| 严重度 | 数量 | 说明 |
|--------|------|------|
| 🔴 严重 | 4 | 逻辑断裂/数据矛盾，必须修复 |
| 🟡 部分 | 9 | 表述歧义/设计不完整，建议修复 |
| 🟢 微小 | 3 | 格式/措辞/建议性，可选择性修复 |
| **合计** | **16** | 较v6.15第一轮(5🔴+10🟡+4🟢=19)减少3项，🔴项从5→4 |

> **与第一轮对比**：v6.15第一轮发现的5🔴+10🟡+4🟢=19项已全部修复。本轮4🔴均为v6.16修复后新引入或此前遗漏的问题，9🟡多为伪代码层面的设计完整性问题。

---

## 🔴 严重问题（4项）

### 🔴-1：文档标题版本号未更新

**位置**：行3  
**现状**：标题写 `## 比赛方案书 v6.15`  
**应值**：`## 比赛方案书 v6.16`（行8页脚和行3613末尾均已更新为v6.16）  
**影响**：读者看到标题会误认为文档仍为v6.15版本，与实际内容不一致  
**修复**：行3改为 `## 比赛方案书 v6.16`

---

### 🔴-2：JudgeVerdict内层`judgment`枚举与顶层`verdict`枚举矛盾

**位置**：6.2.3节 JudgeVerdict JSON Schema（行2270-2322）  
**现状**：
- 顶层 `verdict` 字段：`enum: ["passed", "revise", "low_confidence_passed", "failed"]`（4值，英文）
- 内层 `judges[].judgment` 字段：`enum: ["pass", "fail"]`（2值，英文）

**矛盾点**：
1. **命名不一致**：`pass` ≠ `passed`，`fail` ≠ `failed`。同一Schema内两个相关字段使用不同命名风格
2. **值域不一致**：judge只能输出pass/fail（2值），但顶层verdict可以是revise/low_confidence_passed（4值）。**2值→4值映射规则缺失**——3名裁判各自给出pass/fail，如何映射到revise或low_confidence_passed？例如：2pass+1fail → 应为passed还是revise？1pass+2fail → 应为failed还是low_confidence_passed？

**影响**：裁判团裁决逻辑无法从judgment字段推导verdict字段，数据流断裂  
**修复建议**：
- 方案A（推荐）：统一枚举值体系。`judgment` 改为 `enum: ["passed", "revise", "low_confidence_passed", "failed"]`，与顶层verdict完全一致。裁判独立审查时即可给出4值判定，resolve_judgment汇总时取最严判定（如有1个failed→整体failed，如有1个revise且无failed→整体revise，全部passed→整体passed）
- 方案B：补充映射规则说明。例如："3名裁判judgment汇总规则：3pass→passed, 2pass+1fail→revise, 1pass+2fail→low_confidence_passed, 3fail→failed"

---

### 🔴-3：修退机制伪代码无效——verdict=revise时无修改步骤

**位置**：6.1.2节编排器伪代码（行2093-2105）  
**现状**：
```python
elif state == "JUDGING":
    verdicts = await asyncio.gather(*[judge.judge(focused, profile) for judge in self.referees])
    result = self.resolve_judgment(verdicts)
    if result["passed"]:
        state = "FORMATTING"
    elif result["revise"] and result["revision_count"] < 2:
        result["revision_count"] += 1  # 修改次数递增，上限2次
        state = "JUDGING"  # 修改后直接重审
    else:
        state = "FORMATTING"  # 低置信度强制通过
```

**问题**：
1. **无修改步骤**：当verdict=revise时，伪代码直接设 `state = "JUDGING"` 重入裁判团，但**没有修改focused output的代码行**。未修改的同一输出再次送审，大概率产出相同verdict，2次空转后强制FORMATTING——修退机制名存实亡
2. **REVISING状态未被使用**：FSM定义（6.1.1节行1941）明确列出 `[REVISING] → Agent修改FocusedOutput后回到JUDGING重审`，但伪代码从未进入REVISING状态

**影响**：裁判团"退回修改"功能形同虚设，2次修改机会变成2次对同一内容的无效重审  
**修复建议**：在 `elif result["revise"]` 分支中补充修改步骤：
```python
elif result["revise"] and result["revision_count"] < 2:
    result["revision_count"] += 1
    # 退回修改：Agent根据裁判团反馈修改focused output
    focused = await agent.revise_focused_output(focused, result["revision_feedback"])
    state = "JUDGING"  # 修改后重审
```

---

### 🔴-4：A.5裁判Prompt输出`confidence`字段类型与Schema矛盾

**位置**：
- Schema定义：6.2.3节行2285 `"confidence": {"type": "number", "description": "系统内部记录，对外隐藏"}`
- Prompt模板：附录A.5行3415 `"confidence": "高 / 中 / 低"`

**矛盾**：Schema声明confidence为**number**类型（0.0-1.0数值），但Prompt要求裁判输出**中文字符串**（"高/中/低"）。JSON解析时类型不匹配必然报错。

**影响**：裁判团输出的JSON无法通过JudgeVerdict Schema校验，整个裁判团阶段数据流断裂  
**修复建议**（选一）：
- 方案A（推荐）：统一为number类型。Prompt改为 `"confidence": 0.0-1.0`（数值置信度），Schema保持number类型不变。裁判输出数值，系统内部记录，对外隐藏
- 方案B：统一为字符串类型。Schema改为 `"confidence": {"type": "string", "enum": ["high", "medium", "low"]}`，Prompt改为 `"confidence": "high / medium / low"`（英文枚举，遵循英文原则）

---

## 🟡 部分覆盖问题（9项）

### 🟡-1：FOCUSING伪代码缺`review_feedback`参数

**位置**：6.1.2节行2088  
**现状**：`agent.focused_output(question, profile)` — 只传入问题和画像  
**应值**：3.5节设计要求聚焦输出接收审核反馈做"赢者精进"改进，应传入 `review_feedback`  
**影响**：伪代码与3.5节核心设计意图（MAR反馈回流）矛盾  
**修复**：改为 `agent.focused_output(question, profile, review_feedback)`

---

### 🟡-2：核心方法`select_best`/`resolve_judgment`未定义

**位置**：6.1.2节行2072、2098  
**现状**：伪代码调用 `self.select_best(review_results, outputs)` 和 `self.resolve_judgment(verdicts)` 但无任何算法说明  
**影响**：select_best涉及3维评分加权算法，resolve_judgment涉及DISSENT_RESOLVE状态机+候选辩论——两者是系统核心逻辑，省略使伪代码无法理解  
**修复**：补充方法说明注释或伪代码片段：
- `select_best`：加权总分 = 0.4×fact_accuracy + 0.3×logic_completeness + 0.3×pedagogical_fit，取每段最高分Agent
- `resolve_judgment`：3人verdict汇总→一致passed→直接通过；2:1分歧→触发DISSENT_RESOLVE（4.4.2节）+候选辩论

---

### 🟡-3：traceability `verification_status`使用中文枚举

**位置**：6.2.3节行2316  
**现状**：`"verification_status": {"type": "string", "enum": ["已验证", "待验证", "矛盾"]}`  
**矛盾**：5.0节明确声明"JSON Schema和数据库中统一使用英文枚举值"，但verification_status用中文  
**影响**：与verdict英文枚举原则不一致，降低数据规范性  
**修复**：改为 `"verification_status": {"type": "string", "enum": ["verified", "unverified", "contradictory"]}`，前端展示时映射中文

---

### 🟡-4：RECHECK通过路径跳过HEURISTIC_FOLLOWUP

**位置**：6.1.1节行1960、6.1.2节伪代码行2173  
**现状**：RECHECK复检通过后直接 `return {"response": "经复检确认内容正确", "followup": None}`，不进入HEURISTIC_FOLLOWUP  
**逻辑缺陷**：学生主动报告"内容有误"说明其正在深度思考，复检确认正确后追问（如"你能解释为什么XX和YY的关系是这样的吗？"）有更高教学价值。其他延伸路径（REDIMENSION/ADVANCE）都指向HEURISTIC_FOLLOWUP，唯独RECHECK跳过  
**修复**：RECHECK通过后也进入HEURISTIC_FOLLOWUP，追问引导学生反思"为什么最初认为有误"

---

### 🟡-5：JUDGING伪代码过于简化

**位置**：6.1.2节行2093-2105  
**现状**：JUDGING块只有3行——3人并行judge + resolve_judgment + if/else分支  
**缺失**：4.4.2节详细设计了DISSENT_RESOLVE状态机（少数方举证→多数方回应→僵持→裁判长裁决）+候选辩论证据消费路径（辩论证据作为"第三方专家意见"追加至裁判审查Prompt），但伪代码完全不反映这些核心机制  
**影响**：读者无法从伪代码理解裁判团的完整工作流程  
**修复**：补充注释说明resolve_judgment的内部逻辑：
```python
# resolve_judgment内部逻辑（见4.4.2节）：
# 1. 3人verdict汇总
# 2. 一致passed → 直接通过
# 3. 2:1分歧 → 触发DISSENT_RESOLVE（少数方举证→多数方回应）
# 4. 分歧+候选辩论 → 落选候选质疑+获胜候选辩护，证据合并提交裁判团
# 5. 证据充分 → REVISING（退回修改）
# 6. 证据不足 → PASSED（维持原判）
```

---

### 🟡-6：CandidateOutput.answer无required字段

**位置**：6.2.4节行2338-2349  
**现状**：answer对象定义了6个properties但无required字段，description说"不强制必填所有字段"  
**对比**：FocusedOutput Schema明确标注4个required字段（conclusion/reasoning_steps/knowledge_refs/applicable_conditions）  
**影响**：审核团队评分时需知道Agent至少应输出哪些字段（否则Agent可以只输出一个conclusion就提交），缺乏最低质量保障  
**修复**：标注最低required字段（如 `required: ["conclusion", "reasoning_steps"]`），其余可选

---

### 🟡-7：ResourcePackage中quiz字段使用中文枚举

**位置**：6.2.5节行2400-2415  
**现状**：
- `difficulty: enum: ["基础", "应用", "进阶"]`
- `type: enum: ["判断", "选择", "简答", "代码补全", "设计分析"]`

**矛盾**：与verdict英文枚举原则不一致。虽然quiz是面向学生的教育术语（中文可能更友好），但5.0节声明"JSON Schema中统一使用英文"  
**修复建议**：改为英文枚举 + 前端中文映射：
- `difficulty: enum: ["basic", "applied", "advanced"]`
- `type: enum: ["true_false", "multiple_choice", "short_answer", "code_completion", "design_analysis"]`

---

### 🟡-8：SOP Stage-FSM状态映射缺失

**位置**：6.2.1节  
**现状**：6个Stage（1-6）列出产物名称，但未标注对应的FSM状态  
**读者推断**：Stage 1=PROFILING, Stage 2=GENERATING, Stage 3=REVIEWING, Stage 4=FOCUSING, Stage 5=JUDGING, Stage 6=FORMATTING  
**影响**：SOP链与FSM是方案书两大核心设计，映射关系应明确标注而非依赖推断  
**修复**：6.2.1节补充映射表：
```
Stage 1 (StudentProfile)    ← PROFILING 状态产出
Stage 2 (CandidateOutput)   ← GENERATING 状态产出
Stage 3 (ReviewFeedback)    ← REVIEWING 状态产出
Stage 4 (FocusedOutput)     ← FOCUSING 状态产出
Stage 5 (JudgeVerdict)      ← JUDGING 状态产出
Stage 6 (ResourcePackage)   ← FORMATTING 状态产出
```

---

### 🟡-9：枚举值层级策略不一致

**位置**：domain_confidence（2值high/low）vs severity（3值high/medium/low）vs verdict（4值）  
**现状**：
- domain_confidence：只有high/low两档（行256明确声明"不使用medium，简化调度逻辑"）
- ReviewFeedback.severity：high/medium/low三级（行2242）
- verdict：passed/revise/low_confidence_passed/failed四级

**矛盾**：同一方案书对不同字段采用不同枚举层级策略（2值/3值/4值），缺乏统一设计哲学说明  
**影响**：读者无法判断为何domain_confidence简化为2值而severity保留3值  
**修复**：补充统一说明（如在6.2节开头加注）：
> **枚举值设计原则**：domain_confidence简化为2值（high/low）因为调度逻辑需快速二分决策；severity保留3值（high/medium/low）因为审核问题严重程度需中间档区分"需立即修改"与"建议优化"；verdict保留4值因为裁判团需精确区分"完全通过/需微调/勉强通过/不通过"四种质量状态。各字段枚举层级根据功能需求而定，非一刀切。

---

## 🟢 微小问题（3项）

### 🟢-1：QUIZ_EVAL伪代码逻辑内联

**位置**：6.1.2节行2130-2153  
**现状**：handle_extension伪代码将QUIZ_EVAL判定逻辑（正确率计算→方向判定）嵌入event_type分支，而非作为独立状态处理块  
**对比**：FSM定义6.1.1节将QUIZ_EVAL描述为有独立处理逻辑的状态  
**影响**：功能正确但结构描述与FSM定义略有出入  
**修复**：可选择性重构为独立状态处理块（非必须）

---

### 🟢-2：handle_extension未区分"轻度降维"与"重度降维"

**位置**：6.1.2节行2135-2140  
**现状**：quiz_submit事件中，正确率60%-85%和<60%都指向REDIMENSION，但FSM定义6.1.1节区分了"轻度降维"（60%-85%）和"重度降维"（<60%）  
**影响**：降维策略差异（入门级8小步拆解 vs 中级级加过渡概念）在伪代码中被抹平  
**修复**：REDIMENSION处理块中传入降维等级参数（如`reduction_level="light"/"heavy"`），资源Agent根据等级选择不同降维Prompt

---

### 🟢-3：CandidateOutput.answer最低期望字段未标注

**位置**：6.2.4节行2340  
**现状**：description说"与FocusedOutput一致，但不强制必填所有字段"，但未说明审核团队评分时期望Agent至少输出哪些字段  
**影响**：审核团队无法确定评分底线  
**修复**：description补充："最低期望：conclusion + reasoning_steps（至少3步），其余字段可选但评分时作为加分项"

---

## 一致性交叉验证

| 检查项 | 结果 | 说明 |
|--------|------|------|
| verdict英文枚举一致性 | ✅ 已统一 | JudgeVerdict Schema + contribution_memory表 + 模块输入规格均为英文枚举 |
| domain_confidence值一致性 | ✅ 已统一 | 全文仅high/low两档，Grep确认无medium误用 |
| SOP链声称与实际定义 | ✅ 已匹配 | 6个Schema全部在6.2.1-6.2.5节有正式定义 |
| FSM状态与伪代码 | ⚠️ 部分一致 | 主FSM8个状态匹配，但REVISING未在伪代码中流转（🔴-3） |
| 辩论证据消费路径 | ✅ 完整 | 4.4.2节有完整流程描述 |
| 跨段审查局部修复 | ✅ 已修复 | 伪代码改为fix_consistency_issues()而非回GENERATING |
| FORMATTING条件触发 | ✅ 已修复 | lecture必选+practice_guide/quiz条件触发逻辑完整 |
| 版本号一致性 | ❌ 不一致 | 标题v6.15 vs 内容v6.16（🔴-1） |
| Schema-Prompt一致性 | ❌ 不一致 | confidence字段类型矛盾（🔴-4） |
| 创新点4去重 | ✅ 已修复 | 候选辩论归入创新点1，反向怀疑为创新点4独特贡献 |

---

## 修复优先级建议

| 优先级 | 问题编号 | 修复难度 | 说明 |
|--------|---------|---------|------|
| P0（立即修复） | 🔴-1 | ⭐ 极低 | 标题改一行 |
| P0（立即修复） | 🔴-2 | ⭐⭐ 中 | Schema枚举统一 + 补映射规则 |
| P0（立即修复） | 🔴-3 | ⭐⭐ 中 | 伪代码补修改步骤 + REVISING状态流转 |
| P0（立即修复） | 🔴-4 | ⭐⭐ 低 | Prompt/Schema类型统一 |
| P1（本轮修复） | 🟡-1 | ⭐ 低 | 伪代码补参数 |
| P1（本轮修复） | 🟡-2 | ⭐⭐ 中 | 补方法注释 |
| P1（本轮修复） | 🟡-3 | ⭐ 低 | 枚举值改为英文 |
| P1（本轮修复） | 🟡-4 | ⭐ 低 | 伪代码补HEURISTIC_FOLLOWUP |
| P1（本轮修复） | 🟡-5 | ⭐ 低 | 补注释说明 |
| P1（本轮修复） | 🟡-6 | ⭐ 低 | 补required字段 |
| P1（本轮修复） | 🟡-7 | ⭐⭐ 中 | 枚举值改英文+前端映射 |
| P1（本轮修复） | 🟡-8 | ⭐ 低 | 补映射表 |
| P1（本轮修复） | 🟡-9 | ⭐ 低 | 补设计原则说明 |
| P2（可选修复） | 🟢-1~3 | ⭐ 极低 | 措辞/结构微调 |

---

## 结论

v6.16在第一轮19项修复后，整体可行性大幅提升：
- **架构连通性**：主FSM+延伸路径+SOP链+贡献记忆闭环四条数据流全部闭合
- **Schema完整性**：6个SOP中间产物Schema全部有正式定义（🔴-2已修复）
- **设计一致性**：verdict英文枚举、domain_confidence两值体系已统一

**本轮4🔴均为v6.16修复过程中遗漏或新引入的问题**：
- 🔴-1（标题版本号）是v6.15→v6.16升级时遗漏的最简单修复
- 🔴-2（judgment枚举）是6.2.3节新增Schema时设计不完整
- 🔴-3（修退机制）是伪代码层面遗漏修改步骤，与6.1.1节FSM定义矛盾
- 🔴-4（confidence类型）是Schema与Prompt模板之间的跨节一致性问题

**4🔴修复后，方案书可达定稿级**。9🟡建议本轮一并修复以提升伪代码和Schema的完整性，3🟢可选择性处理。

---

*报告结束*
*检查日期：2026-07-13*
*下次检查建议：4🔴+9🟡修复后，执行第三轮可行性验证（聚焦伪代码与设计描述的精确匹配度）*
