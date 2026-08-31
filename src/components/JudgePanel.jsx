import React from "react";
import { ShieldCheck, Award, BarChart3 } from "lucide-react";

/**
 * 从后端 judge_verdict 中提取裁判评价文本列表
 * 兼容两种结构：
 * 1. { opinions: ["...", ...] }                           —— 旧结构
 * 2. { judges: [{ role, judgment, evidence, confidence }] }  —— 后端实际结构
 */
function extractOpinions(judge) {
    // 旧结构
    if (Array.isArray(judge?.opinions)) {
        return judge.opinions;
    }

    // 新结构：从 judges 数组提取
    if (Array.isArray(judge?.judges)) {
        return judge.judges
            .filter((j) => j && j.role)
            .map((j) => `${j.role}：${j.judgment === "pass" ? "通过" : "未通过"}（置信度 ${Math.round((j.confidence || 0) * 100)}%）`);
    }

    return [];
}

/**
 * 提取参考来源列表
 * 兼容 judge.sources（旧）和 judge.traceability（新）
 */
function extractSources(judge) {
    if (Array.isArray(judge?.sources)) {
        return judge.sources;
    }
    if (Array.isArray(judge?.traceability)) {
        return judge.traceability
            .filter((t) => t && t.source)
            .map((t) => t.source);
    }
    return [];
}

function JudgePanel({ judge, reviewSummary }) {
    if (!judge) return null;

    // verdict 兼容 "pass" / "passed"
    const isPassed = judge.verdict === "pass" || judge.verdict === "passed";

    const opinions = extractOpinions(judge);
    const sources = extractSources(judge);

    return (
        <div className="info-card">
            <div className="card-title">
                <ShieldCheck size={24} />
                <h2>多Agent裁判结果</h2>
            </div>

            <div className="judge-status">
                <Award size={22} />
                {isPassed ? "审核通过" : "需要进一步优化"}
            </div>

            <div className="judge-content">
                <h4>综合评价</h4>
                <p>
                    {opinions.length > 0
                        ? opinions.join("；")
                        : "多个智能体输出经过审核与综合评估，结果符合学习目标。"}
                </p>
            </div>

            {/* 三维度评分 */}
            {reviewSummary && (
                <div style={{ marginTop: "18px" }}>
                    <h4 style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                        <BarChart3 size={16} style={{ color: "#a78bfa" }} />
                        质量评分
                    </h4>
                    <div style={{ display: "flex", flexDirection: "column", gap: "12px", marginTop: "10px" }}>
                        {[
                            { key: "fact_accuracy", label: "事实准确性" },
                            { key: "logic_completeness", label: "逻辑完整性" },
                            { key: "pedagogical_fit", label: "教学适用性" },
                        ].map(({ key, label }) => {
                            const score = reviewSummary[key];
                            if (typeof score !== "number") return null;
                            const pct = Math.round(score * 100);
                            const barColor =
                                score >= 0.9
                                    ? "#4ade80"
                                    : score >= 0.75
                                        ? "#fbbf24"
                                        : "#f87171";
                            return (
                                <div key={key}>
                                    <div
                                        style={{
                                            display: "flex",
                                            justifyContent: "space-between",
                                            fontSize: "13px",
                                            color: "#c4c8e0",
                                            marginBottom: "4px",
                                        }}
                                    >
                                        <span>{label}</span>
                                        <span style={{ color: barColor, fontWeight: 600 }}>
                                            {pct}%
                                        </span>
                                    </div>
                                    <div
                                        style={{
                                            height: "6px",
                                            borderRadius: "3px",
                                            background: "rgba(255,255,255,0.08)",
                                            overflow: "hidden",
                                        }}
                                    >
                                        <div
                                            style={{
                                                width: `${pct}%`,
                                                height: "100%",
                                                borderRadius: "3px",
                                                background: barColor,
                                                transition: "width 0.6s ease",
                                            }}
                                        />
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                </div>
            )}

            {sources.length > 0 && (
                <div>
                    <h4>参考来源</h4>
                    {sources.map((item, index) => (
                        <p key={index} style={{ fontSize: "13px", color: "#b8c4ff", marginBottom: "6px" }}>
                            {item}
                        </p>
                    ))}
                </div>
            )}
        </div>
    );
}

export default JudgePanel;
