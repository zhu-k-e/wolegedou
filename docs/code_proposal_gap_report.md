# 代码与方案书匹配度审查报告

> 审查时间: 2026-07-15
> 方案书版本: v7.0 (proposal.md, ~3500行)
> 代码版本: 当前 backend/ 目录全部文件 (51个Python文件)
> 审查范围: 方案书全部11个部分 vs 代码全部模块

---

## 一、总体评估

| 维度 | 结果 |
|------|------|
| 方案书技术规格项 | 83项 |
| 已正确实现 | 70项 (84.3%) |
| 存在差异 | 10项 (12.0%) |
| 未实现 | 3项 (3.6%) |

**结论**: 主流程（单领域场景）的代码实现与方案书高度匹配，配好API Key即可跑通完整闭环。核心架构亮点（FSM状态机、SOP Schema链、三层JSON兜底、候选辩论、贡献记忆闭环、早停机制、双低RAG触发）均已落地。差异主要集中在**多段场景处理**和**部分优化策略**上。

---

## 二、已正确实现的核心机制（30项确认）

以下方案书要求已在代码中正确实现，无需修改：

### 模块一：学情诊断Agent
- [x] 学情画像生成（9字段枚举约束）
- [x] 增量更新机制（版本号递增 + 历史检索）
- [x] 三步调度框架（意图裁决 → 领域解析 → 候选遴选）
- [x] 标签匹配度计算（primary 1.0 / secondary 0.7 / domain_tags 0.5）
- [x] α动态权重（config_repo get/set，冷启动0.9）
- [x] **早停机制**（连续2轮importance_score波动<0.05 → 只选Top-1）
- [x] 动态淘汰（连续3次importance<0.5 → 挂起 + 进入离线评估队列）

### 模块二：领域知识生成Agent池
- [x] 11个Agent卡片静态定义（agent_registry.py）
- [x] 候选输出含self_confidence自评估（同轮生成，0额外调用）
- [x] **双低触发RAG增强**（两个候选self_confidence都<0.5 → 知识库检索 + 重新生成）
- [x] 聚焦输出含审核反馈回流（MAR落地：只传具体问题不传评分）
- [x] 聚焦输出保持LLM会话上下文（history参数）
- [x] 聚焦输出使用高档模型（GPT-4o）
- [x] 三层JSON兜底校验（原生约束 → 正则修复 → LLM修复）
- [x] 资源生成3种形态条件触发（讲义必选 / 实操看code_example / 测试题看question_type）
- [x] 降维解释生成完整资源包（讲义+实操+测试题，非仅讲义）
- [x] 进阶挑战动态追加

### 模块三：审核团队 + 裁判团
- [x] 审核团队3人Persona（Verifier/Skeptic/Evaluator）
- [x] **Skeptic 5条固定检查清单**（自计算总分，不信任LLM自报分）
- [x] Verifier知识库逐条核查
- [x] Evaluator 4维教学适配评估
- [x] 段内评选加权汇总（w1/w2/w3可配置）
- [x] 跨段一致性审查
- [x] 裁判团3人独立审查（并行asyncio.gather）
- [x] **分歧解决完整流程**（少数方举证 → 多数方回应 → 裁判长裁决）
- [x] **候选Agent辩论**（落选质疑 + 获胜辩护）
- [x] **MaW→C转化路径**（辩论揭示新问题 → 改判REVISE）
- [x] 高保真知识溯源标注（逐条verify_statement）

### 模块四：贡献记忆闭环
- [x] EMA更新accuracy（EMA_SMOOTH=0.8）
- [x] 返工率计算（verdict映射为rework_score）
- [x] importance_score = 0.5×accuracy + 0.3×(1-rework_rate) + 0.2×count_normalized
- [x] 冷启动保护（count<5 返回默认0.5）
- [x] 学生反馈4种类型（helpful/not_helpful/content_error/difficulty_mismatch）
- [x] **difficulty_mismatch不挂钩Agent表现**（由编排器触发画像重新评估）

