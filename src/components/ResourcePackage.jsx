import React from "react";
import { BookOpen, FileText, ClipboardList } from "lucide-react";

/**
 * 将任意类型的资源内容转为可渲染的字符串
 * 兼容：字符串 / 对象（含 content_markdown 或 steps_markdown 或 title）/ undefined / null
 */
function formatResource(value) {
    if (value === null || value === undefined) return null;
    if (typeof value === "string") return value;
    if (typeof value === "object") {
        if (value.steps_markdown) return value.steps_markdown;
        if (value.content_markdown) return value.content_markdown;
        if (value.title) return value.title;
        if (value.goal) return value.goal;
        return null;
    }
    return String(value);
}

/**
 * 简易 markdown 渲染：把 content_markdown 拆成段落、标题、列表、代码块等
 * 不用引入 markdown 库，轻量处理常见格式
 */
function renderMarkdown(text) {
    if (!text) return null;
    const lines = text.split("\n");
    const elements = [];
    let keyIndex = 0;

    for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        const trimmed = line.trim();

        if (trimmed === "") continue;

        // 标题：## 或 ###
        if (trimmed.startsWith("### ")) {
            elements.push(
                <h4
                    key={keyIndex++}
                    style={{
                        color: "#c8d0ff",
                        fontSize: "15px",
                        margin: "14px 0 8px",
                        fontWeight: 600,
                        borderBottom: "1px solid rgba(139,92,246,0.2)",
                        paddingBottom: "4px"
                    }}
                >
                    {trimmed.replace(/^###\s*/, "")}
                </h4>
            );
            continue;
        }
        if (trimmed.startsWith("## ")) {
            elements.push(
                <h3
                    key={keyIndex++}
                    style={{
                        color: "#e0e0ff",
                        fontSize: "17px",
                        margin: "18px 0 10px",
                        fontWeight: 700
                    }}
                >
                    {trimmed.replace(/^##\s*/, "")}
                </h3>
            );
            continue;
        }

        // 代码块：```
        if (trimmed.startsWith("```")) {
            const lang = trimmed.replace(/^```/, "").trim();
            let codeLines = [];
            i++;
            while (i < lines.length && !lines[i].trim().startsWith("```")) {
                codeLines.push(lines[i]);
                i++;
            }
            elements.push(
                <div
                    key={keyIndex++}
                    style={{
                        background: "rgba(0,0,0,0.3)",
                        border: "1px solid rgba(139,92,246,0.2)",
                        borderRadius: "8px",
                        padding: "10px 14px",
                        margin: "8px 0",
                        fontSize: "13px",
                        fontFamily: "monospace",
                        color: "#a78bfa",
                        overflowX: "auto",
                        whiteSpace: "pre"
                    }}
                >
                    {lang && <div style={{ fontSize: "11px", color: "#666", marginBottom: "4px" }}>{lang}</div>}
                    {codeLines.join("\n")}
                </div>
            );
            continue;
        }

        // 列表项：- 或 * 或 1.
        if (trimmed.startsWith("- ") || trimmed.startsWith("* ") || /^\d+\.\s/.test(trimmed)) {
            elements.push(
                <li
                    key={keyIndex++}
                    style={{
                        color: "#b8c4ff",
                        fontSize: "14px",
                        lineHeight: 1.7,
                        margin: "4px 0 4px 20px",
                        listStyleType: trimmed.startsWith("* ") || trimmed.startsWith("- ") ? "disc" : "decimal"
                    }}
                >
                    {trimmed.replace(/^[-*\d.]+\s*/, "")}
                </li>
            );
            continue;
        }

        // 普通段落（加粗、斜体、行内代码）
        let content = trimmed;
        // 行内代码 `xxx`
        content = content.replace(/`([^`]+)`/g, '<span style="background:rgba(139,92,246,0.15);color:#a78bfa;padding:2px 6px;border-radius:4px;font-family:monospace;font-size:13px">$1</span>');
        // 加粗 **xxx**
        content = content.replace(/\*\*([^*]+)\*\*/g, '<strong style="color:#e0e0ff">$1</strong>');
        // 斜体 *xxx*
        content = content.replace(/\*([^*]+)\*/g, '<em style="color:#c8d0ff">$1</em>');

        elements.push(
            <p
                key={keyIndex++}
                style={{
                    color: "#b8c4ff",
                    fontSize: "14px",
                    lineHeight: 1.7,
                    margin: "6px 0"
                }}
                dangerouslySetInnerHTML={{ __html: content }}
            />
        );
    }

    return elements;
}

function ResourcePackage({ resources }) {
    let lectureContent, guideContent, quizCount;

    if (resources && resources.content_markdown) {
        lectureContent = resources.content_markdown;
        guideContent = null;
        quizCount = null;
    } else {
        lectureContent = formatResource(resources?.lecture);
        guideContent = formatResource(resources?.practice_guide || resources?.guide);
        const rawQuiz = resources?.quiz;
        if (Array.isArray(rawQuiz)) {
            quizCount = rawQuiz.length;
        } else if (rawQuiz && typeof rawQuiz === "object" && Array.isArray(rawQuiz.questions)) {
            quizCount = rawQuiz.questions.length;
        } else {
            quizCount = null;
        }
    }

    if (!lectureContent && !guideContent && quizCount === null) {
        return null;
    }

    return (
        <div className="info-card">
            <div className="card-title">
                <BookOpen size={24} />
                <h2>个性化学习资源</h2>
            </div>

            <div className="resource-card">
                <FileText size={20} />
                <div style={{ flex: 1 }}>
                    <h3>学习讲义</h3>
                    {lectureContent
                        ? <div style={{ marginTop: "8px" }}>{renderMarkdown(lectureContent)}</div>
                        : <p style={{ color: "#888", fontSize: "14px" }}>暂无讲义</p>
                    }
                </div>
            </div>

            <div className="resource-card">
                <BookOpen size={20} />
                <div style={{ flex: 1 }}>
                    <h3>实操指南</h3>
                    {guideContent
                        ? <div style={{ marginTop: "8px" }}>{renderMarkdown(guideContent)}</div>
                        : <p style={{ color: "#888", fontSize: "14px" }}>暂无指南</p>
                    }
                </div>
            </div>

            <div className="resource-card">
                <ClipboardList size={20} />
                <div>
                    <h3>测试题</h3>
                    <p>
                        {quizCount !== null && quizCount > 0
                            ? `共${quizCount}道测试题`
                            : "暂无测试题"}
                    </p>
                </div>
            </div>
        </div>
    );
}

export default ResourcePackage;
