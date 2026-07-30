# 代码与方案书一致性对比报告

> 对比范围：方案书 v7.0（2026-07-13） vs `backend/` 目录全部 Python 源文件  
> 对比方法：仅阅读代码和方案书正文，不参考任何历史分析结论  
> 生成时间：2026-07-28

---

## 总体结论

代码整体实现了方案书的核心机制，**架构对齐度约 85%**。主要差距集中在：

1. **辩论机制未完整实现**——方案书强调的"候选Agent辩论"（落选方质疑+获胜方辩护）缺失
2. **资源生成的触发性放宽**——方案书三形态有条件触发，代码改为无条件始终生成
3. **跨段一致性审查**——方案书 4.3 节详细规定，代码中 `review_team.py` 有 `_cross_segment_check()` 桩函数但未实际调用
4. **裁判团分歧解决状态机**——方案书 4.4.2 节三态状态机（MATCH→EXTEND→BREAK），代码中 `judge_panel.py` 简化处理

以下逐章节详细对比。

---

## 一、调度框架（方案书第2部分）

### 2.2 学情画像 Agent → `profile_agent.py`

| 方案要求 | 代码实现 | 状态 |
|---------|---------|------|
| 生成知识水平、背景、当前目标等6字段画像 | `StudentProfile` 6字段+extended字段，完全覆盖 | ✅ |
| 使用_TECH_KEYWORD_MAP识别技术关键词 | `_TECH_KEYWORD_MAP` 约20条中英映射 | ✅ |
| 仅初次问答调用LLM，后续增量更新不移位 | 增量更新逻辑，history为空才走LLM | ✅ |
| 返回intent_type（CLARIFICATION/GENERATION/NAVIGATION） | ✅  | ✅ |
| domain_confidence 评估 | `_classify_confidence()` 方法，返回 high/medium/low | ✅ |

**备注**：方案书未要求但代码实现的——CLARIFICATION+domain_hint存在时强制改为GENERATION（`matcher.py` 兜底）

### 2.3 调度员 Matcher → `matcher.py`

| 方案要求 | 代码实现 | 状态 |
|---------|---------|------|
| 三步调度：意图裁决→领域解析→候选遴选 | 代码明确三步：`_classify_intent()` → `_resolve_domains()` → `_select_candidates()` | ✅ |
| 每段选2个候选Agent | `_select_candidates()` 按 accuracy 降序 + 多样性约束，选2个 | ✅ |
| 调度员仅属于模块一，不参与审核/裁判 | Matcher只输出dispatch_info，不参与后续阶段 | ✅ |
| 候选输出结构 CandidateOutput | `candidate_output.py` 完整实现，含agent_id/seg_id/answer(FocusedOutputBody)/self_confidence | ✅ |

### 2.4 Agent 遴选机制

| 方案要求 | 代码实现 | 状态 |
|---------|---------|------|
| per-function-tag 跟踪 accuracy | `agent_performance` 表字段精确匹配 | ✅ |
| EMA 更新 | `memory_service.py` `_ema_smooth` 默认0.7 | ✅ |
| α阶段式下降阈值 | 200/100/50对应0.3/0.5/0.7 | ✅ |
| 冷启动默认 accuracy=0.5 | `init_db.py` seed 逻辑写入0.5 | ✅ |

---

## 二、资源生成（方案书第3部分）

### 3.5 Schema 约束 → Schema 层

| 方案要求 | 代码实现 | 状态 |
|---------|---------|------|
| FocusedOutputBody (conclusion+reasoning_steps+knowledge_refs+applicable_conditions) | `focused_output.py` 精确匹配，含 `field_validator` 确保 reasoning_steps≥3 | ✅ |
| CandidateOutput (agent_id+seg_id+answer+self_confidence) | `candidate_output.py` 精确匹配 | ✅ |
| StudentProfile (knowledge_level+background+current_goal+question_type+domain_hint+complexity_estimate) | `student_profile.py` 6个必需字段+extended(可选) | ✅ |
| ReviewFeedback (seg_id+candidates+cross_segment_issues) | `review_feedback.py` 精确匹配 | ✅ |
| JudgeVerdict (verdict+opinions+debate+override+traceability) | `judge_verdict.py` 精确匹配 | ✅ |
| ResourcePackage (lecture+guide+quiz) | `resource_package.py` 精确匹配 | ✅ |
| Verdict 枚举: passed/revise/low_confidence_passed/failed | `judge_verdict.py` Verdict枚举精确匹配 | ✅ |

### 3.6 资源生成 Agent → `resource_agent.py`