### 模块五：编排器
- [x] FSM 16状态（9主流程 + 2异常 + 5延伸路径）
- [x] 状态转移合法性校验（can_transition）
- [x] WebSocket实时状态推送
- [x] 退回修改机制（revision_count上限=2）
- [x] 延伸路径4条全部实现（REDIMENSION/ADVANCE/RECHECK/HEURISTIC_FOLLOWUP）
- [x] 延伸路径正确调用对应Agent（ResourceAgent/JudgePanel/ProfileAgent）
- [x] 任务上下文缓存（_task_contexts供延伸路径恢复）

---

## 三、差异清单（按严重程度分级）

### P0 — 高严重性（影响核心流程正确性）

#### GAP-1: 多段聚焦输出合并 — 只取第一段 ✅ 已修复

| 属性 | 值 |
|------|-----|
| 位置 | `orchestrator.py` `_do_judging()` 第401行, `_do_formatting()` 第464行 |
| 方案书要求 | 4.3节：跨段一致性审查后各段最优拼接；裁判团审查合并后的完整输出 |
| 代码现状 | `focused = ctx.focused_outputs[0]` — 只取第一段送裁判团审查和资源生成 |
| 影响 | 跨领域（2段）和全链路（4段）场景下，第2段及之后的聚焦输出未经裁判审查，资源生成也只基于第一段 |
| 修复方案 | 方案A：在FOCUSING后增加合并步骤，将多段FocusedOutput拼接为一份；方案B：裁判团循环审查各段 |
| 修复难度 | 中 |
| 修复状态 | ✅ 已修复：各段独立裁判 + `_merge_judge_verdicts()` 合并裁决 + `_merge_focused_outputs()` 合并输出 |

#### GAP-2: 延伸路径多段处理 — 只处理第一段 ✅ 已修复

| 属性 | 值 |
|------|-----|
| 位置 | `orchestrator.py` `_do_redimension()` 第574行, `_do_advance()` 第604行, `_do_recheck()` 第633行 |
| 方案书要求 | 6.1.3节：延伸路径应作用于完整交付内容 |
| 代码现状 | 所有延伸路径方法都只取 `ctx.focused_outputs[0]` |
| 影响 | 多段场景下降维解释/进阶挑战/审核复检只作用于第一段 |
| 修复方案 | 循环处理各段，或与GAP-1一并修复（合并后再处理） |
| 修复难度 | 低（若GAP-1已修复则自动解决） |
| 修复状态 | ✅ 已修复：全部改用 `ctx.merged_focused_output` |

---

### P1 — 中严重性（影响功能完整性或性能）

#### GAP-3: 反向怀疑机制 — 仅Prompt文本，无代码逻辑 ✅ 已修复

| 属性 | 值 |
|------|-----|
| 位置 | `judge_panel.py` `JudgeFact.system_prompt` 第51-52行 |
| 方案书要求 | 4.4.3节：knowledge_refs≥5 / code_example≥20行 / reasoning_steps≥8步时触发严格审查（被动触发式） |
| 代码现状 | 仅在system_prompt中写了文本说明"若knowledge_refs≥5条 / code_example≥20行 / reasoning_steps≥8步，启用严格审查"，依赖LLM自行判断 |
| 问题 | 代码没有主动检测FocusedOutput字段值，触发时也未改变审查行为（如增加检索Top-K、提高通过阈值、注入不同prompt） |
| 影响 | 反向怀疑的触发完全依赖LLM理解力，没有确定性保证；方案书定位为"创新点4"的核心机制 |
| 修复方案 | 在`judge()`方法中添加阈值检测：检查`len(focused.knowledge_refs)`、`len(focused.code_example.splitlines())`、`len(focused.reasoning_steps)`，触发时向裁判prompt注入"严格审查模式"指令并提高verification_coverage要求 |
| 修复难度 | 中 |
| 修复状态 | ✅ 已修复：新增 `_detect_reverse_suspicion()` 主动检测 + 严格审查指令注入 + 验证率<100%降级 |

