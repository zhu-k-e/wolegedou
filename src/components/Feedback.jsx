import React, { useState } from "react";
import { submitFeedback } from "../api/api";

function Feedback({ taskId, sessionId, agentId, functionTag }) {
    const [sendingType, setSendingType] = useState(null); // 正在提交的反馈类型
    const [result, setResult] = useState(null); // { type, success, message }

    async function send(type) {
        console.log("[Feedback] send 被调用, type:", type);
        console.log("[Feedback] props:", { taskId, sessionId, agentId, functionTag });

        // 前置检查：参数缺失时不发请求
        if (!agentId || !functionTag) {
            console.warn("[Feedback] agentId 或 functionTag 缺失, 跳过请求");
            setResult({
                type,
                success: false,
                message: `当前任务未返回 Agent 调度信息（${!agentId ? "agent_id" : "function_tag"} 缺失），反馈暂不可用`,
            });
            return;
        }

        setSendingType(type);
        setResult(null);

        try {
            const payload = {
                task_id: taskId,
                session_id: sessionId,
                agent_id: agentId,
                function_tag: functionTag,
                feedback_type: type,
                comment: "",
            };
            console.log("[Feedback] 发送 POST /api/feedback, payload:", payload);

            const res = await submitFeedback(payload);
            console.log("[Feedback] 后端响应:", res);

            // 后端返回 { success: true } 或其他格式
            if (res?.success || res?.status === "ok" || res?.message) {
                setResult({ type, success: true, message: res?.message || "感谢反馈，系统已优化 Agent 能力" });
            } else {
                setResult({ type, success: true, message: "感谢反馈，系统已优化 Agent 能力" });
            }
        } catch (err) {
            console.error("[Feedback] 提交失败:", err);
            const status = err?.response?.status;
            let msg = "提交失败";
            if (status === 404) msg = "后端暂无 /api/feedback 接口";
            else if (status === 422) msg = "参数格式错误（agent_id 或 function_tag 缺失）";
            else if (status >= 500) msg = "后端服务异常";
            else if (err?.code === "ECONNABORTED") msg = "请求超时";
            else if (err?.message) msg = err.message;
            setResult({ type, success: false, message: msg });
        } finally {
            setSendingType(null);
        }
    }

    const buttons = [
        { type: "helpful", icon: "👍", label: "内容有帮助" },
        { type: "content_error", icon: "⚠️", label: "内容错误" },
        { type: "difficulty_mismatch", icon: "📖", label: "难度不匹配" },
    ];

    return (
        <div className="info-card">
            <h2>💬 学习反馈</h2>
            <p>你的反馈将帮助系统优化智能体能力。</p>

            <div className="feedback-buttons">
                {buttons.map((btn) => {
                    const disabled = sendingType !== null || !agentId || !functionTag;
                    return (
                        <button
                            key={btn.type}
                            onClick={() => send(btn.type)}
                            disabled={disabled}
                            style={{
                                opacity: disabled ? 0.5 : 1,
                                cursor: disabled ? "not-allowed" : "pointer",
                            }}
                        >
                            {sendingType === btn.type ? "提交中..." : `${btn.icon} ${btn.label}`}
                        </button>
                    );
                })}
            </div>

            {/* 提交结果提示 */}
            {result && (
                <div
                    style={{
                        marginTop: "14px",
                        padding: "12px 18px",
                        borderRadius: "10px",
                        background: result.success
                            ? "rgba(34,197,94,0.1)"
                            : "rgba(239,68,68,0.1)",
                        border: result.success
                            ? "1px solid rgba(34,197,94,0.35)"
                            : "1px solid rgba(239,68,68,0.35)",
                        fontSize: "14px",
                        color: result.success ? "#4ade80" : "#f87171",
                        display: "flex",
                        alignItems: "center",
                        gap: "8px",
                    }}
                >
                    {result.success ? "✅" : "❌"} {result.message}
                </div>
            )}
        </div>
    );
}

export default Feedback;
