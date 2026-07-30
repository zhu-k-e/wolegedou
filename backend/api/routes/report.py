"""/report 接口 - 学情诊断报告（方案书 8.2.2 节三组件）

GET /api/report/{session_id}
返回知识盲区热力图 + 资源难度匹配曲线 + 学习路径规划图

对齐赛题要求：
  "支持生成可视化的个人学情与资源匹配度报告，
   包含知识盲区定位、资源难度匹配曲线、学习路径规划图等"

数据来源（均为已有数据）：
  组件1 热力图：学情画像 domain_confidence + Agent Card importance_score
  组件2 匹配曲线：学情画像 knowledge_level + task_resource_stats 表（quiz difficulty）
  组件3 路径图：7阶段固定路径模板 + 学情画像 + 热力图联动
"""

import json

from fastapi import APIRouter, HTTPException

from backend.api.schemas import (
    LearningReport,
    KnowledgeHeatmap,
    HeatmapNode,
    DifficultyMatchCurve,
    DifficultyMatchPoint,
    LearningPath,
    PathStage,
)
from backend.db.repositories import profile_repo, agent_repo
from backend.db.database import query_all
from backend.agents.agent_registry import get_domain_agents

router = APIRouter()

# ============================================================
# 数值映射常量
# ============================================================

# 难度档 → 0-1 分值（匹配曲线红线）
_DIFFICULTY_SCORE = {"基础": 0.25, "应用": 0.5, "综合": 0.75, "进阶": 1.0}

# 学情水平 → 0-1 分值（匹配曲线蓝线基线）
_LEVEL_SCORE = {"ENTRY": 0.25, "INTERMEDIATE": 0.5, "ADVANCED": 0.75}

# 画像 domain_confidence 值 → 掌握度分值
_CONFIDENCE_SCORE = {"high": 0.8, "low": 0.4}

# 7 阶段学习路径（基于 AI 知识依赖关系，方案书 navigation 路线图）
_LEARNING_STAGES = [
    {"stage": 1, "title": "基础概念", "domains": ["LLM基础"], "hours": 4},
    {"stage": 2, "title": "Prompt工程", "domains": ["Prompt工程"], "hours": 3},
    {"stage": 3, "title": "模型调用与微调", "domains": ["HuggingFace", "模型微调"], "hours": 6},
    {"stage": 4, "title": "向量检索", "domains": ["向量数据库"], "hours": 3},
    {"stage": 5, "title": "RAG架构", "domains": ["RAG", "LangChain"], "hours": 5},
    {"stage": 6, "title": "Agent框架", "domains": ["Agent框架"], "hours": 4},
    {"stage": 7, "title": "项目实战", "domains": ["项目部署"], "hours": 6},
]