#### GAP-4: 审核团队3人评分未并行

| 属性 | 值 |
|------|-----|
| 位置 | `review_team.py` `review_segment()` 第235-237行 |
| 方案书要求 | 8.4.2节优化1：审核团队3人调用并行（节省2×3秒） |
| 代码现状 | 3人串行执行：`v_score = await self.verifier.review(...)` → `s_score = await ...` → `e_score = await ...` |
| 影响 | 每个候选审核多耗时约6秒；跨领域场景（6次审核）多耗时约36秒 |
| 修复方案 | 改为 `asyncio.gather(self.verifier.review(...), self.skeptic.review(...), self.evaluator.review(...))` |
| 修复难度 | 低 |

#### GAP-5: α动态切换逻辑缺失

| 属性 | 值 |
|------|-----|
| 位置 | `config_repo.py` `get_alpha()` / `set_alpha()` |
| 方案书要求 | 2.4.2节：α冷启动0.9 → 数据积累后0.3（自动切换） |
| 代码现状 | 只有手动get/set接口，没有自动切换逻辑 |
| 问题 | α需要人工调用set_alpha更新，不会随系统运行自动从0.9降到0.3 |
| 修复方案 | 在`memory_service.record_task_completion()`完成后，检查全系统总记录数（如>100条），自动调用`config_repo.set_alpha(0.3)`；或设置阶梯式降α（50条→0.7, 100条→0.5, 200条→0.3） |
| 修复难度 | 低 |

#### GAP-6: 缺少阶段级降级策略

| 属性 | 值 |
|------|-----|
| 位置 | `orchestrator.py` 全局try-catch（第138-147行） |
| 方案书要求 | 8.5.3节模型降级 + 隐含的流程降级（学情诊断失败→默认画像，资源生成失败→仅讲义等） |
| 代码现状 | 任何阶段失败直接进ERROR状态，整个流程中断返回错误 |
| 影响 | 单点失败（如LLM超时）导致整个任务失败，无优雅降级 |
| 修复方案 | 各`_do_xxx`方法中添加try-catch：PROFILING失败→使用默认画像；FOCUSING失败→用候选输出直接送裁判；FORMATTING失败→仅生成讲义 |
| 修复难度 | 中 |

---

### P2 — 低严重性（不影响主流程，属于优化项）

#### GAP-7: 多处LLM输出未使用三层校验

| 属性 | 值 |
|------|-----|
| 位置 | 6处方法使用 `json.loads(raw)` 而非 `generate_and_validate()` |
| 涉及文件 | `domain_agent.py` debate_challenge/debate_defense, `judge_panel.py` _judge_single/_majority_response/_chief_judge_arbitrate, `profile_agent.py` generate_heuristic_followup, `resource_agent.py` generate_advance_challenge |
| 方案书要求 | 3.5.2节：所有Agent输出应经过三层兜底 |
| 代码现状 | 这些方法有 `except json.JSONDecodeError` 兜底返回原始文本，但非完整三层修复 |
| 影响 | LLM返回格式异常时降级为原始文本，可能影响下游处理质量 |
| 修复方案 | 统一改用`generate_and_validate()`，或封装一个轻量级`parse_json_safe()`方法 |
| 修复难度 | 低 |

#### GAP-8: 裁判团快速通道未实现

| 属性 | 值 |
|------|-----|
| 位置 | `judge_panel.py` `judge()` 方法 |
| 方案书要求 | 8.4.2节优化4：若审核评分全票一致（分差<0.05），裁判团只做溯源标注，跳过分歧解决 |
| 代码现状 | 所有场景都走完整裁判流程（3人审查 → 汇总 → 可能分歧解决） |
| 影响 | 高置信度场景多耗时约3-6秒 |
| 修复方案 | `judge()`方法开头检查审核评分一致性，若全票一致则简化裁判prompt为仅溯源标注 |
| 修复难度 | 低 |

#### GAP-9: 缺少学情画像缓存机制

