import React, { useState, useMemo, useEffect, useRef } from "react";
import { submitQuiz } from "../api/api";
import { flushSync } from "react-dom";


/**
 * 把后端返回的 quiz 字段（可能是数组、对象、null、字符串）统一规整成题目数组
 */
function normalizeQuiz(rawQuiz) {
    if (rawQuiz == null) return [];

    if (typeof rawQuiz === "string") {
        try {
            return normalizeQuiz(JSON.parse(rawQuiz));
        } catch (e) {
            return [];
        }
    }

    if (Array.isArray(rawQuiz)) {
        return rawQuiz.filter(
            (q) => q && typeof q === "object" && (q.question || q.title || q.q)
        );
    }

    if (typeof rawQuiz === "object") {
        if (rawQuiz.question || rawQuiz.title || rawQuiz.q) {
            return [rawQuiz];
        }

        const nestedKeys = [
            "questions",
            "items",
            "quiz_items",
            "data",
            "list",
            "result",
        ];
        for (const key of nestedKeys) {
            if (Array.isArray(rawQuiz[key])) {
                return normalizeQuiz(rawQuiz[key]);
            }
            if (rawQuiz[key] && typeof rawQuiz[key] === "object") {
                const inner = normalizeQuiz(rawQuiz[key]);
                if (inner.length > 0) return inner;
            }
        }

        const merged = [];
        Object.values(rawQuiz).forEach((v) => {
            if (Array.isArray(v)) {
                v.forEach((item) => {
                    if (
                        item &&
                        typeof item === "object" &&
                        (item.question || item.title || item.q)
                    ) {
                        merged.push(item);
                    }
                });
            }
        });
        return merged;
    }

    return [];
}


/**
 * 判断题关键词
 */
const JUDGE_POSITIVE = new Set(["正确", "对", "是", "true", "yes", "√", "✓"]);
const JUDGE_NEGATIVE = new Set(["错误", "错", "否", "false", "no", "×", "✗"]);

/**
 * 检测题型：choice（选择题）| judge（判断题）| fill（填空题）
 * 策略（优先级从高到低）：
 *   0. 后端自带中文 type 字段（"判断"/"选择"/"简答"/"填空"等）→ 直接映射（最可靠）
 *   1. 没选项 → fill
 *   2. 刚好 2 个选项且内容匹配判断题关键词 → judge
 *   3. 选项全带 A/B/C/D 前缀且 ≥3 个 → choice
 *   4. 其余有选项的 → choice（兜底）
 */
function detectQuestionType(options, questionText, rawType) {
    // 后端自带中文题型时直接映射
    const t = String(rawType ?? "").trim();
    if (t.includes("判断") || /^(judge|true|false|boolean)$/i.test(t)) return "judge";
    if (t.includes("选择") || t.includes("单选") || t.includes("多选") || /^choice/i.test(t)) return "choice";
    if (t.includes("简答") || t.includes("填空") || t.includes("问答") || /^(fill|short|essay|answer)/i.test(t)) return "fill";
    // 其他未知题型：有选项按选择题，没选项按填空题（保证一定有作答框）
    if (t) return Array.isArray(options) && options.length > 0 ? "choice" : "fill";

    if (!Array.isArray(options) || options.length === 0) return "fill";

    const opts = options.map((o) => String(o ?? "").trim());

    // 判断题检测：刚好 2 个选项，内容是一正一反
    if (opts.length === 2) {
        const normalizedOpts = opts.map((o) => {
            // 去掉 A. / B. / A) / B) 等前缀
            const stripped = o.replace(/^[A-D][.\s)]\s*/i, "").trim();
            return stripped;
        });
        const hasPositive =
            normalizedOpts.some((o) => JUDGE_POSITIVE.has(o)) ||
            normalizedOpts.some((o) =>
                Array.from(JUDGE_POSITIVE).some((k) => o.includes(k))
            );
        const hasNegative =
            normalizedOpts.some((o) => JUDGE_NEGATIVE.has(o)) ||
            normalizedOpts.some((o) =>
                Array.from(JUDGE_NEGATIVE).some((k) => o.includes(k))
            );
        if (hasPositive && hasNegative) return "judge";
    }

    // 问题文字也包含判断题特征（弱信号辅助）
    if (questionText && /(判断|是否正确|是否属于|True.or.False|对错)/i.test(questionText)) {
        return "judge";
    }

    // 选择题
    return "choice";
}

