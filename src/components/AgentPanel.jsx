import React, { useState } from "react";
import { Bot, Network, ChevronDown, ChevronRight } from "lucide-react";

// Agent中文名称映射
const agentNameMap = {
    agent_001: "大语言模型基础 Agent",
    agent_002: "Prompt工程 Agent",
    agent_003: "LangChain框架 Agent",
    agent_004: "RAG知识增强 Agent",
    agent_005: "HuggingFace模型调用 Agent",
    agent_006: "模型微调 Agent",
    agent_007: "向量数据库 Agent",
    agent_008: "智能体框架 Agent",
    agent_009: "项目部署 Agent",
    agent_010: "代码调试 Agent",
};

/**
 * 从后端 dispatch_info 中提取 agent_id 列表
 * 兼容两种结构：
 * 1. { selected_agents: ["agent_004", ...] }           —— 旧结构
 * 2. { segments: [{ candidates: [{ agent_id: "agent_004" }] }] }  —— 后端实际结构
 */
function extractAgents(dispatchInfo) {
    if (!dispatchInfo) return [];

    // 旧结构：直接是字符串数组
    if (Array.isArray(dispatchInfo.selected_agents)) {
        return dispatchInfo.selected_agents;
    }

    // 新结构：从 segments → candidates → agent_id 提取
    const agents = [];
    if (Array.isArray(dispatchInfo.segments)) {
        dispatchInfo.segments.forEach((seg) => {
            if (Array.isArray(seg.candidates)) {
                seg.candidates.forEach((c) => {
                    if (c.agent_id && !agents.includes(c.agent_id)) {
                        agents.push(c.agent_id);
                    }
                });
            }
            // 兼容：segment 本身可能直接有 agent_id
            if (seg.agent_id && !agents.includes(seg.agent_id)) {
                agents.push(seg.agent_id);
            }
        });
    }

    // 兜底：扫描 dispatch_info 所有数组属性，找 agent_id
    if (agents.length === 0) {
        Object.values(dispatchInfo).forEach((val) => {
            if (Array.isArray(val)) {
                val.forEach((item) => {
                    if (typeof item === "string" && item.startsWith("agent_")) {
                        agents.push(item);
                    }
                    if (item && typeof item === "object" && item.agent_id) {
                        agents.push(item.agent_id);
                    }
                    if (Array.isArray(item?.candidates)) {
                        item.candidates.forEach((c) => {
                            if (c?.agent_id) agents.push(c.agent_id);
                        });
                    }
                });
            }
        });
    }

    return agents;
}

function AgentPanel({ dispatchInfo }) {
    const [showAll, setShowAll] = useState(false);

    if (!dispatchInfo) return null;

    const agents = extractAgents(dispatchInfo);
    const intent = dispatchInfo.intent || "";
    const MAX_SHOW = 5;
    const visibleAgents = showAll ? agents : agents.slice(0, MAX_SHOW);
    const hiddenCount = agents.length - visibleAgents.length;

    return (
        <div className="info-card">
            <div className="card-title">
                <Network size={24} />
                <h2>Agent动态调度</h2>
            </div>

            <p className="description">
                系统根据任务需求，自动选择最适合的智能体进行协同。
            </p>

            {intent && (
                <p style={{ color: "#b8c4ff", fontSize: "13px", marginBottom: "12px" }}>
                    调度意图：{intent}
                </p>
            )}

            <div className="agent-list">
                {agents.length > 0 ? (
                    visibleAgents.map((agent, index) => (
                        <div className="agent-node" key={agent || index}>
                            <Bot size={22} />
                            <div>
                                <h3>{agentNameMap[agent] || agent}</h3>
                                <p>智能体编号：{agent}</p>
                            </div>
                        </div>
                    ))
                ) : (
                    <p style={{ color: "#888", fontSize: "14px" }}>
                        未获取到调度信息
                    </p>
                )}
            </div>

            {/* 展开/收起按钮：默认只展示前 5 个 */}
            {agents.length > MAX_SHOW && (
                <button
                    onClick={() => setShowAll(!showAll)}
                    style={{
                        display: "flex",
                        alignItems: "center",
                        gap: "6px",
                        margin: "12px auto 0",
                        padding: "8px 16px",
                        borderRadius: "999px",
                        border: "1px solid rgba(59,130,246,0.4)",
                        background: "rgba(59,130,246,0.08)",
                        color: "#93b4ff",
                        fontSize: "13px",
                        fontWeight: "500",
                        cursor: "pointer",
                        transition: "all 0.2s",
                    }}
                    onMouseEnter={(e) => {
                        e.currentTarget.style.background = "rgba(59,130,246,0.18)";
                    }}
                    onMouseLeave={(e) => {
                        e.currentTarget.style.background = "rgba(59,130,246,0.08)";
                    }}
                >
                    {showAll ? (
                        <><ChevronDown size={14} /> 收起（还有 {hiddenCount} 个已展示）</>
                    ) : (
                        <><ChevronRight size={14} /> 展开全部（共 {agents.length} 个，还有 {hiddenCount} 个）</>
                    )}
                </button>
            )}

            <div className="agent-flow">
                多个 Agent 协同工作，共同完成学习任务。
            </div>
        </div>
    );
}

export default AgentPanel;
