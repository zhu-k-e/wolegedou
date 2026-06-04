"""
Streamlit 前端界面。
用法：streamlit run frontend/app.py

展示多Agent协同调度的完整可视化流程。
"""

import streamlit as st
import json
import sys
from pathlib import Path

# 确保项目根目录在 Python 路径中
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from config import LEARNER_PROFILE_TEMPLATE, DOMAIN_NAME
from agents import AgentOrchestrator
from knowledge_base import KnowledgeRetriever
from utils.logger import setup_logger

# 初始化日志
setup_logger()

st.set_page_config(
    page_title=f"多Agent协同学习系统 - {DOMAIN_NAME}",
    page_icon="📚",
    layout="wide",
)

st.title(f"📚 领域知识个性化生成与多智能体协同决策系统")
st.caption(f"垂直领域: {DOMAIN_NAME} | 挑战杯揭榜挂帅 XH-202630")

# ============================================================
# 侧边栏：学习者信息输入
# ============================================================
with st.sidebar:
    st.header("👤 学习者画像输入")

    learner_name = st.text_input("姓名", value="张三")

    st.subheader("背景信息")
    education = st.selectbox("学历", ["本科", "硕士", "博士", "其他"])
    major = st.text_input("专业", value="计算机科学")
    experience = st.slider("相关经验（年）", 0, 10, 1)

    st.subheader("自我评估")
    known_topics = st.text_area(
        "已掌握技能（每行一个）",
        value="Python基础\nNumPy\nPandas",
        height=80,
    )
    target_topics = st.text_area(
        "想学习技能（每行一个）",
        value="机器学习基础\n模型评估\n特征工程",
        height=80,
    )
    learning_goal = st.text_input("学习目标", value="掌握ML工程实践能力")

    st.subheader("前置测试（可选）")
    pretest_score = st.slider("前置测试分数", 0, 100, 60)

    run_button = st.button("🚀 开始诊断与生成", type="primary", use_container_width=True)

# ============================================================
# 主区域
# ============================================================
tab1, tab2, tab3, tab4 = st.tabs(["📊 诊断结果", "📖 学习资源", "✅ 质量审核", "📋 全流程日志"])