/**
 * 提取单道题的标准字段，兼容多种命名
 */
function extractQuestion(item, index) {
    const question =
        item.question || item.title || item.q || `题目 ${index + 1}`;

    let options = Array.isArray(item.options)
        ? item.options
        : Array.isArray(item.choices)
            ? item.choices
            : Array.isArray(item.options_list)
                ? item.options_list
                : [];

    // options 是字符串时的兜底：尝试 JSON 解析，失败则按行拆分
    if (typeof options === "string" || typeof item.options === "string") {
        const raw = typeof item.options === "string" ? item.options : "";
        try {
            const parsed = JSON.parse(raw);
            options = Array.isArray(parsed) ? parsed : [];
        } catch (e) {
            options = raw
                .split(/\r?\n|(?=[A-D][.、)])/)
                .map((s) => s.trim())
                .filter(Boolean);
        }
    }

    const answer =
        item.answer !== undefined
            ? item.answer
            : item.correct_answer !== undefined
                ? item.correct_answer
                : item.correct !== undefined
                    ? item.correct
                    : "";

    // 解析字段：explanation / analysis / 解析（后端实测返回 explanation）
    const explanation =
        item.explanation !== undefined && item.explanation !== ""
            ? item.explanation
            : item.analysis !== undefined && item.analysis !== ""
                ? item.analysis
                : item.解析 !== undefined && item.解析 !== ""
                    ? item.解析
                    : "";

    let type = detectQuestionType(options, question, item.type);

    // 防御：无论检测出什么题型，只要没有有效选项就强制变成填空题，
    // 保证每道题一定有作答框（此前 choice/judge 题在 options 为空时什么都不渲染）
    const hasOptions =
        Array.isArray(options) &&
        options.some((o) => String(o ?? "").trim().length > 0);
    if (!hasOptions) type = "fill";

    return { question, options, answer, type, explanation };
}

/**
 * 判断用户答案是否匹配正确答案
 * 兼容三种格式：
 *   "B"          vs "B"           → 直接匹配
 *   "B. 机器学习" vs "B"           → 前缀匹配（选项带 "B. " 前缀，answer 只给字母）
 *   "B. 机器学习" vs "B. 机器学习" → 直接匹配（全文本）
 */
function answerMatches(userAnswer, correctAnswer) {
    const ua = String(userAnswer ?? "").trim();
    const ca = String(correctAnswer ?? "").trim();
    if (!ua || !ca) return false;
    if (ua === ca) return true;
    // 选项带字母前缀（如 "B. xxx" / "B) xxx" / "B  xxx"），answer 是单字母
    if (/^[A-D][.\s)]/.test(ua) && ca.length === 1 && ua[0].toUpperCase() === ca.toUpperCase()) {
        return true;
    }
    return false;
}

/**
 * 提取解析文本的第一句话（用于正确率 ≥85% 时的"一句话解析"）
 */
function firstSentence(text) {
    const t = String(text ?? "").trim();
    if (!t) return "";
    // 按中文/英文句末标点切分，取第一句；无标点时整体截断
    const m = t.match(/^.*?[。！？!?；;]/);
    if (m && m[0].trim()) return m[0].trim();
    return t.length > 60 ? t.substring(0, 60) + "..." : t;
}


