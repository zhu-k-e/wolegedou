import React from "react";
import { X, ClipboardList } from "lucide-react";
import Quiz from "./Quiz";
import Feedback from "./Feedback";

/**
 * 全屏测试题页
 * - fixed 定位覆盖整个视口，右上角 ✕ 关闭，回到首页
 * - 复用 Quiz 组件（做题 → 提交 → 按正确率分档显示解析 → 重新测试/关闭测试）
 * - 支持自适应出题：正确率 <85% 降难度 / ≥85% 在当前级别上限内小幅升难度（对齐后端 0.85 单阈值）
 * - 底部紧跟反馈组件（有用/没用/有点难）
 */
function QuizPage({
    quiz = {},
    taskId,
    sessionId,
    feedbackAgentId,
    feedbackFunctionTag,
    onClose,
    // ===== 自适应出题相关（App.jsx 提供）=====
    onRegenerate,          // (accuracy:number) => void 触发重新出题
    adaptiveState = "idle", // idle | generating | ready | error
    adaptiveQuiz = null,    // 自适应生成的新题目（有值时替换原题目展示）
    adaptiveRound = 0,      // 自适应轮次（0 = 第一轮原始题）
    adaptiveDirection = "", // easier | harder
    userLevel = "入门",
    onFollowupClick,        // (question:string) => void 点击启发式追问，开启新一轮学习
}) {
    // 展示的题目：自适应生成的新题优先于原始题
    const displayQuiz = adaptiveQuiz || quiz;
    const currentRound = adaptiveRound + 1;

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
                    <ClipboardList size={20} color="#8b5cf6" />
                    <span
                        style={{
                            fontSize: "17px",
                            fontWeight: "600",
                            color: "#e0e0ff",
                        }}
                    >
                        学习效果测试
                    </span>
                    {/* 轮次徽章：第 2 轮起显示自适应标识 */}
                    {adaptiveRound > 0 && (
                        <span
                            style={{
                                fontSize: "12px",
                                fontWeight: "600",
                                padding: "3px 10px",
                                borderRadius: "999px",
                                color: adaptiveDirection === "easier" ? "#fbbf24" : "#c4b5fd",
                                background: adaptiveDirection === "easier"
                                    ? "rgba(251,191,36,0.12)"
                                    : "rgba(139,92,246,0.12)",
                                border: adaptiveDirection === "easier"
                                    ? "1px solid rgba(251,191,36,0.35)"
                                    : "1px solid rgba(139,92,246,0.35)",
                            }}
                        >
                            第 {currentRound} 轮 · {adaptiveDirection === "easier" ? "难度已下调" : "难度已上调"}
                        </span>
                    )}
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
                    {/* 自适应出题：生成中 / 失败提示 */}
                    {adaptiveState === "generating" && (
                        <div
                            style={{
                                marginBottom: "20px",
                                padding: "16px 20px",
                                borderRadius: "12px",
                                background: "rgba(139,92,246,0.08)",
                                border: "1px solid rgba(139,92,246,0.3)",
                                display: "flex",
                                alignItems: "center",
                                gap: "14px",
                                fontSize: "14px",
                                color: "#c4b5fd",
                                lineHeight: 1.6,
                            }}
                        >
                            <span
                                className="fsm-spinner"
                                style={{
                                    width: "18px",
                                    height: "18px",
                                    borderRadius: "50%",
                                    border: "2px solid rgba(139,92,246,0.3)",
                                    borderTopColor: "#8b5cf6",
                                    display: "inline-block",
                                    animation: "spin 1s linear infinite",
                                    flexShrink: 0,
                                }}
                            />
                            <div>
                                <div style={{ fontWeight: "600" }}>
                                    🤖 AI 正在根据你的正确率自适应调整题目难度...
                                </div>
                                <div style={{ fontSize: "13px", color: "#8893b8" }}>
                                    {adaptiveDirection === "easier"
                                        ? "正在生成一组更基础、更简单的同类题目"
                                        : `正在「${userLevel}」级别上限内生成难度小幅上调的新题目`}
                                    （约需 1-3 分钟，可稍作等待）
                                </div>
                            </div>
                        </div>
                    )}
                    {adaptiveState === "error" && (
                        <div
                            style={{
                                marginBottom: "20px",
                                padding: "14px 20px",
                                borderRadius: "12px",
                                background: "rgba(239,68,68,0.08)",
                                border: "1px solid rgba(239,68,68,0.3)",
                                fontSize: "14px",
                                color: "#f87171",
                                lineHeight: 1.6,
                            }}
                        >
                            ⚠️ 自适应出题失败，可能是后端连接中断或超时。可在提交结果中重新点击按钮再试一次。
                        </div>
                    )}

                    <Quiz
                        key={adaptiveRound}
                        quiz={displayQuiz}
                        taskId={taskId}
                        sessionId={sessionId}
                        onClose={onClose}
                        onRegenerate={onRegenerate}
                        regenerating={adaptiveState === "generating"}
                        userLevel={userLevel}
                        round={currentRound}
                        onFollowupClick={onFollowupClick}
                    />

                    {/* 反馈：紧挨在测试题下方 */}
                    <div style={{ marginTop: "20px" }}>
                        <Feedback
                            taskId={taskId}
                            sessionId={sessionId}
                            agentId={feedbackAgentId}
                            functionTag={feedbackFunctionTag}
                        />
                    </div>
                </div>
            </div>
        </div>
    );
}

export default QuizPage;