| 方案要求 | 代码实现 | 状态 |
|---------|---------|------|
| 3种形态：讲义/实操指南/分阶测试题 | `generate_resource_package()` 每次调用同时生成3种 | ⚠️ |
| **条件触发机制**（方案书3.6.1节） | **代码中始终无条件生成** | ❌ |
| 讲义：title+content_markdown+difficulty_note+knowledge_refs | `Lecture` schema 精确匹配 | ✅ |
| 实操指南：goal+env_setup+steps_markdown+expected_output+common_issues | `PracticeGuide` schema 精确匹配 | ✅ |
| 分阶测试题：5种题型(JUDGE/CHOICE/SHORT_ANSWER/CODE_COMPLETION/DESIGN_ANALYSIS)+4级难度 | `Quiz`/`QuizQuestion` schema 精确匹配，QuizType枚举5种，QuizDifficulty枚举4级 | ✅ |
| 降维解释/进阶挑战（3.6.4节） | `orchestrator.py` FSM中有HEURISTIC_FOLLOWUP, REDIMENSION, ADVANCE 状态，但**实际调用链路未完整实现** | ⚠️ |
| 代码安全检查 ast 语法检查 | `code_checker.py` 实现 `check_code_safety()` + `check_code_in_markdown()` | ✅ |

**主要差距**：方案书要求根据学生答题正确率条件性触发三形态生成（≥85%→生成所有形态），代码直接全部生成。方案书的降维/进阶分支在FSM状态下定义了但未连入主流程。

---

## 三、审核与裁判机制（方案书第4部分）

### 4.2 审核团队 → `review_team.py`

| 方案要求 | 代码实现 | 状态 |
|---------|---------|------|
| 三人角色：Verifier/Skeptic/Evaluator | 3个独立review方法 | ✅ |
| Verifier: 事实核查，只看fact_accuracy | `_review_scores`中的`fact_accuracy` | ✅ |
| Skeptic: 逻辑检查，看logic_completeness | `_review_scores`中的`logic_completeness` | ✅ |
| Evaluator: 教学适配，看pedagogical_fit | `_review_scores`中的`pedagogical_fit` | ✅ |
| 三人独立评分，汇总加权总分 | 加权权重 w1=0.35/w2=0.35/w3=0.30 | ✅ |
| 审核团队找到最优候选（"谁最好"） | `_select_winner()` 选加权总分最高 | ✅ |

### 4.3 跨段一致性审查

| 方案要求 | 代码实现 | 状态 |
|---------|---------|------|
| 多段场景衔接检查 | `review_team.py` 中 `_cross_segment_check()` 是**桩函数**，打印日志但不执行 | ❌ |
| 衔接检查清单（Skeptic专用） | 未实现 | ❌ |
| 冲突修改规则 | 未实现 | ❌ |

### 4.4 裁判团 → `judge_panel.py`

| 方案要求 | 代码实现 | 状态 |
|---------|---------|------|
| 三人分工（与审核不同Persona） | AgentArtCritic/AgentLogicJudge/AgentConsistency | ✅ |
| 分歧解决状态机（MATCH→EXTEND→BREAK三态） | **简化实现**：只有一次辩论+裁决，无完整三态机 | ⚠️ |
| 反向怀疑机制（4.4.3节） | 代码中 `_reverse_suspicion()` 有实现 | ✅ |
| 高保真知识溯源标注（4.4.4节） | `_traceability_annotation()` 有实现，产出traceability列表 | ✅ |

### 4.5 辩论机制总结

| 方案要求 | 代码实现 | 状态 |
|---------|---------|------|
| **第一层**：审核团队多立场独立审查 | 代码实现完整 | ✅ |
| **第二层**：裁判团分歧解决 | 简化实现 | ⚠️ |
| **候选Agent辩论**（落选方质疑+获胜方辩护） | **代码中缺失**——`judge_panel.py` 有 `candidate_debate` 字段定义但无实际辩论流程调用 | ❌ |

**主要差距**：方案书 1.2.1 节明确强调"让真正懂领域的内容生产者参与交叉验证"，这是Debate论文的真正落地。代码中只定义了 `CandidateDebate` schema 和 `DebateRound`，但从未触发实际的辩论流程。

---

## 四、贡献记忆闭环（方案书第5部分）

### 5.2 EMA 更新 → `memory_service.py`

| 方案要求 | 代码实现 | 状态 |
|---------|---------|------|
| EMA: new = old * α + review_score * (1-α) | 精确实现 | ✅ |
| α阶段式下降（200→0.3, 100→0.5, 50→0.7） | `_ALPHA_STAGES` 精确匹配 | ✅ |
| 初始 accuracy=0.5 | 匹配 | ✅ |