function Quiz({ quiz = [], taskId, sessionId, onClose, onRegenerate, regenerating = false, userLevel = "入门", round = 1, onFollowupClick }) {
    const [answers, setAnswers] = useState({});
    const [submitted, setSubmitted] = useState(false);
    const [results, setResults] = useState(null);
    const [isSubmitting, setIsSubmitting] = useState(false);
    const resultsRef = useRef(null);

    const normalizedQuiz = useMemo(() => {
        const list = normalizeQuiz(quiz);
        return list.map((item, idx) => extractQuestion(item, idx));
    }, [quiz]);

    // 提交后自动滚动到结果区域
    useEffect(() => {
        if (submitted && resultsRef.current) {
            resultsRef.current.scrollIntoView({ behavior: "smooth", block: "start" });
        }
    }, [submitted, results]);

    if (normalizedQuiz.length === 0) {
        return (
            <div
                style={{
                    padding: "24px",
                    borderRadius: "12px",
                    background: "rgba(251,191,36,0.06)",
                    border: "1px solid rgba(251,191,36,0.25)",
                    color: "#e2d9a8",
                    fontSize: "14px",
                    lineHeight: "1.6",
                }}
            >
                ⚠️ 未识别到测试题数据。可能是后端本次未生成测试题，或题目数据结构与预期不符。
                请尝试重新点击「生成测试题」，若仍出现此提示请截图反馈。
            </div>
        );
    }

    const handleChange = (index, value) => {
        if (submitted) return;
        setAnswers({ ...answers, [index]: value });
    };

    const handleSubmit = async () => {
        console.log("[Quiz] handleSubmit 开始, answers:", answers, "normalizedQuiz长度:", normalizedQuiz.length);
        if (isSubmitting) {
            console.log("[Quiz] 正在提交中，忽略重复点击");
            return;
        }
        setIsSubmitting(true);

        // 前端自己算正确率（不依赖后端）
        let correctCount = 0;
        const details = normalizedQuiz.map((item, index) => {
            const userAnswer = answers[index] || "（未作答）";
            const correctAnswer = String(item.answer ?? "");
            const isCorrect = answerMatches(userAnswer, correctAnswer);
            if (isCorrect) correctCount++;
            return { question: item.question, userAnswer, correctAnswer, isCorrect };
        });
        const totalCount = normalizedQuiz.length;
        const accuracy =
            totalCount > 0
                ? ((correctCount / totalCount) * 100).toFixed(1)
                : "0";

        // 关键修复：使用 flushSync 强制立即更新 UI，防止 async 批处理延迟
        flushSync(() => {
            setResults({ correctCount, totalCount, accuracy, details, systemJudgment: "" });
            setSubmitted(true);
        });
        console.log("[Quiz] 本地结果已强制 flush, submitted=true, accuracy=" + accuracy);

        // 按后端契约格式提交：{ question_index, selected_option }
        try {
            const answerPayload = normalizedQuiz.map((item, index) => {
                const userAnswer = answers[index] || "";
                // 选项题：找到用户选中项在选项数组中的下标，映射为 A/B/C/D
                const optionIndex =
                    item.options.length > 0
                        ? item.options.findIndex((opt) => opt === userAnswer)
                        : -1;
                return {
                    question_index: index,
                    selected_option:
                        optionIndex >= 0
                            ? String.fromCharCode(65 + optionIndex) // 0→A, 1→B, ...
                            : userAnswer, // 填空题或匹配不到时用原始文本
                };
            });

            console.log("[Quiz] 向后端提交:", { task_id: taskId, session_id: sessionId, answers: answerPayload });
            const response = await submitQuiz({
                task_id: taskId,
                session_id: sessionId,
                answers: answerPayload,
            });
            console.log("[Quiz] 后端返回:", response);

            // 解析后端返回的系统判定
            const judgment =
                response?.judgment ||
                response?.system_verdict ||
                response?.difficulty_assessment ||
                (response?.message ? response.message : "");

            // 启发式追问（REDIMENSION/ADVANCE 后的收尾引导问题，不计分）
            const followupQuestions =
                Array.isArray(response?.followup_questions) && response.followup_questions.length > 0
                    ? response.followup_questions
                    : [];

            // 如果后端返回了正确率，以后端为准
            const backendAccuracy =
                response?.accuracy != null
                    ? (response.accuracy * 100).toFixed(1)
                    : accuracy;

            setResults((prev) => ({
                ...prev,
                accuracy: backendAccuracy,
                systemJudgment: judgment,
                followupQuestions,
            }));
            console.log("[Quiz] 后端判定已合并到 results, followupQuestions:", followupQuestions);
        } catch (e) {
            console.warn("后端测试提交失败（不影响本地结果展示）", e);
        } finally {
            setIsSubmitting(false);
            console.log("[Quiz] 提交流程结束, isSubmitting=false");
        }
    };

    const handleReset = () => {
        setAnswers({});
        setSubmitted(false);
        setResults(null);
    };

    const answeredCount = Object.keys(answers).filter((k) => answers[k]).length;
    const allAnswered = answeredCount >= normalizedQuiz.length;

    return (
        <div className="info-card">
            <div className="card-title">
                <h2>📝 学习效果测试</h2>
            </div>

            {/* 调试：显示当前状态 */}
            {normalizedQuiz.map((item, index) => {
                const userAnswer = answers[index];
                const detail = results?.details?.[index];
                const isCorrect = detail?.isCorrect;

                return (
                    <div
                        key={index}
                        style={{
                            marginBottom: "20px",
                            padding: "16px",
                            borderRadius: "12px",
                            background: submitted
                                ? isCorrect
                                    ? "rgba(34,197,94,0.06)"
                                    : "rgba(239,68,68,0.06)"
                                : "rgba(255,255,255,0.03)",
                            border: submitted
                                ? isCorrect
                                    ? "1px solid rgba(34,197,94,0.25)"
                                    : "1px solid rgba(239,68,68,0.25)"
                                : "1px solid rgba(255,255,255,0.08)",
                        }}
                    >
                        <p
                            style={{
                                fontSize: "15px",
                                marginBottom: "12px",
                                color: "#e0e0ff",
                                fontWeight: "500",
                            }}
                        >
                            {index + 1}. {item.question}
                        </p>

                        {/* 判断题：两个大按钮 */}
                        {item.type === "judge" && (
                            <div style={{ display: "flex", gap: "12px" }}>
                                {item.options.map((option, i) => {
                                    const isSelected = userAnswer === option;
                                    // 判断题正确答案判断（用 answerMatches 兜底）
                                    const isCorrectAnswer =
                                        submitted &&
                                        answerMatches(option, item.answer);
                                    return (
                                        <button
                                            key={i}
                                            onClick={() =>
                                                !submitted &&
                                                handleChange(index, option)
                                            }
                                            disabled={submitted}
                                            style={{
                                                flex: 1,
                                                padding: "14px 10px",
                                                borderRadius: "10px",
                                                border: submitted
                                                    ? isCorrectAnswer
                                                        ? "2px solid rgba(34,197,94,0.6)"
                                                        : isSelected
                                                            ? "2px solid rgba(239,68,68,0.6)"
                                                            : "1px solid rgba(255,255,255,0.08)"
                                                    : isSelected
                                                        ? "2px solid rgba(139,92,246,0.6)"
                                                        : "2px solid rgba(255,255,255,0.12)",
                                                background: submitted
                                                    ? isCorrectAnswer
                                                        ? "rgba(34,197,94,0.12)"
                                                        : isSelected
                                                            ? "rgba(239,68,68,0.12)"
                                                            : "transparent"
                                                    : isSelected
                                                        ? "rgba(139,92,246,0.12)"
                                                        : "transparent",
                                                color: submitted
                                                    ? isCorrectAnswer
                                                        ? "#4ade80"
                                                        : isSelected
                                                            ? "#f87171"
                                                            : "#666"
                                                    : isSelected
                                                        ? "#c4b5fd"
                                                        : "#8893b8",
                                                fontSize: "15px",
                                                fontWeight: isSelected ? "600" : "400",
                                                cursor: submitted
                                                    ? "default"
                                                    : "pointer",
                                                transition: "all 0.2s",
                                            }}
                                        >
                                            {String(option ?? "").replace(/^[A-D][.\s)]\s*/i, "")}
                                            {submitted && isCorrectAnswer && " ✓"}
                                            {submitted && isSelected && !isCorrectAnswer && " ✗"}
                                        </button>
                                    );
                                })}
                            </div>
                        )}

                        {/* 选择题：radio 列表 */}
                        {item.type === "choice" && item.options.length > 0 && (
                            <div>
                                {item.options.map((option, i) => {
                                    const isSelected = userAnswer === option;
                                    const isCorrectOption =
                                        submitted &&
                                        answerMatches(option, item.answer);

                                    return (
                                        <label
                                            key={i}
                                            style={{
                                                display: "flex",
                                                alignItems: "center",
                                                gap: "8px",
                                                padding: "10px 14px",
                                                marginBottom: "6px",
                                                borderRadius: "8px",
                                                cursor: submitted
                                                    ? "default"
                                                    : "pointer",
                                                background: submitted
                                                    ? isCorrectOption
                                                        ? "rgba(34,197,94,0.12)"
                                                        : isSelected
                                                            ? "rgba(239,68,68,0.12)"
                                                            : "transparent"
                                                    : isSelected
                                                        ? "rgba(139,92,246,0.12)"
                                                        : "transparent",
                                                border: submitted
                                                    ? isCorrectOption
                                                        ? "1px solid rgba(34,197,94,0.4)"
                                                        : isSelected
                                                            ? "1px solid rgba(239,68,68,0.4)"
                                                            : "1px solid transparent"
                                                    : isSelected
                                                        ? "1px solid rgba(139,92,246,0.4)"
                                                        : "1px solid transparent",
                                                transition: "all 0.2s",
                                                color: submitted
                                                    ? isCorrectOption
                                                        ? "#4ade80"
                                                        : isSelected
                                                            ? "#f87171"
                                                            : "#8893b8"
                                                    : "#c8d0ff",
                                                fontSize: "14px",
                                            }}
                                        >
                                            <input
                                                type="radio"
                                                name={`q${index}`}
                                                value={option}
                                                checked={isSelected || false}
                                                onChange={(e) =>
                                                    handleChange(
                                                        index,
                                                        e.target.value
                                                    )
                                                }
                                                disabled={submitted}
                                                style={{
                                                    cursor: submitted
                                                        ? "default"
                                                        : "pointer",
                                                    accentColor: "#8b5cf6",
                                                }}
                                            />
                                            <span>{option}</span>
                                            {submitted && isCorrectOption && (
                                                <span
                                                    style={{
                                                        marginLeft: "auto",
                                                        color: "#4ade80",
                                                        fontSize: "12px",
                                                        fontWeight: "600",
                                                    }}
                                                >
                                                    ✓ 正确答案
                                                </span>
                                            )}
                                            {submitted &&
                                                isSelected &&
                                                !isCorrectOption && (
                                                    <span
                                                        style={{
                                                            marginLeft: "auto",
                                                            color: "#f87171",
                                                            fontSize: "12px",
                                                            fontWeight: "600",
                                                        }}
                                                    >
                                                        ✗ 你的选择
                                                    </span>
                                                )}
                                        </label>
                                    );
                                })}
                            </div>
                        )}

                        {/* 填空题：文本输入 */}
                        {item.type === "fill" && (
                            <div>
                                <input
                                    className="answer-input"
                                    placeholder="请输入答案"
                                    value={userAnswer || ""}
                                    onChange={(e) =>
                                        handleChange(index, e.target.value)
                                    }
                                    disabled={submitted}
                                    style={{
                                        width: "100%",
                                        padding: "10px 14px",
                                        borderRadius: "8px",
                                        border: submitted
                                            ? isCorrect
                                                ? "1px solid rgba(34,197,94,0.4)"
                                                : "1px solid rgba(239,68,68,0.4)"
                                            : "1px solid rgba(255,255,255,0.15)",
                                        background: "rgba(255,255,255,0.05)",
                                        color: "#e0e0ff",
                                        fontSize: "14px",
                                        outline: "none",
                                    }}
                                />
                                {submitted && (
                                    <div
                                        style={{
                                            marginTop: "8px",
                                            fontSize: "13px",
                                        }}
                                    >
                                        <span
                                            style={{
                                                color: isCorrect
                                                    ? "#4ade80"
                                                    : "#f87171",
                                                fontWeight: "600",
                                            }}
                                        >
                                            {isCorrect
                                                ? "✓ 回答正确"
                                                : "✗ 回答错误"}
                                        </span>
                                        {!isCorrect && (
                                            <span
                                                style={{
                                                    color: "#b8c4ff",
                                                    marginLeft: "12px",
                                                }}
                                            >
                                                正确答案：{item.answer}
                                            </span>
                                        )}
                                    </div>
                                )}
                            </div>
                        )}

                        {/* 提交后，非填空题答错时显示正确答案 */}
                        {submitted &&
                            item.type !== "fill" &&
                            !isCorrect &&
                            item.answer && (
                                <div
                                    style={{
                                        marginTop: "8px",
                                        fontSize: "13px",
                                        color: "#4ade80",
                                        fontWeight: "500",
                                    }}
                                >
                                    正确答案：{item.answer}
                                </div>
                            )}

                        {/* 提交后解析：正确率<85%显示完整解析，≥85%只显示一句话解析 */}
                        {submitted && item.explanation && (
                            <div
                                style={{
                                    marginTop: "10px",
                                    padding: "10px 14px",
                                    borderRadius: "8px",
                                    background: "rgba(251,191,36,0.06)",
                                    border: "1px solid rgba(251,191,36,0.2)",
                                    fontSize: "13px",
                                    color: "#e2d9a8",
                                    lineHeight: "1.6",
                                }}
                            >
                                <span style={{ fontWeight: "600", color: "#fbbf24" }}>
                                    💡 解析：
                                </span>
                                {parseFloat(results?.accuracy) < 85
                                    ? item.explanation
                                    : firstSentence(item.explanation)}
                            </div>
                        )}
                    </div>
                );
            })}

            {/* 底部：结果展示 / 提交按钮 */}
            <div ref={resultsRef}>
            {submitted && results ? (
                <>
                    {/* 成功提示横幅 */}
                    <div
                        style={{
                            marginTop: "20px",
                            padding: "14px 20px",
                            borderRadius: "10px",
                            background:
                                parseFloat(results.accuracy) >= 85
                                    ? "rgba(34,197,94,0.1)"
                                    : "rgba(251,191,36,0.1)",
                            border:
                                parseFloat(results.accuracy) >= 85
                                    ? "1px solid rgba(34,197,94,0.35)"
                                    : "1px solid rgba(251,191,36,0.35)",
                            display: "flex",
                            alignItems: "center",
                            gap: "10px",
                            fontSize: "15px",
                            fontWeight: "500",
                            color:
                                parseFloat(results.accuracy) >= 85
                                    ? "#4ade80"
                                    : "#fbbf24",
                        }}
                    >
                        <span>{isSubmitting ? "⏳ 提交中..." : "✅ 测试提交成功！"} 正确率：{results.accuracy}%</span>
                    </div>

                    {/* 自适应难度调整卡片：正确率 <85% 建议降难度，≥85% 建议在当前级别上限内小幅升难度（对齐后端 0.85 单阈值：REDIMENSION / ADVANCE） */}
                    {onRegenerate &&
                        (parseFloat(results.accuracy) < 85 ? (
                        <div
                            style={{
                                marginTop: "10px",
                                padding: "16px 20px",
                                borderRadius: "10px",
                                background: "rgba(251,191,36,0.08)",
                                border: "1px solid rgba(251,191,36,0.3)",
                                display: "flex",
                                flexWrap: "wrap",
                                alignItems: "center",
                                justifyContent: "space-between",
                                gap: "12px",
                            }}
                        >
                            <div style={{ fontSize: "14px", color: "#e2d9a8", lineHeight: 1.6 }}>
                                <div style={{ fontWeight: "600", color: "#fbbf24", marginBottom: "4px" }}>
                                    📉 正确率低于 85%，触发自适应降档
                                </div>
                                系统将为你重新生成一组
                                <span style={{ color: "#fbbf24", fontWeight: "600" }}>更基础、更简单</span>
                                的同类题目，先夯实基础再进阶。
                            </div>
                            <button
                                className="start-button"
                                onClick={() => onRegenerate(parseFloat(results.accuracy))}
                                disabled={regenerating}
                                style={{
                                    opacity: regenerating ? 0.5 : 1,
                                    cursor: regenerating ? "not-allowed" : "pointer",
                                    whiteSpace: "nowrap",
                                }}
                            >
                                {regenerating ? "AI 出题中..." : "生成更简单的题目"}
                            </button>
                        </div>
                        ) : (
                        <div
                            style={{
                                marginTop: "10px",
                                padding: "16px 20px",
                                borderRadius: "10px",
                                background: "rgba(139,92,246,0.08)",
                                border: "1px solid rgba(139,92,246,0.3)",
                                display: "flex",
                                flexWrap: "wrap",
                                alignItems: "center",
                                justifyContent: "space-between",
                                gap: "12px",
                            }}
                        >
                            <div style={{ fontSize: "14px", color: "#c4b5fd", lineHeight: 1.6 }}>
                                <div style={{ fontWeight: "600", marginBottom: "4px" }}>
                                    📈 正确率达标，触发自适应升档
                                </div>
                                系统将在「{userLevel}」级别
                                <span style={{ fontWeight: "600" }}>上限之内</span>
                                为你生成难度小幅上调的新题目，稳步提升挑战。
                            </div>
                            <button
                                className="start-button"
                                onClick={() => onRegenerate(parseFloat(results.accuracy))}
                                disabled={regenerating}
                                style={{
                                    opacity: regenerating ? 0.5 : 1,
                                    cursor: regenerating ? "not-allowed" : "pointer",
                                    whiteSpace: "nowrap",
                                }}
                            >
                                {regenerating ? "AI 出题中..." : "挑战更高难度"}
                            </button>
                        </div>
                        ))}

                    {/* 系统判定 */}
                    {results.systemJudgment && (
                        <div
                            style={{
                                marginTop: "10px",
                                padding: "12px 20px",
                                borderRadius: "10px",
                                background: "rgba(139,92,246,0.08)",
                                border: "1px solid rgba(139,92,246,0.25)",
                                fontSize: "14px",
                                color: "#c4b5fd",
                            }}
                        >
                            系统判定：{results.systemJudgment}
                        </div>
                    )}

                    {/* 启发式追问：降维/进阶后的收尾引导问题（不计分） */}
                    {Array.isArray(results.followupQuestions) && results.followupQuestions.length > 0 && (
                        <div
                            style={{
                                marginTop: "16px",
                                padding: "16px 20px",
                                borderRadius: "12px",
                                background: "rgba(139,92,246,0.06)",
                                border: "1px solid rgba(139,92,246,0.25)",
                            }}
                        >
                            <div
                                style={{
                                    display: "flex",
                                    alignItems: "center",
                                    gap: "8px",
                                    fontSize: "14px",
                                    fontWeight: "600",
                                    color: "#c4b5fd",
                                    marginBottom: "10px",
                                }}
                            >
                                💡 系统想进一步问你：
                            </div>
                            <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                                {results.followupQuestions.map((q, i) => (
                                    <div
                                        key={i}
                                        style={{
                                            padding: "10px 14px",
                                            borderRadius: "8px",
                                            background: "rgba(255,255,255,0.04)",
                                            border: "1px solid rgba(255,255,255,0.08)",
                                            fontSize: "14px",
                                            color: "#c8d0ff",
                                            lineHeight: 1.6,
                                            cursor: "pointer",
                                            transition: "all 0.2s",
                                        }}
                                        onClick={() => {
                                            if (onFollowupClick) onFollowupClick(q);
                                        }}
                                        onMouseEnter={(e) => {
                                            e.currentTarget.style.background = "rgba(139,92,246,0.1)";
                                            e.currentTarget.style.borderColor = "rgba(139,92,246,0.3)";
                                        }}
                                        onMouseLeave={(e) => {
                                            e.currentTarget.style.background = "rgba(255,255,255,0.04)";
                                            e.currentTarget.style.borderColor = "rgba(255,255,255,0.08)";
                                        }}
                                    >
                                        <span style={{ color: "#8b5cf6", fontWeight: "600", marginRight: "6px" }}>
                                            {i + 1}.
                                        </span>
                                        {q}
                                    </div>
                                ))}
                            </div>
                            <div
                                style={{
                                    marginTop: "8px",
                                    fontSize: "12px",
                                    color: "#666",
                                }}
                            >
                                （引导式追问，不计分；点击问题可作为新提问开启下一轮学习）
                            </div>
                        </div>
                    )}

                    {/* 结果详情卡片 */}
                    <div
                        style={{
                            marginTop: "12px",
                            padding: "20px",
                            borderRadius: "14px",
                            background:
                                "linear-gradient(135deg, rgba(37,99,235,0.12), rgba(147,51,234,0.12))",
                            border: "1px solid rgba(139,92,246,0.3)",
                            textAlign: "center",
                        }}
                    >
                        <div
                            style={{
                                fontSize: "14px",
                                color: "#b8c4ff",
                            }}
                        >
                            答对 {results.correctCount} / {results.totalCount} 题
                        </div>
                        <button
                            className="start-button"
                            onClick={handleReset}
                            style={{ marginTop: "14px" }}
                        >
                            重新测试
                        </button>
                        {onClose && (
                            <button
                                className="start-button"
                                onClick={onClose}
                                style={{
                                    marginTop: "10px",
                                    background:
                                        "linear-gradient(135deg, rgba(239,68,68,0.6), rgba(139,92,246,0.6))",
                                }}
                            >
                                关闭测试
                            </button>
                        )}
                    </div>
                </>
            ) : (
                <button
                    className="start-button"
                    onClick={handleSubmit}
                    disabled={isSubmitting || !allAnswered}
                    style={{
                        opacity: allAnswered && !isSubmitting ? 1 : 0.5,
                        cursor: allAnswered && !isSubmitting ? "pointer" : "not-allowed",
                    }}
                >
                    {isSubmitting
                        ? "正在提交..."
                        : allAnswered
                            ? "提交测试"
                            : `请完成所有题目（${answeredCount}/${normalizedQuiz.length}）`}
                </button>
            )}
            </div>
        </div>
    );
}

export default Quiz;
