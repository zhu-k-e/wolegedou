import React, { useState, useEffect, useRef } from "react";
import { Brain, TrendingUp, Trophy, AlertTriangle, Activity, Zap, Clock, CheckCircle, XCircle, RefreshCw } from "lucide-react";
import { getMemoryStats } from "../api/api";

// ===========================
// Mock 数据（后端未启动时兜底，保证演示视频能录）
// 数据结构与真实返回一致，数值参考 API 文档示例
// ===========================
const MOCK_DATA = {
    alpha: 0.3,
    agent_count: 11,
    capability_count: 45,
    agents: [
        { agent_id: "agent_001", agent_name: "LLM基础Agent",       function_tag: "LLM原理与概念",  accuracy: 0.8835, count: 262, rework_rate: 0.0008, importance_score: 0.9415, is_suspended: false },
        { agent_id: "agent_002", agent_name: "Prompt工程Agent",     function_tag: "提示词工程",      accuracy: 0.8612, count: 198, rework_rate: 0.0021, importance_score: 0.9023, is_suspended: false },
        { agent_id: "agent_003", agent_name: "LangChain框架Agent",  function_tag: "框架应用",        accuracy: 0.8245, count: 156, rework_rate: 0.0150, importance_score: 0.8536, is_suspended: false },
        { agent_id: "agent_004", agent_name: "RAG知识增强Agent",     function_tag: "检索增强生成",    accuracy: 0.8367, count: 174, rework_rate: 0.0085, importance_score: 0.8781, is_suspended: false },
        { agent_id: "agent_005", agent_name: "HuggingFace调用Agent", function_tag: "模型调用",        accuracy: 0.7998, count: 112, rework_rate: 0.0230, importance_score: 0.8124, is_suspended: false },
        { agent_id: "agent_006", agent_name: "模型微调Agent",        function_tag: "微调训练",        accuracy: 0.7561, count: 88,  rework_rate: 0.0450, importance_score: 0.7456, is_suspended: false },
        { agent_id: "agent_007", agent_name: "向量数据库Agent",      function_tag: "向量检索",        accuracy: 0.8154, count: 134, rework_rate: 0.0120, importance_score: 0.8301, is_suspended: false },
        { agent_id: "agent_008", agent_name: "智能体框架Agent",      function_tag: "Agent编排",       accuracy: 0.7723, count: 96,  rework_rate: 0.0300, importance_score: 0.7689, is_suspended: false },
        { agent_id: "agent_009", agent_name: "项目部署Agent",        function_tag: "项目架构与落地",  accuracy: 0.8245, count: 90,  rework_rate: 0.0895, importance_score: 0.8654, is_suspended: false },
        { agent_id: "agent_010", agent_name: "代码调试Agent",        function_tag: "代码排错",        accuracy: 0.7012, count: 64,  rework_rate: 0.0670, importance_score: 0.6890, is_suspended: true  },
    ],
    recent_contributions: [
        { task_id: "task_1962d568c305", agent_id: "agent_001", function_tag: "LLM原理与概念",  review_score: 0.8833, importance_score: 0.9415, referee_verdict: "passed",               created_at: "2026-08-17 11:29:26" },
        { task_id: "task_1962d568c305", agent_id: "agent_004", function_tag: "检索增强生成",    review_score: 0.8567, importance_score: 0.8781, referee_verdict: "passed",               created_at: "2026-08-17 11:28:14" },
        { task_id: "task_1962d568c305", agent_id: "agent_002", function_tag: "提示词工程",      review_score: 0.7912, importance_score: 0.9023, referee_verdict: "low_confidence_passed", created_at: "2026-08-17 11:27:03" },
        { task_id: "task_1a3f5e7b9c22", agent_id: "agent_009", function_tag: "项目架构与落地",  review_score: 0.8445, importance_score: 0.8654, referee_verdict: "passed",               created_at: "2026-08-17 10:45:38" },
        { task_id: "task_1a3f5e7b9c22", agent_id: "agent_006", function_tag: "微调训练",        review_score: 0.6234, importance_score: 0.7456, referee_verdict: "revise",                created_at: "2026-08-17 10:44:21" },
        { task_id: "task_0e2c4a6b8d11", agent_id: "agent_010", function_tag: "代码排错",        review_score: 0.4521, importance_score: 0.6890, referee_verdict: "failed",                created_at: "2026-08-16 18:33:15" },
        { task_id: "task_0e2c4a6b8d11", agent_id: "agent_008", function_tag: "Agent编排",       review_score: 0.7789, importance_score: 0.7689, referee_verdict: "passed",               created_at: "2026-08-16 18:32:08" },
        { task_id: "task_0e2c4a6b8d11", agent_id: "agent_005", function_tag: "模型调用",        review_score: 0.8102, importance_score: 0.8124, referee_verdict: "passed",               created_at: "2026-08-16 18:31:42" },
    ],
    eliminations: [
        { agent_id: "agent_010", function_tag: "代码排错", reason: "连续5次importance_score<0.7阈值，触发淘汰机制", created_at: "2026-08-16 19:05:00" },
    ],
};