@router.get("/report/{session_id}", response_model=LearningReport)
async def get_report(session_id: str) -> LearningReport:
    """学情诊断报告 - 8.2.2 节三组件

    前端调用此接口获取结构化数据，自行渲染热力图/曲线/路径图。
    """
    # ---- 取画像 ----
    profile = profile_repo.get_latest_profile(session_id)
    if not profile:
        raise HTTPException(
            status_code=404,
            detail=f"未找到 session {session_id} 的学情画像，请先提问生成画像",
        )

    domain_confidence = profile.get("domain_confidence", {})
    knowledge_level = profile.get("knowledge_level", "ENTRY")
    level_score = _LEVEL_SCORE.get(knowledge_level, 0.25)

    # ---- 取全部领域 Agent ----
    domain_agents = get_domain_agents()  # 10 个

    # ============================================================
    # 组件1：知识盲区定位热力图
    # ============================================================
    # 预加载所有领域 Agent 的 importance_score
    agent_infos = []
    for agent in domain_agents:
        agent_id = agent["agent_id"]
        perfs = agent_repo.get_agent_all_performances(agent_id)
        primary_tag = agent["primary_function"]
        importance = 0.5  # 冷启动默认
        for p in perfs:
            if p["function_tag"] == primary_tag:
                importance = p["importance_score"]
                break
        agent_infos.append({
            "agent_name": agent["agent_name"],
            "domains": agent["domain_tags"],
            "importance": importance,
        })

    # 建立 domain → 主Agent 映射（domain_tags[0] 是该 Agent 的主领域，取第一个匹配）
    domain_primary: dict[str, tuple[str, float]] = {}
    for ai in agent_infos:
        if ai["domains"]:
            d = ai["domains"][0]
            if d not in domain_primary:
                domain_primary[d] = (ai["agent_name"], ai["importance"])

    # 对每个 domain 计算掌握状态（用主 Agent 的 importance）+ 构建去重节点
    # 🟢 绿：domain_confidence 标 high
    # 🟡 黄：domain_confidence 标 low，或未交互但 importance≥0.7（系统有优质资源）
    # 🔴 红：未交互且 importance<0.7
    nodes: list[HeatmapNode] = []
    blind_count = 0
    domain_status: dict[str, str] = {}
    seen_domains: set[str] = set()

    for ai in agent_infos:
        for d in ai["domains"]:
            if d not in seen_domains:
                seen_domains.add(d)
                # 优先用主 Agent 的 name 和 importance
                p_agent, p_imp = domain_primary.get(
                    d, (ai["agent_name"], ai["importance"])
                )
                if d in domain_confidence and domain_confidence[d] == "high":
                    status = "mastered"
                elif d in domain_confidence and domain_confidence[d] == "low":
                    status = "partial"
                elif p_imp >= 0.7:
                    status = "partial"
                else:
                    status = "blind"
                    blind_count += 1
                domain_status[d] = status
                nodes.append(HeatmapNode(
                    domain=d,
                    agent_name=p_agent,
                    status=status,
                    importance_score=round(p_imp, 2),
                    interacted=d in domain_confidence,
                ))

    # 汇总建议
    if blind_count >= 5:
        summary = f"你的知识盲区集中在 {blind_count} 个核心领域，建议从「基础概念」开始系统学习"
    elif blind_count >= 1:
        summary = f"还有 {blind_count} 个领域盲区，建议优先补齐红色节点"
    else:
        summary = "各领域均有覆盖，建议挑战进阶内容"

    heatmap = KnowledgeHeatmap(nodes=nodes, blind_count=blind_count, summary=summary)

    # ============================================================
    # 组件2：资源难度匹配曲线
    # ============================================================
    rows = query_all(
        "SELECT * FROM task_resource_stats WHERE session_id = ? ORDER BY created_at",
        (session_id,),
    )

    points: list[DifficultyMatchPoint] = []
    matched = 0
    total = 0

    for row in rows:
        domain = row["domain"] or "未知"
        diffs_raw = row["quiz_difficulties"]
        diffs = json.loads(diffs_raw) if diffs_raw else {}

        # 资源难度 = 各难度档分值 × 占比的加权平均
        total_q = sum(diffs.values()) if diffs else 0
        if total_q > 0:
            resource_score = sum(
                _DIFFICULTY_SCORE.get(k, 0.5) * v for k, v in diffs.items()
            ) / total_q
        else:
            resource_score = 0.5

        # 学生掌握水平：domain_confidence 有 → 用 confidence；无 → 用 level 基线
        if domain in domain_confidence:
            student_score = _CONFIDENCE_SCORE.get(
                domain_confidence[domain], level_score
            )
        else:
            student_score = level_score

        # 匹配状态：偏差 <0.2 算匹配良好
        gap = student_score - resource_score
        if abs(gap) < 0.2:
            match_status = "matched"
            matched += 1
        elif gap > 0:
            match_status = "too_easy"
        else:
            match_status = "too_hard"
        total += 1

        points.append(DifficultyMatchPoint(
            domain=domain,
            student_level=round(student_score, 2),
            resource_difficulty=round(resource_score, 2),
            match_status=match_status,
        ))

    overall_rate = round(matched / total, 2) if total > 0 else 0.0
    match_curve = DifficultyMatchCurve(
        points=points, overall_match_rate=overall_rate
    )

    # ============================================================
    # 组件3：学习路径规划图
    # ============================================================
    # 复用热力图阶段构建的 domain_status（含所有 domain_tags）

    stages: list[PathStage] = []
    for s in _LEARNING_STAGES:
        # 该阶段涉及领域中取最差状态
        statuses = [domain_status.get(d, "blind") for d in s["domains"]]
        if "blind" in statuses:
            stage_status = "blind"
        elif "partial" in statuses:
            stage_status = "partial"
        else:
            stage_status = "mastered"

        stages.append(PathStage(
            stage=s["stage"],
            title=s["title"],
            domains=s["domains"],
            estimated_hours=s["hours"],
            student_status=stage_status,
            recommended=(stage_status == "blind"),
        ))

    learning_path = LearningPath(stages=stages)

    # ============================================================
    # 组装报告
    # ============================================================
    return LearningReport(
        session_id=session_id,
        profile_summary={
            "knowledge_level": knowledge_level,
            "domain_hint": profile.get("domain_hint", []),
            "domain_confidence": domain_confidence,
        },
        knowledge_heatmap=heatmap,
        difficulty_match=match_curve,
        learning_path=learning_path,
    )