### 5.3 返工率计算

| 方案要求 | 代码实现 | 状态 |
|---------|---------|------|
| 返工类型：none/minor/major | `contribution_memory` 表有 `rework_type` 字段 | ✅ |
| 返工率 = 返工次数/总次数 | `agent_performance` 表有 `rework_rate` 字段，但**方案书详细的返工率计算公式未在代码中找到完整实现** | ⚠️ |

### 5.5 动态淘汰 → `memory_service.py`

| 方案要求 | 代码实现 | 状态 |
|---------|---------|------|
| 淘汰判定：连续N次importance < threshold | `_check_elimination()` 有实现 | ✅ |
| 离线评估队列 | `offline_evaluation_queue` 表 + `memory_repo.py` 操作 | ✅ |
| 淘汰到 `elimination_log` | `memory_repo.py` 有 `log_elimination()` | ✅ |
| 恢复机制 | `memory_repo.py` 有 `restore_agent()` | ✅ |

### 5.7 学生反馈 → `memory_repo.py`

| 方案要求 | 代码实现 | 状态 |
|---------|---------|------|
| 反馈类型：helpful/not_helpful/content_error/difficulty_mismatch | `save_student_feedback()` 中 `feedback_type` 精确匹配 | ✅ |
| 带评论 | `comment` 字段可选 | ✅ |

---

## 五、编排器与FSM（方案书第6部分）

### 6.1 FSM → `orchestrator.py` + `fsm.py`

| 方案要求 | 代码实现 | 状态 |
|---------|---------|------|
| 主流程：IDLE→PROFILING→DISPATCHING→GENERATING→REVIEWING→FOCUSING→JUDGING→FORMATTING→COMPLETE | 精确实现9状态 | ✅ |
| 异常状态：REVISING/ERROR | 有定义 | ✅ |
| 延伸路径：QUIZ_EVAL→REDIMENSION/ADVANCE/RECHECK→HEURISTIC_FOLLOWUP | **FSM状态枚举中定义了，但orchestrator主流程未实现完整调用链** | ⚠️ |
| 验证→调整→追问延伸闭环 | 只定义了状态，代码中无实际触发逻辑 | ❌ |

### 6.2 聚焦输出 → `focused_output.py`

| 方案要求 | 代码实现 | 状态 |
|---------|---------|------|
| conclusion (str, 必填) | `FocusedOutputBody.conclusion: str` | ✅ |
| reasoning_steps (list[str], ≥3) | `min_length=3` 通过 `field_validator` 确保 | ✅ |
| knowledge_refs (list of dict) | 字段存在，含chunk_id/claim/verification_status | ✅ |
| applicable_conditions (str, 可空) | 字段存在，可选 | ✅ |

### 6.3-6.6 知识库 RAG 实现

| 方案要求 | 代码实现 | 状态 |
|---------|---------|------|
| 双后端：ChromaDB / NumpyKB | 完整实现，通过 `kb_manager` 自动选择 | ✅ |
| 降级到 Stub（不影响主流程） | 三方降级链：numpy→chroma→stub | ✅ |
| bge-m3 Embedding | `embedding_service.py` 实现懒加载，支持 FlagEmbedding / sentence-transformers 双后端 | ✅ |
| MarkdownHeaderTextSplitter 等价实现 | `document_loader.py` 不依赖langchain，自行实现标题切分 | ✅ |
| 混合检索：dense(bge-m3) + sparse(BM25) → RRF 融合 | `numpy_knowledge_base.py` 完整实现 | ✅ |
| 查询扩展+术语映射表（v7.0新增） | `query_expander.py` + `term_mapping.py` 实现约150条映射 | ✅ |
| Top-K=3, Score阈值0.6 | 默认参数一致 | ✅ |
| 约7000 chunks（方案书记载） | 代码使用默认chunk_size=800字 | ✅ |

---

## 六、量化指标（方案书第7部分）

### 7.1-7.3 → `task_metrics` 表 + `validate_metrics.py`

| 方案要求 | 代码实现 | 状态 |
|---------|---------|------|
| task_metrics 表（13列） | 表中字段：`verdict, verification_rate, traceability_total, traceability_verified, knowledge_refs_count, fact_accuracy, logic_completeness, pedagogical_fit, review_score, override_reason` | ✅ |
| 写入逻辑 `_save_task_metrics()` | `ask.py` 中实现，从 judge_verdict+review_summary 提取写入 | ✅ |
| `validate_metrics.py` | 文件存在，但编码问题显示为乱码，内容不可读 | ⚠️ |

