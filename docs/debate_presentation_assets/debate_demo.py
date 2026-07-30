#!/usr/bin/env python3
"""
辩论流程演示脚本 — 多 Agent 辩论裁判协同展示

本脚本模拟完整的 JUDGING 阶段（裁判团3人审查 + 分歧解决 + 候选辩论 + 溯源标注），
使用硬编码的模拟数据，不调用真实 LLM，适合答辩演示。

用法:
    python docs/debate_presentation_assets/debate_demo.py

输出：
    - 控制台分阶段展示辩论流程
    - docs/debate_presentation_assets/debate_log.txt 完整日志
    - docs/debate_presentation_assets/debate_demo_data.json 结构化演示数据
"""

import io
import json
import os
import sys
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Optional

# Windows GBK 控制台 emoji 兼容
if sys.stdout.encoding and sys.stdout.encoding.lower() in ("gbk", "gb2312"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")



# ============================================================
# 演示场景：一个"注意力机制"提问
# ============================================================

DEMO_QUESTION = "什么是注意力机制（Attention Mechanism）？它在Transformer中的作用是什么？"

DEMO_STUDENT_PROFILE = {
    "knowledge_level": "入门",
    "background": "理科_无编程",
    "current_goal": "快速上手应用",
    "domain_hint": "LLM基础",
}

# 聚焦输出（模拟LLM生成结果，含一个合理的事实偏差）
DEMO_FOCUSED_OUTPUT = {
    "title": "注意力机制基础",
    "conclusion": (
        "注意力机制（Attention Mechanism）是Transformer架构的核心组件，"
        "它允许模型在处理序列数据时动态关注不同位置的信息权重。"
        "与RNN按顺序处理不同，注意力机制可以并行计算所有位置之间的相关性，"
        "大幅提升训练效率。"
    ),
    "reasoning_steps": [
        "步骤1：注意力机制的本质是'加权求和'——根据查询(Query)与各个键(Key)的相似度，"
        "计算每个值(Value)的权重，然后加权聚合。",
        "步骤2：在Transformer中，自注意力(Self-Attention)让每个token与其他所有token计算关联度，"
        "从而捕捉长距离依赖关系。这与RNN的逐步传递不同，无信息衰减问题。",
        "步骤3：论文'Attention Is All You Need'(Vaswani et al., 2017)提出的"
        "Scaled Dot-Product Attention被原始Transformer采用。"
        "后来发展出多头注意力(Multi-Head Attention)，"
        "让模型在不同表示子空间学习关联模式。",
        "步骤4：Transformer的编码器-解码器结构通过交叉注意力(Cross-Attention)对齐输入输出。"
        "Google 2017年最早在机器翻译任务上验证了其有效性。",
        "但Google并未提出注意力机制——注意力机制最早由Bahdanau等人在2014年提出用于机器翻译。"
    ],
    "knowledge_refs": [
        {
            "source": "论文: Attention Is All You Need (Vaswani et al., 2017)",
            "content_summary": "Transformer架构使用Scaled Dot-Product Attention，公式为Attention(Q,K,V)=softmax(QK^T/√d_k)V"
        },
        {
            "source": "论文: Neural Machine Translation by Jointly Learning to Align and Translate (Bahdanau et al., 2015)",
            "content_summary": "首次将注意力机制引入神经机器翻译，解决长句翻译性能下降问题"
        },
        {
            "source": "CS224n Lecture Notes (Stanford)",
            "content_summary": "注意力机制分为全局注意力和局部注意力，常见变体包括加性注意力、乘性注意力和自注意力"
        },
    ],
    "code_example": (
        "import torch\n"
        "import torch.nn.functional as F\n\n"
        "def scaled_dot_product_attention(Q, K, V):\n"
        "    '''Scaled Dot-Product Attention 实现'''\n"
        "    d_k = K.size(-1)\n"
        "    scores = torch.matmul(Q, K.transpose(-2, -1)) / (d_k ** 0.5)\n"
        "    weights = F.softmax(scores, dim=-1)\n"
        "    return torch.matmul(weights, V)"
    ),
}

# 获胜候选（候选生成阶段产物）
DEMO_WINNING_CANDIDATE = {
    "agent_id": "agent_001",
    "agent_name": "LLM基础Agent",
    "response_summary": "注意力机制是Transformer的核心，通过Query-Key-Value三重映射实现动态权重分配",
    "domain": ["LLM基础"],
    "self_confidence": 0.85,
}

# 落选候选
DEMO_LOSING_CANDIDATE = {
    "agent_id": "agent_005",
    "agent_name": "Agent框架Agent",
    "response_summary": "注意力机制允许Agent在处理长上下文时聚焦关键信息",
    "domain": ["Agent框架"],
    "self_confidence": 0.62,
}


# ============================================================
# 模块：3位裁判的独立审查意见（模拟）
# ============================================================

def judge_fact_review():
    """裁判1 - 事实审查：发现一个事实偏差"""
    return {
        "role": "事实审查裁判",
        "judgment": "fail",
        "evidence": [
            "步骤4中'Google 2017年最早在机器翻译任务上验证了其有效性'表述可能产生误解——"
            "注意力机制不是Google提出的，是Bahdanau 2014和Luong 2015的工作。"
            "Transformer确实是Google提出的，但注意力机制本身不是。",
            "建议改为：'Transformer由Google在2017年提出，基于Bahdanau等人2014年提出的注意力机制'",
        ],
        "confidence": 0.82,
    }


def judge_logic_review():
    """裁判2 - 逻辑审查：推理链完整"""
    return {
        "role": "逻辑审查裁判",
        "judgment": "pass",
        "evidence": [
            "推理链从概念定义→自注意力→多头注意力→交叉注意力，逻辑递进清晰",
            "结论与推理步骤一致，无矛盾",
        ],
        "confidence": 0.88,
    }


def judge_applicability_review():
    """裁判3 - 适用性审查：内容适配入门学生"""
    return {
        "role": "适用性审查裁判",
        "judgment": "pass",
        "evidence": [
            "内容从基础概念讲起，适合'入门'水平学生",
            "代码示例简洁（仅7行），适合'无编程背景'学生理解",
            "目标'快速上手应用'对齐较好——不涉及公式推导细节",
        ],
        "confidence": 0.85,
    }


# ============================================================
# 模块：分歧解决模拟
# ============================================================

def simulate_dissent_resolution():
    """
    模拟 2:1 分歧的完整解决流程

    状态:  裁判1(fail) + 裁判2(pass) + 裁判3(pass) = 2:1
    流程:  少数方举证 → 多数方回应 → 候选辩论 → 最终裁决
    """

    print("\n" + "=" * 72)
    print("  ⚖️  分歧解决 DISSENT_RESOLVE 启动")
    print("=" * 72)

    # ---- 第一步：少数方举证 ----
    fact = judge_fact_review()
    print(f"\n  [少数方] {fact['role']} 提交质证:")
    for e in fact["evidence"]:
        print(f"    ❓ {e}")

    # ---- 第二步：多数方回应（模拟 LLM 调用结果） ----
    print(f"\n  [多数方] 逻辑审查裁判 + 适用性审查裁判 回应:")
    majority_response = "rejected"  # 模拟多数方反驳
    majority_reasoning = [
        "步骤4的表述确实可优化，但内容本身是正确的 —— 注意力机制确实是Bahdanau提出，"
        "Transformer确实由Google在机器翻译任务上推广。混淆责任在表述不够精确，不影响输出质量。",
        "总体看，4步推理链完整，实质无事实错误。建议标注为'low_confidence_passed'而非退回修改。"
    ]
    print(f"    回应: {'接受质疑' if majority_response == 'accepted' else '反驳质疑'}")
    for r in majority_reasoning:
        print(f"    💬 {r}")

    # ---- 第三步：僵持 → 裁判长终裁（模拟） ----
    if majority_response == "rejected":
        print(f"\n  [僵持] 双方各执一词 → 提交裁判长终裁")
        chief_verdict = "revise"  # 裁判长倾向：虽然内容基本正确，但精确性要求高
        chief_reasoning = (
            "事实审查裁判指出的问题确实存在：步骤4的表述可能被评委解读为'Google提出了注意力机制'。"
            "在学术答辩场景下，这个混淆必须修正。建议退回修改步骤4的表述，其他内容通过。"
        )
        print(f"    [裁判长] 裁决: {'passed' if chief_verdict == 'passed' else 'revise'}")
        print(f"    🧑‍⚖️  {chief_reasoning}")

    # ---- 第四步：候选Agent辩论（模拟） ----
    print(f"\n  [候选辩论] 落选候选质疑 + 获胜候选辩护")
    challenge_evidence = [
        "落选候选(Agent框架Agent): 注意力机制的应用背景更适合在Agent框架中讲解，"
        "关注的是'如何利用注意力处理长上下文'而非'注意力原理本身'。"
        "入门学生更需要实用性视角。",
    ]
    defense_evidence = [
        "获胜候选(LLM基础Agent): 入门阶段重要的是建立概念理解，而不是跳入框架应用。"
        "先讲'是什么'再讲'怎么用'是教育学的合理顺序。",
    ]
    print(f"    🗣️  {challenge_evidence[0]}")
    print(f"    🛡️  {defense_evidence[0]}")

    # 辩论可能改变裁决
    print(f"\n  [裁决结论] 由于裁判长已判定 revise，候选辩论作为追加信息记录")
    final_verdict = "revise"
    print(f"    ✅ 最终裁定: {final_verdict}")

    return {
        "verdict": final_verdict,
        "dissent_resolution": {
            "minority_judge": fact["role"],
            "minority_evidence": fact["evidence"],
            "majority_response": majority_response,
            "majority_reasoning": majority_reasoning,
            "chief_judge_verdict": chief_verdict,
            "chief_judge_reasoning": chief_reasoning,
        },
        "candidate_debate": {
            "challenging_agent": "agent_005 (Agent框架Agent)",
            "challenge_evidence": challenge_evidence,
            "defending_agent": "agent_001 (LLM基础Agent)",
            "defense_evidence": defense_evidence,
        },
    }


# ============================================================
# 模块：溯源标注模拟
# ============================================================

def simulate_traceability():
    """高保真溯源标注 — 对knowledge_refs + conclusion + reasoning_steps做溯源"""

    print("\n" + "=" * 72)
    print("  📎 溯源标注流程")
    print("=" * 72)

    # 提取事实声明（模拟 _extract_factual_statements 逻辑）
    statements = []
    statements.append(("knowledge_ref_1", "Transformer架构使用Scaled Dot-Product Attention"))
    statements.append(("knowledge_ref_2", "Bahdanau首次将注意力机制引入机器翻译"))
    statements.append(("knowledge_ref_3", "注意力分为全局/局部注意力，加性/乘性/自注意力"))
    statements.append(("conclusion", "注意力机制是Transformer核心，可并行计算所有位置相关性"))
    statements.append(("reasoning_step_1", "注意力机制本质是Query-Key-Value的加权求和"))
    statements.append(("reasoning_step_2", "自注意力让每个token与其他所有token计算关联度"))
    statements.append(("reasoning_step_3", "Scaled Dot-Product Attention被原始Transformer采用"))
    statements.append(("reasoning_step_4", "Transformer通过交叉注意力对齐输入输出"))

    # 溯源结果（模拟 verify_statement 结果）
    traceability = []
    verification_results = {
        "Transformer架构使用Scaled Dot-Product Attention": {"status": "已验证", "source": "Attention Is All You Need"},
        "Bahdanau首次将注意力机制引入机器翻译": {"status": "已验证", "source": "Bahdanau 2015"},
        "注意力分为全局/局部注意力，加性/乘性/自注意力": {"status": "已验证", "source": "CS224n Lecture Notes"},
        "注意力机制是Transformer核心，可并行计算所有位置相关性": {"status": "已验证", "source": "综合多篇文献"},
        "注意力机制本质是Query-Key-Value的加权求和": {"status": "已验证", "source": "综合多篇文献"},
        "自注意力让每个token与其他所有token计算关联度": {"status": "已验证", "source": "Attention Is All You Need"},
        "Scaled Dot-Product Attention被原始Transformer采用": {"status": "已验证", "source": "Attention Is All You Need"},
        "Transformer通过交叉注意力对齐输入输出": {"status": "已验证", "source": "Attention Is All You Need"},
    }

    for cat, stmt in statements:
        result = verification_results.get(stmt, {"status": "待验证", "source": ""})
        traceability.append({
            "statement": stmt,
            "source_label": cat,
            "verification_status": result["status"],
            "source_doc": result["source"],
        })

    # 统计
    verified_count = sum(1 for t in traceability if t["verification_status"] == "已验证")
    total_count = len(traceability)
    rate = verified_count / total_count if total_count > 0 else 0

    print(f"    总声明数: {total_count}（knowledge_refs=3, conclusion=1, reasoning_steps=4）")
    print(f"    已溯源: {verified_count}/{total_count} = {rate:.0%}")
    for t in traceability:
        status_icon = "✅" if t["verification_status"] == "已验证" else "⏳"
        print(f"    {status_icon} [{t['source_label']}] {t['statement'][:50]}... → {t['verification_status']}")

    return {
        "statements_count": total_count,
        "verified_count": verified_count,
        "verification_rate": rate,
        "traceability_items": traceability,
    }


# ============================================================
# 模块：完整演示
# ============================================================

def print_header(text):
    width = 72
    print("\n" + "█" * width)
    print(f"  {text}")
    print("█" * width)


def run_demo():
    """运行完整辩论演示"""

    print_header("多 Agent 辩论裁判协同系统 — 演示")
    print(f"   时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"   场景: {DEMO_QUESTION}")

    # === 阶段1：背景输入 ===
    print_header("阶段 1/6: 输入 → 学生提问 + 聚焦输出")
    print(f"\n   📝 学生提问: {DEMO_QUESTION}")
    print(f"   👤 学情画像:")
    for k, v in DEMO_STUDENT_PROFILE.items():
        print(f"      {k}: {v}")
    print(f"\n   📄 聚焦输出标题: {DEMO_FOCUSED_OUTPUT['title']}")
    print(f"   📄 推理步数: {len(DEMO_FOCUSED_OUTPUT['reasoning_steps'])}")
    print(f"   📄 知识引用数: {len(DEMO_FOCUSED_OUTPUT['knowledge_refs'])}")
    print(f"   📄 代码行数: {len(DEMO_FOCUSED_OUTPUT['code_example'].splitlines())}")

    # === 阶段2：反向怀疑检测 ===
    print_header("阶段 2/6: 反向怀疑检测")
    refs_count = len(DEMO_FOCUSED_OUTPUT["knowledge_refs"])
    code_lines = len(DEMO_FOCUSED_OUTPUT["code_example"].splitlines())
    steps_count = len(DEMO_FOCUSED_OUTPUT["reasoning_steps"])

    # refs=3, code=7, steps=4 → none trigger
    print(f"   📊 knowledge_refs: {refs_count}/5 (阈值)")
    print(f"   📊 code_example行数: {code_lines}/20 (阈值)")
    print(f"   📊 reasoning_steps数: {steps_count}/8 (阈值)")
    triggered = refs_count >= 5 or code_lines >= 20 or steps_count >= 8
    print(f"\n   {'⚠️  触发严格审查模式' if triggered else '✅ 未触发严格审查，常规审查'}")
    print(f"   → 判决: {'注入严格审查指令' if triggered else '正常审查流程'}")

    # === 阶段3：3人独立审查并行（模拟）===
    print_header("阶段 3/6: 3人独立审查（并行）")
    fact = judge_fact_review()
    logic = judge_logic_review()
    applic = judge_applicability_review()

    votes = {"pass": 0, "fail": 0}
    for judge in [fact, logic, applic]:
        icon = "✅" if judge["judgment"] == "pass" else "❌"
        print(f"\n   {icon} {judge['role']}: {judge['judgment']}")
        print(f"      置信度: {judge['confidence']:.0%}")
        for e in judge["evidence"]:
            print(f"      - {e}")
        votes[judge["judgment"]] += 1

    print(f"\n   📊 投票结果: pass={votes['pass']}, fail={votes['fail']}")

    # === 阶段4：分歧解决 ===
    print_header("阶段 4/6: 分歧解决（2:1触发）")
    resolution = simulate_dissent_resolution()
    verdict = resolution["verdict"]
    dr = resolution["dissent_resolution"]

    # === 审核快速通道检查（此场景不触发）===
    review_scores = [0.82, 0.88, 0.85]
    score_range = max(review_scores) - min(review_scores)
    unanimous = score_range < 0.05
    print(f"\n   审核评分: {review_scores}, 分差={score_range:.2f}")
    print(f"   快速通道: {'⚡ 触发' if unanimous else '❌ 不触发'}")
    print(f"   → 因为分数差异明显，走完整分歧解决")

    # === 阶段5：溯源标注 ===
    print_header("阶段 5/6: 高保真溯源标注")
    trace = simulate_traceability()

    # === 阶段6：裁决产出 ===
    print_header("阶段 6/6: 最终裁定")

    verdict_map = {
        "passed": "✅ 通过",
        "revise": "🔄 修改通过",
        "low_confidence_passed": "🟡 低置信度通过",
        "failed": "❌ 未通过",
    }

    print(f"\n   裁定: {verdict_map.get(verdict, '未知')}")
    print(f"   投票: pass={votes['pass']}, fail={votes['fail']}")
    print(f"   溯源验证率: {trace['verification_rate']:.0%}")
    print(f"   裁决理由: 事实审查裁判指出的步骤4表述精确性问题，经裁判长终裁确认需要修正")

    # 动态决策说明
    print(f"\n   🔄 决策路径分析:")
    print(f"      1. 3人独立审查 → 2:1分歧")
    print(f"      2. 分歧解决启动 → 少数方举证 + 多数方反驳")
    print(f"      3. 僵持 → 裁判长终裁 → 裁定 revise")
    print(f"      4. 候选辩论追加记录 → 不改变裁定")
    print(f"      5. 最终 revise → 退回 GENERATING/FOCUSING 阶段重做")

    # 输出区隔
    print("\n")

    # ============================================================
    # 汇总数据
    # ============================================================
    demo_data = {
        "meta": {
            "title": "多Agent辩论裁判协同演示",
            "description": "挑战杯揭榜挂帅XH-202630 · 防幻觉机制展示",
            "generated_at": datetime.now().isoformat(),
            "demo_question": DEMO_QUESTION,
        },
        "input": {
            "question": DEMO_QUESTION,
            "student_profile": DEMO_STUDENT_PROFILE,
            "focused_output": DEMO_FOCUSED_OUTPUT,
        },
        "reverse_suspicion": {
            "triggered": triggered,
            "refs_count": refs_count,
            "code_lines": code_lines,
            "steps_count": steps_count,
        },
        "judges": {
            "fact_judge": fact,
            "logic_judge": logic,
            "applicability_judge": applic,
            "vote_summary": {"pass": votes["pass"], "fail": votes["fail"]},
        },
        "dissent_resolution": dr,
        "candidate_debate": resolution["candidate_debate"],
        "verdict": verdict,
        "traceability": trace,
        "review_unanimous": unanimous,
    }

    return demo_data


# ============================================================
# 入口
# ============================================================

def main():
    out_dir = os.path.dirname(os.path.abspath(__file__))
    log_path = os.path.join(out_dir, "debate_log.txt")
    data_path = os.path.join(out_dir, "debate_demo_data.json")

    # 保存控制台输出到日志
    old_stdout = sys.stdout
    log_file = open(log_path, "w", encoding="utf-8")
    sys.stdout = log_file

    demo_data = run_demo()

    # 恢复控制台后打印一次
    sys.stdout = old_stdout
    log_file.close()

    # 控制台重新显示
    run_demo()

    # 保存结构化数据
    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(demo_data, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 演示完成!")
    print(f"   📄 完整日志: {log_path}")
    print(f"   📊 结构化数据: {data_path}")


if __name__ == "__main__":
    main()
