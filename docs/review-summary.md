# 方案书 vs 代码 评审总结

> 生成日期：2026-07-29  
> 版本：v7.0 终版  
> 对应方案书：`docs/proposal.md`  
> 对应代码：`backend/`

---

## 一、方案书文本审查：发现的 12 个问题

### 核心 5 个（已确认）

| 严重度 | 问题 | 所在章节 | 说明 |
|--------|------|----------|------|
| 中等 | §2.3 流程图标注"并行"但实为串行 | §2.3 图2-1 | 候选Agent生成输出 ↔ 裁判团审查是顺序执行，图上标了并行 |
| 中等 | §5.7 学生反馈难度闭环断了 | §5.7 | `difficulty_mismatch` 代码仅记录反馈不做事，`profile_agent` 不读 `student_feedback` 表 |
| 轻微 | §2.4.2 α 衰减是全局量而非 per-tag | §2.4.2 | 方案书写 per-function-tag，代码实践发现全局更可控，README 已补工程权衡说明 |
| 轻微 | §2.3.3 调用估算表中双低 RAG 增强开销未体现 | §2.3.3 表2-3 | 估算表仅含基本链路调用，双低场景 +2 次 LLM 调用（候选检索+知识库向量化）未计入 |
| 轻微 | §2.3.1/§2.3.2 DISPATCHING 回退路径未实现 | §2.3.1/§2.3.2 | domain_confidence 全 low 时应该退 CLARIFICATION，代码只打了 log，matcher 已修复 |

### 其余 7 个（已确认）

| 严重度 | 问题 | 所在章节 | 说明 |
|--------|------|----------|------|
| 轻微 | "第二期功能"等将来承诺话术 | §2.2.4 | 增量更新写"计划中"，已改为 V1/V2 分期话术 |
| 概念 | filter_agent 字段名与代码不一致 | §6.6 | 方案书写按 theme 过滤，代码按 agent_name |
| 概念 | 早停机制下的候选辩论不可用 | §2.4.4 / §3.4.3 | 早停只选 Top-1，落选候选不存在，辩论逻辑缺失 |
| 信息 | 代码安全检查替代沙箱 | §3.5.1 | 方案书说沙箱执行，代码用 AST 静态分析 |
| 信息 | 实操指南和测试题始终生成 | §3.6.1 | 方案书写条件触发，代码改为始终生成 |
| 信息 | 0:3 全票失败的裁判长终审门控 | §4.4.2 | 方案书无此设计，代码实现了挽救逻辑 |
| 信息 | 全链路降级策略 | §8.5.3 | 方案书只提了一句，代码有完整的 8 阶段降级表 |

---

## 二、代码 vs 方案书对比

### 2.1 差距：方案书写了但代码没做

| 优先级 | 差距 | 状态 | 修复 |
|--------|------|------|------|
| P0 | 学生反馈闭环（difficulty_mismatch → 画像调整） | ✅ 已修复 | `profile_agent.py` 加 `_load_student_feedback()` + `_adjust_knowledge_level_for_difficulty_feedback()` |
| P0 | DISPATCHING 回退路径（全 low → CLARIFICATION） | ✅ 已修复 | `matcher.py` `_resolve_domains()` 返回空列表 → dispatch 返回 CLARIFICATION |
| P1 | 早停 + 辩论缺失 | ✅ 已补文档 | 方案书 §2.4.4 添加补充说明 |

### 2.2 改进：代码做了但方案书没写

| 改进 | 文件 | 方案书章节 | 说明 |
|------|------|-----------|------|
| 技术关键词意图兜底（30+关键词硬映射） | `profile_agent.py` | §2.3.1 | 即使 LLM 判错，代码层救回 |
| 实操指南和测试题始终生成 | `resource_agent.py` | §3.6.1 | prompt 自适应有无代码 |
| 0:3 全票失败 → 裁判长终审门控 | `judge_panel.py` | §4.4.2 | 挽救大部分 0:3 场景 |
| 全链路 8 阶段降级策略 | `orchestrator.py` | §8.5.3 | 每个 FSM 阶段有明确 fallback |
| AST 静态代码安全检查 | `resource_agent.py` | §3.5.1 | 替代方案书的沙箱执行 |
| 多段聚焦输出 + 裁决合并 | `orchestrator.py` | §3.4.2/3.4.3 | 知识引用去重合并 |
| ws_manager.push_state 实时推送 | `ws_manager.py` | §6.1.2 | 每次 FSM 状态变更推前端 |

---

## 三、架构速查

```
学生提问 → PROFILING → DISPATCHING → GENERATING → REVIEWING → 
           FOCUSING → JUDGING → FORMATTING → COMPLETE
                                            ↓ 答题/反馈触发
                                     QUIZ_EVAL → REDIMENSION / ADVANCE / RECHECK / HEURISTIC_FOLLOWUP
```

关键文件位置：

| 文件 | 职责 |
|------|------|
| `backend/core/orchestrator.py` | FSM 主循环入口 |
| `backend/core/fsm.py` | 状态定义 + 转移规则 |
| `backend/agents/profile_agent.py` | 学情诊断 + 画像生成 |
| `backend/agents/matcher.py` | 调度（意图/领域/候选） |
| `backend/agents/domain_agent.py` | 领域候选生成 |
| `backend/agents/review_team.py` | 审核团队（3角色） |
| `backend/agents/judge_panel.py` | 裁判团（3角色 + 分歧解决） |
| `backend/agents/resource_agent.py` | 资源生成（讲义/实操/测试题） |
| `backend/services/memory_service.py` | EMA / 淘汰 / 学生反馈 |
| `backend/main.py` | FastAPI 入口 |

---

## 四、目标指标

| 指标 | 目标值 | 验证方式 |
|------|--------|----------|
| 幻觉率 | <5% | 审核团队+裁判团层级拦截 |
| 适配准确率 | ≥85% | 学情画像驱动调度 |
| 知识点覆盖率 | ≥90% | 11 个 Agent 池覆盖 10 个 AI 培训领域分类 |

---

## 五、下一次可以从这里接手

1. **知识库端到端验证**：部署 bge-m3，用真实 query 测检索质量
2. **前端对接**：前端团队调 `POST /api/ask` + `WS /ws/{task_id}`
3. **集成测试**：模拟完整的"提问→资源生成→答题→反馈"链条
4. **方案书微调**：如果竞赛评审要求文档版本统一，确认 proposal.md 的 12 处修改都已对齐

> 启动方法：`python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload`