| 属性 | 值 |
|------|-----|
| 位置 | `profile_agent.py` `generate_profile()` |
| 方案书要求 | 8.4.2节优化2：同一学生后续问题不重新生成学情画像（节省3秒） |
| 代码现状 | 每次都调用LLM生成画像（虽有增量更新版本号，但仍每次调LLM） |
| 影响 | 连续对话场景每次多耗时约3秒 |
| 修复方案 | 检查session最近画像，若domain_hint和knowledge_level未变化则复用 |
| 修复难度 | 低 |

#### GAP-10: 缺少代码可执行性沙箱检查

| 属性 | 值 |
|------|-----|
| 方案书要求 | 3.5.1节：代码可执行性检查（沙箱执行code_example） |
| 代码现状 | 无沙箱执行机制 |
| 影响 | code_example可能有语法错误或不可执行 |
| 修复方案 | 使用`subprocess`在受限环境中执行code_example，或使用`ast.parse`做语法检查 |
| 修复难度 | 高（安全沙箱环境搭建复杂，但方案书也未要求必须实现，属于理想化验证） |

---

## 四、修复优先级建议

### 第一批（必须修复 — 影响核心功能）
1. **GAP-1 + GAP-2**: 多段合并问题 — ✅ 已修复
2. **GAP-3**: 反向怀疑代码逻辑 — ✅ 已修复

### 第二批（建议修复 — 影响性能和鲁棒性）
3. **GAP-4**: 审核团队并行化 — 简单改动，大幅提升性能
4. **GAP-5**: α自动切换 — 简单改动，完善闭环优化
5. **GAP-6**: 阶段级降级策略 — 提升系统鲁棒性

### 第三批（可选修复 — 属于优化项）
6. **GAP-7**: 统一三层校验 — 提升输出质量一致性
7. **GAP-8**: 裁判团快速通道 — 性能优化
8. **GAP-9**: 画像缓存 — 性能优化
9. **GAP-10**: 沙箱检查 — 理想化验证，非必须

---

## 五、方案书 vs 代码架构亮点对照

| 方案书亮点 | 论文来源 | 代码实现位置 | 实现状态 |
|-----------|---------|------------|---------|
| Agent Pool + Agent Card | MetaGPT | agent_registry.py, init_db.py | 完整 |
| SOP 6个中间产物Schema | MetaGPT | schemas/ 目录6个文件 | 完整 |
| 候选自评估self_confidence | DyLAN | domain_agent.py generate_candidate() | 完整 |
| 双低触发RAG增强 | DyLAN | orchestrator.py _do_generating() | 完整 |
| 早停机制 | DyLAN | matcher.py _select_candidates() | 完整 |
| 审核反馈回流 | MAR | domain_agent.py generate_focused_output() | 完整 |
| 3人Persona分工 | MAR | review_team.py Verifier/Skeptic/Evaluator | 完整 |
| 候选Agent辩论 | Debate | judge_panel.py _resolve_dissent() | 完整 |
| MaW→C转化路径 | Debate | judge_panel.py _resolve_dissent() 第266行 | 完整 |
| 分歧解决DISSENT_RESOLVE | Debate | judge_panel.py _resolve_dissent() | 完整 |
| 反向怀疑机制 | Debate | judge_panel.py `_detect_reverse_suspicion()` + `judge()` | **完整** |
| 三层JSON兜底 | MetaGPT | json_validator.py + base_agent.py | 完整 |
| 贡献记忆EMA+淘汰 | DyLAN | memory_service.py | 完整 |
| 高保真溯源标注 | 赛题要求 | judge_panel.py _annotate_traceability() | 完整 |
| 启发式追问 | 赛题要求 | profile_agent.py generate_heuristic_followup() | 完整 |
| 降维解释动态追加 | 赛题要求 | resource_agent.py generate_dimension_reduction() | 完整 |
| FSM 16状态编排器 | MetaGPT | fsm.py + orchestrator.py | 完整 |

---

*报告结束*