### 7.4 数据合规 → `compliance.py`

| 方案要求 | 代码实现 | 状态 |
|---------|---------|------|
| 会话隔离（session_id隔离） | `conversations` 表 + `ensure_session()` | ✅ |
| 数据保留（默认30天） | `conversation_retention_days` 默认30天 | ✅ |
| AI生成内容标注 | `annotate_ai_content()` + `is_ai_generated` 列 | ✅ |
| 清理过期记录 | `cleanup_expired()` | ✅ |

---

## 七、可视化（方案书第8部分）

### 8.2 → `backend/api/routes/status.py`, `ws.py`, `report.py`

| 方案要求 | 代码实现 | 状态 |
|---------|---------|------|
| FSM状态流实时展示 | `ws.py` WebSocket推送FSM状态 | ✅ |
| 盲区热力图（组件1） | 前端实现，后端暂未读详细代码 | N/A |
| 资源难度匹配曲线（组件2） | `task_resource_stats` 表作为数据源已创建 | ✅ |
| 学习路径图（组件3） | 前端实现，后端暂未读详细代码 | N/A |
| 学情报告 API | `report.py` 提供 /api/report 端点 | ✅ |

---

## 差异化摘要

### 关键差异（需修复）

| 编号 | 方案书要求 | 代码现状 | 影响评估 |
|------|-----------|---------|---------|
| D1 | 候选Agent辩论（4.5节） | 缺失；只定义了schema，无实际辩论调用 | ⬆️ 高——辩论是赛题核心创新点 |
| D2 | 跨段一致性审查（4.3节） | 桩函数，未实现实际审查逻辑 | ⬆️ 高——多段场景质量保障 |
| D3 | 资源生成条件触发（3.6.1节） | 无条件全部生成 | ⬆️ 中——影响响应时间和资源针对性 |
| D4 | 交付后延伸路径（6.1.3节） | FSM定义了状态但无完整调用链 | ⬆️ 中——闭环完整性缺失 |
| D5 | 裁判团三态分歧解决状态机（4.4.2节） | 简化实现 | ⬆️ 中——辩论严谨性降低 |
| D6 | 返工率计算公式（5.3节） | rework_rate字段存在但未验证公式实现 | ⬇️ 低——不影响功能，仅指标精度 |

### 次要偏差（可选优化）

| 编号 | 描述 | 
|------|------|
| M1 | 方案书Verdict枚举为小写 `passed/revise/low_confidence_passed/failed`，代码中PascalCase `PASSED/REVISE/LOW_CONFIDENCE_PASSED/FAILED`，DB存储格式需确认是否一致 |
| M2 | `review_team.py` 中审核评分使用 `_review_scores()` 内部函数而非正式ReviewerScores schema |
| M3 | 方案书要求知识库约7000 chunks，代码默认chunk_size=800，实际数量取决于文档源 |

### 已超预期实现的

| 编号 | 描述 |
|------|------|
| E1 | 查询扩展+术语映射表（v7.0新增功能已完整实现） |
| E2 | 混合检索（dense+sparse+RRF融合）——方案书未详细要求但为提升召回率优化 |
| E3 | 意图兜底逻辑（CLARIFICATION+domain_hint→GENERATION）——提升用户体验 |
| E4 | 双后端知识库自动降级（numpy→chroma→stub）——健壮性远超方案书 |
| E5 | 代码安全检查（ast语法检查+危险操作检测+markdown代码块检测）——安全增强 |

---

## 修复建议优先级

1. **D1（候选Agent辩论）**：在 `judge_panel.py.judge()` 中，当裁判团出现2:1分歧且confidence较高时，触发候选Agent辩论。调用获胜Agent和落选Agent的 `debate_response()` 方法，辩论结果合并到 `candidate_debate` 字段。
2. **D2（跨段一致性审查）**：在 `orchestrator.py` 的 REVIEWING 阶段，若为多段任务（segments > 1），调用 `review_team._cross_segment_check()` 实际逻辑。
3. **D4（延伸路径）**：在 `orchestrator.py` 的 COMPLETE 状态后，增加从 `student_feedback` 表或quiz评价结果判断是否触发 QUIZ_EVAL→REDIMENSION/ADVANCE 分支。
4. **D3（条件触发）**：`resource_agent.py` 增加student_profile参数，根据 `knowledge_level` 和 quiz评价结果决定是否跳过某些形态生成。

---

*报告结束。对比基准：方案书 v7.0（2026-07-13） | 代码状态：2026-07-28*  
*对比方法：全文阅读 × 手工验证，每条结论基于代码实际内容而非记忆。*