// ===========================
// 工具函数
// ===========================
function safeArray(val) {
    if (Array.isArray(val)) return val;
    if (val && typeof val === "object") return Object.values(val);
    return [];
}

function verdictConfig(verdict) {
    switch (verdict) {
        case "passed":               return { label: "通过",   color: "#4ade80", bg: "rgba(74,222,128,0.15)",  icon: CheckCircle };
        case "low_confidence_passed":return { label: "低置信通过", color: "#fbbf24", bg: "rgba(251,191,36,0.15)", icon: AlertTriangle };
        case "revise":               return { label: "需修订", color: "#f59e0b", bg: "rgba(245,158,11,0.15)",  icon: AlertTriangle };
        case "failed":               return { label: "未通过", color: "#ef4444", bg: "rgba(239,68,68,0.15)",   icon: XCircle };
        default:                     return { label: verdict || "未知", color: "#94a3b8", bg: "rgba(148,163,184,0.15)", icon: Activity };
    }
}

// 根据重要性分数返回颜色梯度
function scoreColor(score) {
    if (score >= 0.9) return { from: "#22c55e", to: "#15803d" };  // 绿 — 核心贡献者
    if (score >= 0.8) return { from: "#3b82f6", to: "#1d4ed8" };  // 蓝 — 高贡献
    if (score >= 0.7) return { from: "#8b5cf6", to: "#6d28d9" };  // 紫 — 中等贡献
    return { from: "#f59e0b", to: "#b45309" };                     // 橙 — 低贡献
}

