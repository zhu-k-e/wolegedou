import React from "react";
import { X, BookOpen, Copy, Lightbulb, Network } from "lucide-react";

/**
 * 全屏内容页（讲义 / 实操指南共用）
 * - fixed 定位覆盖整个视口，右上角 ✕ 关闭，回到首页
 * - 复用 AnswerPanel 的渲染逻辑（title / content_markdown / difficulty / refs）
 * - pageTitle：顶部栏标题（默认"学习讲义"，实操指南页传入"实操指南"）
 */
function LecturePage({ lecture = {}, onClose, pageTitle = "学习讲义" }) {
    if (!lecture) return null;

    // 兼容两种传值：直接是对象，或者对象包在某个字段里
    const data = lecture.content_markdown || lecture.steps_markdown ? lecture : lecture.lecture || {};
    const title = data.title || data.goal || "AI 生成结果";
    const content = data.content_markdown || data.steps_markdown || "";
    const difficulty = data.difficulty_note || "";
    const refs = Array.isArray(data.knowledge_refs_display)
        ? data.knowledge_refs_display
        : [];

    const envSetup = data.env_setup || "";
    const expectedOutput = data.expected_output || "";
    const commonIssues = Array.isArray(data.common_issues) ? data.common_issues : [];

    function copyAnswer() {
        let fullText = content;
        if (envSetup) fullText += "\n\n【环境准备】\n" + envSetup;
        if (expectedOutput) fullText += "\n\n【预期产出】\n" + expectedOutput;
        if (commonIssues.length) fullText += "\n\n【常见问题】\n" + commonIssues.join("\n");
        navigator.clipboard.writeText(fullText);
        alert("内容已复制");
    }

    return (
        <div
            style={{
                position: "fixed",
                inset: 0,
                width: "100vw",
                height: "100vh",
                zIndex: 9999,
                background: "#1a1a2e",
                display: "flex",
                flexDirection: "column",
            }}
        >
            {/* 顶部栏 */}
            <div
                style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    padding: "14px 24px",
                    borderBottom: "1px solid rgba(255,255,255,0.08)",
                    background: "rgba(26,26,46,0.95)",
                    flexShrink: 0,
                }}
            >
                <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                    <BookOpen size={20} color="#8b5cf6" />
                    <span
                        style={{
                            fontSize: "17px",
                            fontWeight: "600",
                            color: "#e0e0ff",
                        }}
                    >
                        {pageTitle}
                    </span>
                </div>
                <button
                    onClick={onClose}
                    title="关闭"
                    style={{
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        width: "36px",
                        height: "36px",
                        borderRadius: "50%",
                        border: "1px solid rgba(255,255,255,0.15)",
                        background: "rgba(255,255,255,0.06)",
                        color: "#b8c4ff",
                        cursor: "pointer",
                        transition: "all 0.2s",
                        fontSize: "18px",
                    }}
                    onMouseEnter={(e) => {
                        e.currentTarget.style.background = "rgba(239,68,68,0.2)";
                        e.currentTarget.style.color = "#f87171";
                    }}
                    onMouseLeave={(e) => {
                        e.currentTarget.style.background = "rgba(255,255,255,0.06)";
                        e.currentTarget.style.color = "#b8c4ff";
                    }}
                >
                    <X size={20} />
                </button>
            </div>

            {/* 内容区（可滚动） */}
            <div
                style={{
                    flex: 1,
                    overflowY: "auto",
                    padding: "24px",
                    display: "flex",
                    justifyContent: "center",
                    alignItems: "flex-start",
                }}
            >
                <div
                    className="info-card"
                    style={{
                        width: "100%",
                        maxWidth: "860px",
                        margin: 0,
                        minHeight: 0,
                    }}
                >
                    <div className="card-title">
                        <h2>AI 生成结果</h2>
                    </div>

                    {/* 标题 */}
                    {title && (
                        <div className="answer-title">
                            <BookOpen size={18} />
                            <span>{title}</span>
                        </div>
                    )}

                    {/* 主要内容 */}
                    <div className="answer-box">{content}</div>

                    {/* 难度说明 */}
                    {difficulty && (
                        <div className="answer-difficulty">
                            <Lightbulb size={16} />
                            <span>{difficulty}</span>
                        </div>
                    )}

                    {/* 知识参考 */}
                    {refs.length > 0 && (
                        <div className="answer-refs">
                            <div className="refs-title">
                                <Network size={16} />
                                <span>关联知识</span>
                            </div>
                            <ul className="refs-list">
                                {refs.map((ref, idx) => {
                                    if (typeof ref === "string") {
                                        return <li key={idx}>{ref}</li>;
                                    }
                                    const source =
                                        ref?.source || ref?.content || JSON.stringify(ref);
                                    const status = ref?.verification_status;
                                    const isVerified =
                                        status === "verified" || status === "已验证";
                                    return (
                                        <li key={idx}>
                                            <span>{source}</span>
                                            {isVerified && (
                                                <span
                                                    style={{
                                                        marginLeft: 8,
                                                        color: "#10b981",
                                                    }}
                                                >
                                                    ✓ 已核实
                                                </span>
                                            )}
                                        </li>
                                    );
                                })}
                            </ul>
                        </div>
                    )}

                    {/* 实操指南补充字段（env_setup / expected_output / common_issues） */}
                    {envSetup && (
                        <div style={{ marginTop: "16px", padding: "12px 16px", borderRadius: "10px", background: "rgba(139,92,246,0.08)", border: "1px solid rgba(139,92,246,0.2)" }}>
                            <div style={{ display: "flex", alignItems: "center", gap: "6px", color: "#a78bfa", fontSize: "13px", fontWeight: "600", marginBottom: "6px" }}>
                                <Lightbulb size={14} /> 环境准备
                            </div>
                            <div style={{ color: "#d0d0e0", fontSize: "14px", lineHeight: "1.6" }}>{envSetup}</div>
                        </div>
                    )}

                    {expectedOutput && (
                        <div style={{ marginTop: "12px", padding: "12px 16px", borderRadius: "10px", background: "rgba(16,185,129,0.08)", border: "1px solid rgba(16,185,129,0.2)" }}>
                            <div style={{ display: "flex", alignItems: "center", gap: "6px", color: "#34d399", fontSize: "13px", fontWeight: "600", marginBottom: "6px" }}>
                                <BookOpen size={14} /> 预期产出
                            </div>
                            <div style={{ color: "#d0d0e0", fontSize: "14px", lineHeight: "1.6" }}>{expectedOutput}</div>
                        </div>
                    )}

                    {commonIssues.length > 0 && (
                        <div style={{ marginTop: "12px", padding: "12px 16px", borderRadius: "10px", background: "rgba(245,158,11,0.08)", border: "1px solid rgba(245,158,11,0.2)" }}>
                            <div style={{ display: "flex", alignItems: "center", gap: "6px", color: "#fbbf24", fontSize: "13px", fontWeight: "600", marginBottom: "6px" }}>
                                <Lightbulb size={14} /> 常见问题
                            </div>
                            <ul style={{ margin: 0, paddingLeft: "16px", color: "#d0d0e0", fontSize: "14px", lineHeight: "1.7" }}>
                                {commonIssues.map((issue, idx) => (
                                    <li key={idx}>{issue}</li>
                                ))}
                            </ul>
                        </div>
                    )}

                    <button className="small-button" onClick={copyAnswer}>
                        <Copy size={16} />
                        复制内容
                    </button>

                    <div className="disclaimer">
                        ⚠️ 以上内容由 AI 生成，仅供学习参考，请结合专业资料进行判断。
                    </div>
                </div>
            </div>
        </div>
    );
}

export default LecturePage;
