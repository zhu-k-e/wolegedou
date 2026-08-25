import React from "react";
import { MessageCircle, Copy, BookOpen, Lightbulb, Network } from "lucide-react";

function AnswerPanel({ answer }) {
    if (!answer) {
        return null;
    }

    // 兼容两种传值：直接是对象，或者对象包在某个字段里
    const lecture = answer.content_markdown ? answer : answer.lecture || {};

    const title = lecture.title || "AI 生成结果";
    const content = lecture.content_markdown || "";
    const difficulty = lecture.difficulty_note || "";
    const refs = Array.isArray(lecture.knowledge_refs_display)
        ? lecture.knowledge_refs_display
        : [];

    function copyAnswer() {
        navigator.clipboard.writeText(content);
        alert("内容已复制");
    }

    return (
        <div className="info-card">
            <div className="card-title">
                <MessageCircle size={24} />
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
            <div className="answer-box">
                {content}
            </div>

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
                            // 兼容两种格式：字符串 或 {source, verification_status} 对象
                            if (typeof ref === 'string') {
                                return <li key={idx}>{ref}</li>;
                            }
                            const source = ref?.source || ref?.content || JSON.stringify(ref);
                            const status = ref?.verification_status;
                            // 后端实际返回 "已验证" / "未验证"（中文）
                            const isVerified = status === 'verified' || status === '已验证';
                            return (
                                <li key={idx}>
                                    <span>{source}</span>
                                    {isVerified && (
                                        <span style={{ marginLeft: 8, color: '#10b981' }}>✓ 已核实</span>
                                    )}
                                </li>
                            );
                        })}
                    </ul>
                </div>
            )}

            <button
                className="small-button"
                onClick={copyAnswer}
            >
                <Copy size={16} />
                复制内容
            </button>

            <div className="disclaimer">
                ⚠️ 以上内容由 AI 生成，仅供学习参考，请结合专业资料进行判断。
            </div>
        </div>
    );
}

export default AnswerPanel;