// ===========================
// 主组件
// ===========================
function MemoryStatsPanel({ taskComplete }) {
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState("");
    const [usingMock, setUsingMock] = useState(false);
    const [expanded, setExpanded] = useState(false);       // 最近贡献流展开
    const [showAllAgents, setShowAllAgents] = useState(false); // Agent 贡献排行展开
    const fetchRef = useRef(false);

    useEffect(() => {
        if (!taskComplete) return;
        if (fetchRef.current) return;
        fetchRef.current = true;
        fetchData();
    }, [taskComplete]);

    const fetchData = async () => {
        setLoading(true);
        setError("");
        try {
            const res = await getMemoryStats();
            if (res && (res.agents || res.recent_contributions)) {
                setData(res);
                setUsingMock(false);
            } else {
                // 后端返回了但数据为空，兜底
                setData(MOCK_DATA);
                setUsingMock(true);
            }
        } catch (err) {
            console.warn("memory_stats 接口不可用，使用演示数据:", err?.message);
            setData(MOCK_DATA);
            setUsingMock(true);
        } finally {
            setLoading(false);
        }
    };

    if (!taskComplete) return null;

    if (loading) {
        return (
            <div className="info-card" style={{ textAlign: "center", padding: "40px" }}>
                <RefreshCw size={28} style={{ animation: "spin 1.5s linear infinite", color: "#8b5cf6" }} />
                <p style={{ color: "#b8c4ff", fontSize: "14px", marginTop: "12px" }}>
                    正在获取多智能体贡献记忆数据…
                </p>
            </div>
        );
    }

    if (!data) return null;

    const agents = safeArray(data.agents);
    const contributions = safeArray(data.recent_contributions);
    const eliminations = safeArray(data.eliminations);
    const alpha = typeof data.alpha === "number" ? data.alpha : 0.3;
    const agentCount = typeof data.agent_count === "number" ? data.agent_count : agents.length;
    const capabilityCount = typeof data.capability_count === "number" ? data.capability_count : 45;
    const maxScore = agents.length > 0 ? Math.max(...agents.map(a => a.importance_score || 0)) : 1;

    // 统计
    const activeAgents = agents.filter(a => !a.is_suspended).length;
    const suspendedAgents = agents.filter(a => a.is_suspended).length;
    const passedCount = contributions.filter(c => c.referee_verdict === "passed").length;
    const revisedCount = contributions.filter(c => c.referee_verdict === "revise" || c.referee_verdict === "low_confidence_passed").length;

    // 排行默认只展示前 6 名，其余折叠（与历史记录/动态调度面板交互一致）
    const visibleAgents = showAllAgents ? agents : agents.slice(0, 6);
    const hiddenAgentCount = agents.length - visibleAgents.length;

    return (
        <div className="info-card" style={{
            borderColor: "rgba(139,92,246,0.35)",
            boxShadow: "0 20px 50px rgba(139,92,246,0.15)",
        }}>
            {/* 卡片标题 */}
            <div className="card-title" style={{ marginBottom: "6px" }}>
                <Brain size={24} style={{ color: "#8b5cf6" }} />
                <h2>多智能体贡献记忆闭环</h2>
                {usingMock && (
                    <span style={{
                        marginLeft: "auto",
                        fontSize: "11px",
                        color: "#fbbf24",
                        background: "rgba(251,191,36,0.12)",
                        padding: "3px 10px",
                        borderRadius: "10px",
                        border: "1px solid rgba(251,191,36,0.25)",
                    }}>
                        演示数据
                    </span>
                )}
                <button
                    onClick={fetchData}
                    style={{
                        marginLeft: usingMock ? "0" : "auto",
                        background: "rgba(139,92,246,0.15)",
                        border: "1px solid rgba(139,92,246,0.3)",
                        borderRadius: "10px",
                        padding: "6px 12px",
                        color: "#c4b5fd",
                        cursor: "pointer",
                        fontSize: "12px",
                        display: "flex",
                        alignItems: "center",
                        gap: "5px",
                        transition: "all 0.2s",
                    }}
                >
                    <RefreshCw size={13} /> 刷新
                </button>
            </div>

            <p className="description" style={{ marginBottom: "20px", fontSize: "13px" }}>
                每次任务完成后，系统记录各 Agent 贡献、EMA 更新表现分、动态调整调度权重 α、淘汰低表现 Agent ——
                <span style={{ color: "#a78bfa" }}>系统越用越聪明，实现优胜劣汰。</span>
            </p>

            {/* ===== 第一部分：核心指标卡片 ===== */}
            <div style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
                gap: "12px",
                marginBottom: "24px",
            }}>
                {/* α 权重 */}
                <div style={{
                    background: "linear-gradient(135deg, rgba(59,130,246,0.12), rgba(139,92,246,0.08))",
                    border: "1px solid rgba(59,130,246,0.25)",
                    borderRadius: "14px",
                    padding: "16px",
                    textAlign: "center",
                }}>
                    <Zap size={20} style={{ color: "#60a5fa", marginBottom: "6px" }} />
                    <div style={{ fontSize: "28px", fontWeight: "700", color: "#60a5fa" }}>
                        {alpha.toFixed(2)}
                    </div>
                    <div style={{ fontSize: "11px", color: "#94a3b8", marginTop: "2px" }}>
                        调度权重 α
                    </div>
                    <div style={{ fontSize: "10px", color: "#64748b", marginTop: "4px" }}>
                        冷启动 0.9 → 已降至 0.{Math.round(alpha * 10)}
                    </div>
                </div>

                {/* Agent 与能力维度 */}
                <div style={{
                    background: "linear-gradient(135deg, rgba(139,92,246,0.12), rgba(168,85,247,0.08))",
                    border: "1px solid rgba(139,92,246,0.25)",
                    borderRadius: "14px",
                    padding: "16px",
                    textAlign: "center",
                }}>
                    <Brain size={20} style={{ color: "#a78bfa", marginBottom: "6px" }} />
                    <div style={{ fontSize: "20px", fontWeight: "700", color: "#a78bfa", lineHeight: "1.3" }}>
                        {agentCount}<span style={{ fontSize: "13px", fontWeight: "500" }}> 个领域 Agent</span>
                    </div>
                    <div style={{ fontSize: "12px", color: "#a78bfa", marginTop: "2px", fontWeight: "500" }}>
                        覆盖 {capabilityCount} 个能力维度
                    </div>
                    <div style={{ fontSize: "10px", color: "#64748b", marginTop: "6px" }}>
                        活跃 {activeAgents} · 淘汰 {suspendedAgents}
                    </div>
                </div>

                {/* 贡献通过率 */}
                <div style={{
                    background: "linear-gradient(135deg, rgba(34,197,94,0.12), rgba(22,163,74,0.08))",
                    border: "1px solid rgba(34,197,94,0.25)",
                    borderRadius: "14px",
                    padding: "16px",
                    textAlign: "center",
                }}>
                    <CheckCircle size={20} style={{ color: "#4ade80", marginBottom: "6px" }} />
                    <div style={{ fontSize: "28px", fontWeight: "700", color: "#4ade80" }}>
                        {contributions.length > 0 ? Math.round((passedCount / contributions.length) * 100) : 0}%
                    </div>
                    <div style={{ fontSize: "11px", color: "#94a3b8", marginTop: "2px" }}>
                        裁判通过率
                    </div>
                    <div style={{ fontSize: "10px", color: "#64748b", marginTop: "4px" }}>
                        通过 {passedCount} · 修订 {revisedCount}
                    </div>
                </div>

                {/* 贡献记录数 */}
                <div style={{
                    background: "linear-gradient(135deg, rgba(245,158,11,0.12), rgba(217,119,6,0.08))",
                    border: "1px solid rgba(245,158,11,0.25)",
                    borderRadius: "14px",
                    padding: "16px",
                    textAlign: "center",
                }}>
                    <TrendingUp size={20} style={{ color: "#fbbf24", marginBottom: "6px" }} />
                    <div style={{ fontSize: "28px", fontWeight: "700", color: "#fbbf24" }}>
                        {contributions.length}
                    </div>
                    <div style={{ fontSize: "11px", color: "#94a3b8", marginTop: "2px" }}>
                        最近贡献记录
                    </div>
                    <div style={{ fontSize: "10px", color: "#64748b", marginTop: "4px" }}>
                        淘汰 {eliminations.length} 个 Agent
                    </div>
                </div>
            </div>

            {/* ===== 第二部分：Agent 贡献分排行 ===== */}
            <div style={{ marginBottom: "24px" }}>
                <div style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "8px",
                    marginBottom: "14px",
                    fontSize: "15px",
                    fontWeight: "600",
                    color: "#e0e0ff",
                }}>
                    <Trophy size={18} style={{ color: "#fbbf24" }} />
                    Agent 贡献分排行
                    <span style={{ fontSize: "11px", color: "#64748b", fontWeight: "400" }}>
                        按 importance_score 降序
                    </span>
                </div>

                <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                    {visibleAgents.map((agent, idx) => {
                        const score = agent.importance_score || 0;
                        const widthPct = maxScore > 0 ? (score / maxScore) * 100 : 0;
                        const colors = scoreColor(score);
                        const isTop = idx === 0;
                        const isSuspended = agent.is_suspended;

                        return (
                            <div
                                key={agent.agent_id || idx}
                                style={{
                                    display: "flex",
                                    alignItems: "center",
                                    gap: "12px",
                                    padding: "10px 14px",
                                    borderRadius: "12px",
                                    background: isSuspended
                                        ? "rgba(239,68,68,0.06)"
                                        : "rgba(255,255,255,0.04)",
                                    border: isSuspended
                                        ? "1px solid rgba(239,68,68,0.2)"
                                        : "1px solid rgba(255,255,255,0.08)",
                                    opacity: isSuspended ? 0.6 : 1,
                                }}
                            >
                                {/* 排名 */}
                                <div style={{
                                    width: "28px",
                                    height: "28px",
                                    borderRadius: "8px",
                                    display: "flex",
                                    alignItems: "center",
                                    justifyContent: "center",
                                    fontSize: "13px",
                                    fontWeight: "700",
                                    flexShrink: 0,
                                    background: isTop ? "linear-gradient(135deg, #fbbf24, #d97706)"
                                        : idx === 1 ? "linear-gradient(135deg, #94a3b8, #64748b)"
                                        : idx === 2 ? "linear-gradient(135deg, #b45309, #92400e)"
                                        : "rgba(255,255,255,0.06)",
                                    color: isTop || idx === 1 || idx === 2 ? "#fff" : "#94a3b8",
                                }}>
                                    {isTop ? "★" : idx + 1}
                                </div>

                                {/* Agent 信息 */}
                                <div style={{ flex: "1", minWidth: "0" }}>
                                    <div style={{
                                        display: "flex",
                                        alignItems: "center",
                                        gap: "6px",
                                        marginBottom: "4px",
                                    }}>
                                        <span style={{
                                            fontSize: "13px",
                                            fontWeight: "600",
                                            color: isSuspended ? "#94a3b8" : "#e0e0ff",
                                            overflow: "hidden",
                                            textOverflow: "ellipsis",
                                            whiteSpace: "nowrap",
                                        }}>
                                            {agent.agent_name || agent.agent_id}
                                        </span>
                                        {isSuspended && (
                                            <span style={{
                                                fontSize: "9px",
                                                color: "#ef4444",
                                                background: "rgba(239,68,68,0.15)",
                                                padding: "1px 6px",
                                                borderRadius: "6px",
                                                flexShrink: 0,
                                            }}>
                                                已淘汰
                                            </span>
                                        )}
                                        <span style={{
                                            fontSize: "10px",
                                            color: "#64748b",
                                            overflow: "hidden",
                                            textOverflow: "ellipsis",
                                            whiteSpace: "nowrap",
                                        }}>
                                            {agent.function_tag}
                                        </span>
                                    </div>

                                    {/* 贡献分进度条 */}
                                    <div style={{
                                        height: "8px",
                                        borderRadius: "4px",
                                        background: "rgba(0,0,0,0.3)",
                                        overflow: "hidden",
                                        position: "relative",
                                    }}>
                                        <div style={{
                                            height: "100%",
                                            width: `${widthPct}%`,
                                            borderRadius: "4px",
                                            background: `linear-gradient(90deg, ${colors.from}, ${colors.to})`,
                                            transition: "width 1s ease-out",
                                            boxShadow: isTop ? `0 0 8px ${colors.from}80` : "none",
                                        }} />
                                    </div>
                                </div>

                                {/* 数据指标 */}
                                <div style={{
                                    display: "flex",
                                    gap: "16px",
                                    flexShrink: 0,
                                    fontSize: "11px",
                                }}>
                                    <div style={{ textAlign: "center", minWidth: "50px" }}>
                                        <div style={{ color: "#64748b", fontSize: "9px" }}>贡献分</div>
                                        <div style={{
                                            color: colors.from,
                                            fontWeight: "700",
                                            fontSize: "14px",
                                        }}>
                                            {score.toFixed(2)}
                                        </div>
                                    </div>
                                    <div style={{ textAlign: "center", minWidth: "45px" }}>
                                        <div style={{ color: "#64748b", fontSize: "9px" }}>准确率</div>
                                        <div style={{
                                            color: "#94a3b8",
                                            fontWeight: "600",
                                            fontSize: "13px",
                                        }}>
                                            {((agent.accuracy || 0) * 100).toFixed(1)}%
                                        </div>
                                    </div>
                                    <div style={{ textAlign: "center", minWidth: "40px" }}>
                                        <div style={{ color: "#64748b", fontSize: "9px" }}>参与</div>
                                        <div style={{
                                            color: "#94a3b8",
                                            fontWeight: "600",
                                            fontSize: "13px",
                                        }}>
                                            {agent.count || 0}
                                        </div>
                                    </div>
                                </div>
                            </div>
                        );
                    })}
                </div>

                {agents.length > 6 && (
                    <div style={{ textAlign: "center", marginTop: "10px" }}>
                        <button
                            onClick={() => setShowAllAgents(!showAllAgents)}
                            style={{
                                background: "rgba(139,92,246,0.12)",
                                border: "1px solid rgba(139,92,246,0.25)",
                                borderRadius: "10px",
                                padding: "6px 20px",
                                color: "#a78bfa",
                                cursor: "pointer",
                                fontSize: "12px",
                                transition: "all 0.2s",
                            }}
                        >
                            {showAllAgents
                                ? "▾ 收起排行"
                                : `▸ 展开全部（共 ${agents.length} 个，还有 ${hiddenAgentCount} 个）`}
                        </button>
                    </div>
                )}
            </div>

            {/* ===== 第三部分：最近贡献流 ===== */}
            <div style={{ marginBottom: "20px" }}>
                <div style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "8px",
                    marginBottom: "14px",
                    fontSize: "15px",
                    fontWeight: "600",
                    color: "#e0e0ff",
                }}>
                    <Clock size={18} style={{ color: "#60a5fa" }} />
                    最近贡献流
                    <span style={{ fontSize: "11px", color: "#64748b", fontWeight: "400" }}>
                        最近 {contributions.length} 条记录
                    </span>
                </div>

                <div style={{
                    maxHeight: expanded ? "none" : "280px",
                    overflow: "hidden",
                    position: "relative",
                }}>
                    <div style={{
                        display: "flex",
                        flexDirection: "column",
                        gap: "6px",
                    }}>
                        {contributions.map((c, idx) => {
                            const vc = verdictConfig(c.referee_verdict);
                            const VIcon = vc.icon;
                            const agentName = agents.find(a => a.agent_id === c.agent_id)?.agent_name || c.agent_id;
                            return (
                                <div
                                    key={idx}
                                    style={{
                                        display: "flex",
                                        alignItems: "center",
                                        gap: "12px",
                                        padding: "10px 14px",
                                        borderRadius: "10px",
                                        background: "rgba(255,255,255,0.03)",
                                        border: "1px solid rgba(255,255,255,0.06)",
                                        fontSize: "12px",
                                    }}
                                >
                                    {/* 时间线圆点 */}
                                    <div style={{
                                        width: "10px",
                                        height: "10px",
                                        borderRadius: "50%",
                                        flexShrink: 0,
                                        background: vc.color,
                                        boxShadow: `0 0 6px ${vc.color}60`,
                                    }} />

                                    {/* Agent 名称 + 职能 */}
                                    <div style={{ flex: "1", minWidth: "0" }}>
                                        <span style={{ color: "#e0e0ff", fontWeight: "600" }}>
                                            {agentName}
                                        </span>
                                        <span style={{ color: "#64748b", margin: "0 6px" }}>·</span>
                                        <span style={{ color: "#94a3b8" }}>{c.function_tag}</span>
                                    </div>

                                    {/* 评分 */}
                                    <div style={{ textAlign: "center", flexShrink: 0 }}>
                                        <div style={{ fontSize: "9px", color: "#64748b" }}>评分</div>
                                        <div style={{
                                            color: "#e0e0ff",
                                            fontWeight: "700",
                                            fontSize: "13px",
                                        }}>
                                            {((c.review_score || 0) * 100).toFixed(0)}
                                        </div>
                                    </div>

                                    {/* 裁判结论 */}
                                    <div style={{
                                        display: "flex",
                                        alignItems: "center",
                                        gap: "4px",
                                        padding: "3px 10px",
                                        borderRadius: "8px",
                                        background: vc.bg,
                                        color: vc.color,
                                        fontSize: "11px",
                                        fontWeight: "600",
                                        flexShrink: 0,
                                    }}>
                                        <VIcon size={12} />
                                        {vc.label}
                                    </div>

                                    {/* 时间 */}
                                    <div style={{
                                        fontSize: "10px",
                                        color: "#475569",
                                        flexShrink: 0,
                                        minWidth: "80px",
                                        textAlign: "right",
                                    }}>
                                        {c.created_at || ""}
                                    </div>
                                </div>
                            );
                        })}
                    </div>

                    {/* 渐变遮罩 */}
                    {!expanded && contributions.length > 5 && (
                        <div style={{
                            position: "absolute",
                            bottom: 0,
                            left: 0,
                            right: 0,
                            height: "50px",
                            background: "linear-gradient(transparent, rgba(20,20,40,0.9))",
                            pointerEvents: "none",
                        }} />
                    )}
                </div>

                {contributions.length > 5 && (
                    <div style={{ textAlign: "center", marginTop: "8px" }}>
                        <button
                            onClick={() => setExpanded(!expanded)}
                            style={{
                                background: "rgba(139,92,246,0.12)",
                                border: "1px solid rgba(139,92,246,0.25)",
                                borderRadius: "10px",
                                padding: "6px 20px",
                                color: "#a78bfa",
                                cursor: "pointer",
                                fontSize: "12px",
                                transition: "all 0.2s",
                            }}
                        >
                            {expanded ? "收起" : `展开全部 ${contributions.length} 条`}
                        </button>
                    </div>
                )}
            </div>

            {/* ===== 第四部分：淘汰记录 ===== */}
            {eliminations.length > 0 && (
                <div>
                    <div style={{
                        display: "flex",
                        alignItems: "center",
                        gap: "8px",
                        marginBottom: "12px",
                        fontSize: "15px",
                        fontWeight: "600",
                        color: "#f87171",
                    }}>
                        <AlertTriangle size={18} />
                        Agent 淘汰记录
                    </div>
                    <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                        {eliminations.map((e, idx) => (
                            <div
                                key={idx}
                                style={{
                                    display: "flex",
                                    alignItems: "center",
                                    gap: "12px",
                                    padding: "12px 14px",
                                    borderRadius: "10px",
                                    background: "rgba(239,68,68,0.06)",
                                    border: "1px solid rgba(239,68,68,0.2)",
                                }}
                            >
                                <XCircle size={18} style={{ color: "#ef4444", flexShrink: 0 }} />
                                <div style={{ flex: "1" }}>
                                    <div style={{ fontSize: "13px", color: "#e0e0ff", fontWeight: "600" }}>
                                        Agent {e.agent_id}
                                        <span style={{ color: "#64748b", fontWeight: "400", marginLeft: "6px" }}>
                                            ({e.function_tag})
                                        </span>
                                    </div>
                                    <div style={{ fontSize: "11px", color: "#94a3b8", marginTop: "2px" }}>
                                        {e.reason}
                                    </div>
                                </div>
                                <div style={{ fontSize: "10px", color: "#475569", flexShrink: 0 }}>
                                    {e.created_at || ""}
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            )}
        </div>
    );
}

export default MemoryStatsPanel;