if run_button:
    # 构建学习者数据
    learner_data = {
        "name": learner_name,
        "background": {
            "education": education,
            "major": major,
            "years_of_experience": experience,
        },
        "self_assessment": {
            "known_topics": [t.strip() for t in known_topics.split("\n") if t.strip()],
            "target_topics": [t.strip() for t in target_topics.split("\n") if t.strip()],
            "learning_goal": learning_goal,
        },
        "test_results": {
            "pretest_score": pretest_score,
        },
    }

    # 初始化知识库检索器
    with st.spinner("🔌 连接知识库..."):
        try:
            retriever = KnowledgeRetriever()
            doc_count = retriever.get_doc_count()
            if doc_count == 0:
                st.warning("⚠️ 知识库为空，Agent将在无RAG模式下运行（生成质量会下降）")
        except Exception as e:
            st.error(f"知识库连接失败: {e}")
            retriever = None

    # 初始化Orchestrator并运行
    with st.spinner("🤖 多Agent协同工作中..."):
        orchestrator = AgentOrchestrator(retriever=retriever)
        result = orchestrator.run(learner_data)

    # --- Tab1: 诊断结果 ---
    with tab1:
        diagnosis = result["diagnosis"]
        st.subheader(f"🔍 学情诊断报告 - {learner_name}")

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("知识水平", diagnosis.get("knowledge_level", "未知"))
        with col2:
            st.metric("学习风格", diagnosis.get("learning_style_hint", "未知"))
        with col3:
            st.metric("学习目标", learning_goal[:10] + "..." if len(learning_goal) > 10 else learning_goal)

        col4, col5 = st.columns(2)
        with col4:
            st.markdown("**💪 强项**")
            for s in diagnosis.get("strengths", []):
                st.success(s)
            st.markdown("**🎯 推荐方向**")
            for r in diagnosis.get("recommended_focus", []):
                st.info(r)
        with col5:
            st.markdown("**⚠️ 知识盲区**")
            for w in diagnosis.get("weaknesses", []):
                st.warning(w)

        st.markdown(f"**📝 诊断分析**\n\n{diagnosis.get('analysis', '无')}")

    # --- Tab2: 学习资源 ---
    with tab2:
        content = result["final_output"]["learning_resources"]
        st.subheader("📖 个性化学习资源")

        with st.expander("📚 定制讲义", expanded=True):
            st.markdown(content.get("theory_lecture", "无内容"))

        with st.expander("🔧 实操指南", expanded=False):
            st.markdown(content.get("practical_guide", "无内容"))

        with st.expander("📝 分阶测试题", expanded=False):
            exercises = content.get("exercises", [])
            if isinstance(exercises, list):
                for i, ex in enumerate(exercises):
                    if isinstance(ex, dict):
                        difficulty_emoji = {"easy": "🟢", "medium": "🟡", "hard": "🔴"}
                        emoji = difficulty_emoji.get(ex.get("difficulty", ""), "⚪")
                        st.markdown(
                            f"**{i+1}. {emoji} [{ex.get('difficulty', '?')}] {ex.get('question', '')}**"
                        )
                        if ex.get("target_weakness"):
                            st.caption(f"针对盲区: {ex['target_weakness']}")
                        st.divider()
            else:
                st.markdown(str(exercises))

    # --- Tab3: 质量审核 ---
    with tab3:
        st.subheader("✅ 内容质量审核报告")
        quality = result["final_output"]["quality_report"]

        col1, col2, col3 = st.columns(3)
        with col1:
            verdict = quality.get("review_verdict", "未知")
            verdict_color = "green" if verdict == "通过" else "orange" if verdict == "需修正" else "red"
            st.markdown(f"**审核结论**: :{verdict_color}[{verdict}]")
        with col2:
            st.metric("发现错误数", quality.get("error_count", 0))
        with col3:
            risk = quality.get("hallucination_risk", "未知")
            risk_color = "green" if risk == "低" else "orange" if risk == "中" else "red"
            st.markdown(f"**幻觉风险**: :{risk_color}[{risk}]")

        if result["debate_result"].get("debate_rounds", 0) > 0:
            st.info(f"🔁 辩论仲裁已触发，共 {result['debate_result']['debate_rounds']} 轮")
            st.markdown(f"**仲裁理由**: {result['debate_result'].get('reason', '无')}")

        review = result["review_result"]
        if review.get("errors"):
            st.markdown("**错误详情**:")
            for e in review["errors"]:
                severity_map = {"严重": "🔴", "一般": "🟡", "轻微": "🟢"}
                sev = severity_map.get(e.get("severity", ""), "⚪")
                st.error(f"{sev} [{e.get('severity', '?')}] {e.get('description', '')}")
                st.caption(f"修正建议: {e.get('correction', '无')}")

    # --- Tab4: 全流程日志 ---
    with tab4:
        st.subheader("📋 多Agent协同调度全流程")
        trace = result.get("trace", [])
        for step in trace:
            stage = step.get("stage", "")
            if stage == "diagnosis":
                st.markdown(f"**1️⃣ 学情诊断Agent** → 知识水平: {step['result'].get('knowledge_level')}")
            elif stage == "retrieval":
                st.markdown(f"**2️⃣ RAG检索** → 命中 {step.get('doc_count', 0)} 条文档")
            elif stage == "generation":
                st.markdown(f"**3️⃣ 知识生成Agent** → 置信度: {step['result'].get('confidence')}")
            elif stage == "review":
                st.markdown(f"**4️⃣ 审核裁判Agent** → 结论: {step['result'].get('verdict')}")
            elif stage == "debate":
                st.markdown(f"**5️⃣ 辩论仲裁Agent** → 裁定: {step['result'].get('arbitration')}")
            st.divider()

    st.success("✅ 全流程完成！各Agent输出已在上方标签页展示")

else:
    # 初始状态
    st.info("👈 在左侧填写学习者信息后，点击「开始诊断与生成」启动多Agent协同流程")
    st.markdown("""
    ### 系统工作流
    1. **学情诊断Agent** → 分析知识强项与盲区
    2. **RAG知识检索** → 从领域知识库获取相关内容
    3. **知识生成Agent** → 生成个性化学习资源
    4. **审核裁判Agent** → 验证内容准确性，防控幻觉
    5. **辩论仲裁Agent** → 出现分歧时交叉验证决策
    """)
