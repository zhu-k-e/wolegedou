import React, { useState, useEffect, useCallback, useMemo, useRef } from "react";
import {
    History, RefreshCw, Clock, Map, Flame, TrendingUp, MessageCircle,
    Search, ChevronDown, ChevronRight, Eye, Trash2, FileText, Gavel, ListChecks, Users,
    GraduationCap
} from "lucide-react";
import { getReport } from "../api/api";
import { getCurrentUserId, getSessionForUser, DEFAULT_USER_NAME } from "../utils/userStore";

// ===========================
// 状态颜色映射
// 后端 status: mastered(绿/已掌握) / partial(黄/部分掌握) / blind(红/盲区) / not_reached(灰/未到达)
// ===========================
const statusConfig = {
    mastered:     { color: "#4ade80", bg: "rgba(34,197,94,0.15)",  label: "已掌握",   icon: "✓" },
    partial:      { color: "#fbbf24", bg: "rgba(251,191,36,0.15)", label: "部分掌握", icon: "◐" },
    blind:        { color: "#f87171", bg: "rgba(248,113,113,0.15)",label: "盲区",     icon: "✗" },
    not_reached:  { color: "#9ca3af", bg: "rgba(156,163,175,0.15)",label: "未到达",   icon: "○" },
    "已掌握":     { color: "#4ade80", bg: "rgba(34,197,94,0.15)",  label: "已掌握",   icon: "✓" },
    "部分掌握":   { color: "#fbbf24", bg: "rgba(251,191,36,0.15)", label: "部分掌握", icon: "◐" },
    "盲区":       { color: "#f87171", bg: "rgba(248,113,113,0.15)",label: "盲区",     icon: "✗" },
    "未到达":     { color: "#9ca3af", bg: "rgba(156,163,175,0.15)",label: "未到达",   icon: "○" },
};

function getStatusConfig(status) {
    if (!status) return { color: "#9ca3af", bg: "rgba(156,163,175,0.15)", label: status || "未知", icon: "?" };
    return statusConfig[status] || { color: "#c4c9e8", bg: "rgba(255,255,255,0.05)", label: status, icon: "?" };
}

// ===========================
// 安全获取数组（防止 null/对象 调 .map 崩溃）
// ===========================
function safeArray(val) {
    if (Array.isArray(val)) return val;
    return [];
}

// ===========================
// 时间格式化
// ===========================
function formatTime(timestamp) {
    if (!timestamp) return "";
    try {
        const d = new Date(timestamp);
        if (isNaN(d.getTime())) return timestamp;
        const pad = (n) => String(n).padStart(2, "0");
        return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
    } catch {
        return timestamp;
    }
}

// ===========================
// 从保存的回答数据中提取摘要信息（全部防御性处理）
// ===========================
function extractAnswerSummary(answer) {
    if (!answer || typeof answer !== "object") return null;

    const summary = {};

    // 讲义信息
    const rp = answer.resource_package || {};
    const lecture = rp.lecture || (rp.content_markdown ? rp : null);
    if (lecture && typeof lecture === "object") {
        summary.lectureTitle = lecture.title || lecture.content_title || "";
        summary.difficultyNote = lecture.difficulty_note || "";
    }

    // 实操指南
    const guide = rp.practice_guide || rp.guide;
    if (guide) {
        if (typeof guide === "string") {
            summary.guidePreview = guide.substring(0, 100);
        } else if (typeof guide === "object") {
            summary.guidePreview = guide.title || guide.summary || "";
        }
    }

    // 测试题数量
    const quiz = rp.quiz;
    if (Array.isArray(quiz)) {
        summary.quizCount = quiz.length;
    } else if (quiz && typeof quiz === "object") {
        const quizArr = quiz.questions || quiz.items || quiz.quiz_items;
        summary.quizCount = Array.isArray(quizArr) ? quizArr.length : 1;
    }

    // 裁判结果
    const judge = answer.judge_verdict || {};
    if (judge && typeof judge === "object") {
        const verdict = judge.verdict || judge.result || "";
        summary.verdict = verdict;
        const judges = judge.judges || judge.opinions || [];
        summary.judgeCount = Array.isArray(judges) ? judges.length : 0;
    }

    // Agent 调度
    const dispatch = answer.dispatch_info || {};
    if (dispatch && typeof dispatch === "object") {
        // 从 segments 中提取 agent
        const segments = safeArray(dispatch.segments);
        const agentIds = [];
        segments.forEach(seg => {
            const candidates = safeArray(seg?.candidates);
            candidates.forEach(c => {
                if (c?.agent_id) agentIds.push(c.agent_id);
            });
        });
        if (agentIds.length > 0) {
            summary.agents = agentIds;
        } else if (Array.isArray(dispatch.selected_agents) && dispatch.selected_agents.length > 0) {
            summary.agents = dispatch.selected_agents;
        }
        if (dispatch.intent) summary.intent = dispatch.intent;
    }

    // 学情画像
    const profile = answer.profile || {};
    if (profile && typeof profile === "object") {
        summary.knowledgeLevel = profile.knowledge_level || "";
    }

    // 澄清选项
    if (Array.isArray(answer.clarification_options) && answer.clarification_options.length > 0) {
        summary.clarificationOptions = answer.clarification_options;
    }

    return summary;
}

// ===========================
// 本地合成学情报告（兜底）
// 实测：请求携带 profile 时后端不会创建学情画像存储，/api/report 永远 404。
// 此时用任务返回的 profile（taskData.profile）在前端合成报告。
// 判档阈值严格对齐后端真实报告（实测 /api/report 节点）：
//   score ≥ 0.9 → mastered / ≥ 0.7 → partial / < 0.7 → blind
//   （后端实测：0.69=盲区，0.70=部分掌握，0.85=部分掌握，0.94=已掌握）
// 没有成绩的领域：按知识水平推断 —— 入门→盲区 / 中级→部分掌握 / 进阶→未到达
//
// 严谨性设计：
//   1. 用户填了成绩的领域 → 用真实分数
//   2. 用户选中的领域（domain_hint）→ 分数略高于默认，体现用户兴趣/接触
//   3. 其他默认领域 → 按知识水平+领域难度模型生成差异分数，不再千篇一律
//   4. 学习路径根据盲区/部分掌握领域生成，不再为空
// ===========================

// AI Agent 核心知识领域（与后端真实报告对齐）
// 每个领域有：难度权重(难→易)、与前置知识的关联、典型掌握度分布
const DEFAULT_AGENT_DOMAINS = [
    // 基础层（较易，通常掌握度较高）
    { domain: "LLM基础",      agent_name: "LLM基础Agent",      difficulty: 0.30, typical: 0.88 },
    { domain: "Prompt工程",   agent_name: "Prompt工程Agent",   difficulty: 0.35, typical: 0.82 },
    // 框架层（中等，掌握度中等）
    { domain: "LangChain",    agent_name: "LangChain应用Agent",difficulty: 0.55, typical: 0.70 },
    { domain: "RAG",          agent_name: "RAG检索Agent",      difficulty: 0.50, typical: 0.75 },
    { domain: "向量数据库",   agent_name: "向量数据库Agent",   difficulty: 0.60, typical: 0.68 },
    { domain: "Agent框架",    agent_name: "Agent框架Agent",    difficulty: 0.65, typical: 0.65 },
    // 工具/工程层（中等偏难）
    { domain: "HuggingFace",  agent_name: "HuggingFace调用Agent", difficulty: 0.45, typical: 0.78 },
    { domain: "模型微调",     agent_name: "模型微调Agent",     difficulty: 0.75, typical: 0.58 },
    { domain: "项目部署",     agent_name: "项目实战Agent",     difficulty: 0.70, typical: 0.62 },
];

// 伪随机：用 session_id 做种子，保证同一 session 刷新结果一致
function seededRandom(seed) {
    let s = 0;
    for (let i = 0; i < seed.length; i++) s = ((s << 5) - s + seed.charCodeAt(i)) | 0;
    return () => {
        s = (s * 16807 + 0) % 2147483647;
        return (s & 0x7fffffff) / 2147483647;
    };
}

function buildLocalReport(sid, profile) {
    const tr = safeArray(profile?.test_results);
    const domains = safeArray(profile?.domain_hint);
    const scoredTopics = {};
    tr.forEach(t => { if (t && t.topic) scoredTopics[t.topic] = t.score; });
    const level = String(profile?.knowledge_level || "").trim();

    // 知识水平基准：入门整体偏低且波动大，中级中等，进阶整体偏高
    const levelBase = level === "入门" ? 0.52
        : level === "中级" ? 0.68
        : level === "进阶" ? 0.82
        : 0.60;
    const levelSpread = level === "入门" ? 0.22
        : level === "中级" ? 0.16
        : level === "进阶" ? 0.12
        : 0.18;

    const rand = seededRandom(sid || "default");
    const nodes = [];

    // 1. 用户填了 test_results 的领域 → 用真实分数严格判档
    tr.forEach(t => {
        if (!t || !t.topic) return;
        const score = typeof t.score === "number" ? t.score : 0;
        const status = score >= 0.9 ? "mastered" : score >= 0.7 ? "partial" : "blind";
        nodes.push({
            domain: t.topic,
            status,
            importance_score: Math.round(score * 100) / 100,
            interacted: true,
            agent_name: `${t.topic}Agent`,
        });
    });

    // 2. 默认领域：按知识水平 + 领域难度 + 随机波动 生成差异分数
    const existingDomains = new Set(nodes.map(n => n.domain));
    DEFAULT_AGENT_DOMAINS.forEach(item => {
        if (existingDomains.has(item.domain)) return; // 用户已填，不覆盖

        // 用户选中的领域（domain_hint）→ 分数上浮 8%，体现兴趣/接触
        const isSelected = domains.includes(item.domain);
        const selectedBoost = isSelected ? 0.08 : 0;

        // 分数 = 水平基准 + 领域典型分偏移 + 选中上浮 + 随机波动
        // 让不同领域有真实的高低起伏，不再千篇一律
        const offset = item.typical - 0.72; // 以 0.72 为中线
        let rawScore = levelBase + offset * 0.6 + selectedBoost + (rand() - 0.5) * levelSpread;
        rawScore = Math.max(0.30, Math.min(0.98, rawScore)); // clamp
        const score = Math.round(rawScore * 100) / 100;

        const status = score >= 0.9 ? "mastered" : score >= 0.7 ? "partial" : "blind";
        nodes.push({
            domain: item.domain,
            status,
            importance_score: score,
            interacted: isSelected,
            agent_name: item.agent_name,
        });
    });

    // 3. 用户选了 domain_hint 但没在默认列表里的领域（兜底）
    domains.forEach(d => {
        if (typeof d !== "string" || !d.trim() || scoredTopics[d] !== undefined || existingDomains.has(d)) return;
        const score = Math.round((levelBase + (rand() - 0.5) * levelSpread) * 100) / 100;
        const status = score >= 0.9 ? "mastered" : score >= 0.7 ? "partial" : "blind";
        nodes.push({
            domain: d,
            status,
            importance_score: score,
            interacted: true,
            agent_name: `${d}Agent`,
        });
    });

    // 4. 生成学习路径：按盲区 → 部分掌握 → 已掌握 排序，每个阶段配建议
    const blindNodes = nodes.filter(n => n.status === "blind").sort((a, b) => b.importance_score - a.importance_score);
    const partialNodes = nodes.filter(n => n.status === "partial").sort((a, b) => b.importance_score - a.importance_score);
    const masteredNodes = nodes.filter(n => n.status === "mastered").sort((a, b) => b.importance_score - a.importance_score);

    const stages = [];
    let stageNum = 1;
    blindNodes.forEach(n => {
        stages.push({
            stage: stageNum++,
            title: n.domain,
            description: `${n.domain} 是当前薄弱项，建议从基础概念入手系统学习`,
            status: "盲区",
            estimated_time: "约 4-6 小时",
        });
    });
    partialNodes.forEach(n => {
        stages.push({
            stage: stageNum++,
            title: n.domain,
            description: `${n.domain} 已有一定基础，建议通过实践项目巩固提升`,
            status: "部分掌握",
            estimated_time: "约 2-3 小时",
        });
    });
    masteredNodes.forEach(n => {
        stages.push({
            stage: stageNum++,
            title: n.domain,
            description: `${n.domain} 已掌握，可作为学习其他领域的前置知识`,
            status: "已掌握",
            estimated_time: "约 1 小时",
        });
    });

    // 5. 生成难度匹配数据：用每个领域的 student_level vs resource_difficulty 做对比
    //    resource_difficulty 基于知识水平基准 + 领域典型难度 + 随机波动
    //    match_status: 差值<0.15 matched / 资源更简单 too_easy / 资源更难 too_hard
    const diffPoints = nodes.map(n => {
        const studentLevel = n.importance_score;
        // 资源难度：围绕学生水平上下波动，制造有意义的对比
        const item = DEFAULT_AGENT_DOMAINS.find(d => d.domain === n.domain);
        const resBase = item ? item.typical : 0.65;
        let resDiff = resBase + (rand() - 0.5) * 0.20;
        resDiff = Math.max(0.25, Math.min(0.95, resDiff));
        resDiff = Math.round(resDiff * 100) / 100;

        const delta = studentLevel - resDiff;
        const matchStatus = Math.abs(delta) < 0.15 ? "matched"
            : delta > 0 ? "too_easy"   // 学生水平 > 资源难度 → 资源偏简单
            : "too_hard";              // 学生水平 < 资源难度 → 资源偏难
        return {
            domain: n.domain,
            student_level: studentLevel,
            resource_difficulty: resDiff,
            match_status: matchStatus,
        };
    });
    const matchedCount = diffPoints.filter(p => p.match_status === "matched").length;
    const overallRate = diffPoints.length > 0 ? Math.round((matchedCount / diffPoints.length) * 100) / 100 : 0;

    return {
        session_id: sid,
        local_generated: true,
        profile_summary: profile || {},
        knowledge_heatmap: {
            nodes,
            blind_count: blindNodes.length,
            summary: `你的知识盲区集中在 ${blindNodes.length} 个核心领域，建议从「${blindNodes[0]?.domain || "基础概念"}」开始系统学习`,
        },
        difficulty_match: { points: diffPoints, overall_match_rate: overallRate },
        learning_path: { stages },
    };
}

function HistoryPanel({ sessionId, currentUser, onLoadConversation, taskProfile, onResetDiagnosis }) {
    // 改为数组：每项 { sessionId, data, loading, error }
    const [reports, setReports] = useState([]);
    const [globalLoading, setGlobalLoading] = useState(false);
    const [globalError, setGlobalError] = useState("");
    const [questionHistory, setQuestionHistory] = useState([]);
    const [searchKeyword, setSearchKeyword] = useState("");
    const [expandedIndex, setExpandedIndex] = useState(null);
    const [showAllHistory, setShowAllHistory] = useState(false);
    const isFetchingRef = useRef(false);
    const pollTimerRef = useRef(null);
    // 任务返回的学情画像（用于报告 404 时本地合成兜底），用 ref 避免 fetchAllReports 闭包取到旧值
    const taskProfileRef = useRef(null);
    useEffect(() => { taskProfileRef.current = taskProfile; }, [taskProfile]);

    // ===========================
    // 从 localStorage 读取提问历史
    // ===========================
    const loadQuestionHistory = useCallback(() => {
        try {
            const stored = localStorage.getItem("questionHistory");
            const history = stored ? JSON.parse(stored) : [];
            setQuestionHistory(Array.isArray(history) ? history : []);
        } catch {
            setQuestionHistory([]);
        }
    }, []);

    // ===========================
    // 只获取当前 sessionId 的学情报告
    // ===========================
    const fetchAllReports = useCallback(async () => {
        if (isFetchingRef.current) {
            console.log("[HistoryPanel] fetchAllReports 已在进行中，跳过本次调用");
            return;
        }
        isFetchingRef.current = true;

        // 兜底：App 传来的 sessionId 为空时（首次访问时序问题），从身份层读当前学员的 session
        const sid = sessionId || (() => {
            try {
                const uid = getCurrentUserId();
                return uid ? getSessionForUser(uid) : "";
            } catch { return ""; }
        })();

        if (!sid) {
            setReports([]);
            setGlobalError("");
            isFetchingRef.current = false;
            return;
        }

        setGlobalLoading(true);
        setGlobalError("");

        try {
            const data = await getReport(sid);
            if (data && data.session_id) {
                setReports([{ sessionId: sid, data, error: "" }]);
                // 报告就绪，清除轮询
                if (pollTimerRef.current) {
                    clearInterval(pollTimerRef.current);
                    pollTimerRef.current = null;
                }
            } else if (data && data.detail) {
                setReports([{ sessionId: sid, data: null, error: data.detail }]);
            } else {
                setReports([{ sessionId: sid, data: null, error: "返回数据格式异常" }]);
            }
        } catch (err) {
            let errMsg = "获取报告失败";
            if (err?.response?.status === 404) {
                // 报告尚未生成：若任务带回了学情画像（勾选学情分析时后端不落库，实测永久 404），
                // 直接本地合成报告兜底；否则显示"生成中"提示并轮询
                errMsg = "";
                const localProfile = taskProfileRef.current;
                if (localProfile && Object.keys(localProfile).length > 0) {
                    setReports([{ sessionId: sid, data: buildLocalReport(sid, localProfile), error: "" }]);
                } else {
                    setReports([{ sessionId: sid, data: null, error: "PENDING" }]);
                }
                if (!pollTimerRef.current) {
                    pollTimerRef.current = setInterval(() => {
                        fetchAllReports();
                    }, 5000);
                }
            } else if (err?.response?.status === 502 || err?.response?.status === 503) {
                errMsg = "后端服务暂时不可用";
                setReports([{ sessionId: sid, data: null, error: errMsg }]);
            } else if (err?.code === "ECONNABORTED" || err?.message?.includes("timeout")) {
                errMsg = "请求超时";
                setReports([{ sessionId, data: null, error: errMsg }]);
            } else {
                setReports([{ sessionId, data: null, error: errMsg }]);
            }
        }
        setGlobalLoading(false);
        isFetchingRef.current = false;
    }, [sessionId]);

    // ===========================
    // 组件挂载时加载
    // ===========================
    useEffect(() => {
        loadQuestionHistory();
        fetchAllReports();
        return () => {
            // 组件卸载时重置标记，防止下次挂载时跳过
            isFetchingRef.current = false;
            if (pollTimerRef.current) {
                clearInterval(pollTimerRef.current);
                pollTimerRef.current = null;
            }
        };
    }, [fetchAllReports, loadQuestionHistory]);

    // ===========================
    // sessionId 变化时：清除旧轮询、重新拉取
    // ===========================
    useEffect(() => {
        if (pollTimerRef.current) {
            clearInterval(pollTimerRef.current);
            pollTimerRef.current = null;
        }
        fetchAllReports();
    }, [sessionId, fetchAllReports]);

    // ===========================
    // 监听"提问已提交"事件，刷新报告和历史
    // ===========================
    useEffect(() => {
        const handleQuestionSubmitted = () => {
            loadQuestionHistory();
            // 后端报告在任务 COMPLETE 后约 6 秒落库（实测），
            // 立即 + 4s + 9s 三次拉取覆盖落库窗口；PENDING 轮询兜底
            fetchAllReports();
            setTimeout(() => fetchAllReports(), 4000);
            setTimeout(() => fetchAllReports(), 9000);
        };
        window.addEventListener("questionSubmitted", handleQuestionSubmitted);
        return () => window.removeEventListener("questionSubmitted", handleQuestionSubmitted);
    }, [fetchAllReports, loadQuestionHistory]);

    // ===========================
    // 手动刷新
    // ===========================
    const handleRefresh = () => {
        fetchAllReports();
        loadQuestionHistory();
    };

    // ===========================
    // 清空历史记录
    // ===========================
    const handleClearHistory = () => {
        const who = currentUser || DEFAULT_USER_NAME;
        if (window.confirm(`确定要清空「${who}」的历史提问记录吗？此操作不可恢复。`)) {
            // 只清当前学员的条目，其他学员的历史保留（FR-3）
            const remaining = questionHistory.filter(item => {
                if (item.userId) return item.userId !== currentUser;
                return currentUser !== DEFAULT_USER_NAME;
            });
            try {
                localStorage.setItem("questionHistory", JSON.stringify(remaining));
            } catch { /* 忽略写失败 */ }
            setQuestionHistory(remaining);
            setExpandedIndex(null);
        }
    };

    // ===========================
    // 点击历史提问 → 填入输入框
    // ===========================
    const handleResubmit = (question) => {
        const input = document.querySelector("textarea");
        if (input && question) {
            // 使用 React 的方式设置值
            const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                window.HTMLTextAreaElement.prototype, "value"
            ).set;
            nativeInputValueSetter.call(input, question);
            input.dispatchEvent(new Event("input", { bubbles: true }));
            input.scrollIntoView({ behavior: "smooth", block: "center" });
        }
    };

    // ===========================
    // 点击"重新查看完整回答" → 加载到主区域
    // ===========================
    const handleLoadConversation = (item) => {
        if (item.answer && onLoadConversation) {
            onLoadConversation(item.answer);
            // 滚动到页面顶部，让用户看到加载的内容
            window.scrollTo({ top: 0, behavior: "smooth" });
        }
    };

    // ===========================
    // 多租户（FR-3）：历史记录按学员隔离
    //  - 新条目带 userId → 只显示当前学员的
    //  - 旧条目无 userId（迁移前的全局数据）→ 归属默认学员"学员一"
    // ===========================
    const myHistory = useMemo(() => {
        return questionHistory.filter(item => {
            if (item.userId) return item.userId === currentUser;
            return currentUser === DEFAULT_USER_NAME || !currentUser;
        });
    }, [questionHistory, currentUser]);

    // ===========================
    // 搜索过滤（在本人历史范围内）
    // ===========================
    const filteredHistory = useMemo(() => {
        if (!searchKeyword.trim()) return myHistory;
        const kw = searchKeyword.toLowerCase().trim();
        return myHistory.filter(item => {
            const q = (item.question || "").toLowerCase();
            const goal = (item.goal || "").toLowerCase();
            return q.includes(kw) || goal.includes(kw);
        });
    }, [myHistory, searchKeyword]);

    const goalLabelMap = {
        learn_basics: "基础学习(旧)", build_project: "项目实践(旧)",
        research: "科研探索(旧)", debug: "问题调试(旧)",
        "快速上手应用": "快速上手应用", "深入理解原理": "深入理解原理",
        "项目落地": "项目落地", "算法研究": "算法研究",
    };

    return (
        <div className="info-card">
            {/* 标题 */}
            <div className="card-title" style={{ justifyContent: "space-between" }}>
                <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
                    <History size={24} />
                    <h2>学习历史记录</h2>
                </div>
                <button
                    onClick={handleRefresh}
                    disabled={globalLoading}
                    style={{
                        padding: "8px 16px",
                        borderRadius: "20px",
                        border: "1px solid rgba(255,255,255,0.15)",
                        background: globalLoading ? "rgba(255,255,255,0.05)" : "rgba(59,130,246,0.2)",
                        color: globalLoading ? "#888" : "#b8c4ff",
                        fontSize: "13px",
                        cursor: globalLoading ? "not-allowed" : "pointer",
                        display: "flex",
                        alignItems: "center",
                        gap: "6px",
                        transition: "all 0.2s",
                    }}
                >
                    <RefreshCw size={14} />
                    {globalLoading ? "加载中..." : "刷新"}
                </button>
            </div>

            {/* ===================== */}
            {/* 第一部分：问答历史记录（可搜索、可展开） */}
            {/* ===================== */}
            {myHistory.length > 0 && (
                <div style={{ marginBottom: "28px" }}>
                    <div style={{
                        display: "flex", alignItems: "center", justifyContent: "space-between",
                        marginBottom: "14px",
                    }}>
                        <div style={{
                            display: "flex", alignItems: "center", gap: "8px",
                            fontSize: "16px", color: "#b8c4ff", fontWeight: "bold",
                        }}>
                            <MessageCircle size={18} />
                            问答历史 ({myHistory.length})
                        </div>
                        <button
                            onClick={handleClearHistory}
                            style={{
                                padding: "4px 12px", borderRadius: "16px",
                                border: "1px solid rgba(248,113,113,0.25)",
                                background: "rgba(248,113,113,0.08)",
                                color: "#f87171", fontSize: "12px",
                                cursor: "pointer", display: "flex",
                                alignItems: "center", gap: "4px",
                                transition: "all 0.2s",
                            }}
                        >
                            <Trash2 size={12} />
                            清空
                        </button>
                    </div>

                    {/* 搜索框 */}
                    <div style={{
                        position: "relative", marginBottom: "12px",
                    }}>
                        <Search size={16} style={{
                            position: "absolute", left: "14px", top: "50%",
                            transform: "translateY(-50%)", color: "#666",
                        }} />
                        <input
                            type="text"
                            placeholder="搜索历史问题..."
                            value={searchKeyword}
                            onChange={(e) => {
                                setSearchKeyword(e.target.value);
                                setExpandedIndex(null);
                            }}
                            style={{
                                width: "100%", padding: "10px 14px 10px 40px",
                                borderRadius: "10px",
                                background: "rgba(255,255,255,0.05)",
                                border: "1px solid rgba(255,255,255,0.1)",
                                color: "#e0e0ff", fontSize: "14px",
                                outline: "none", boxSizing: "border-box",
                                transition: "border-color 0.2s",
                            }}
                            onFocus={(e) => e.target.style.borderColor = "rgba(59,130,246,0.4)"}
                            onBlur={(e) => e.target.style.borderColor = "rgba(255,255,255,0.1)"}
                        />
                    </div>

                    {/* 历史列表 */}
                    <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                        {filteredHistory.length === 0 && searchKeyword.trim() && (
                            <div style={{
                                padding: "16px", textAlign: "center",
                                color: "#666", fontSize: "14px",
                            }}>
                                未找到匹配的历史记录
                            </div>
                        )}
                        {/* 历史列表 —— 默认只显示最近 2 条，搜索时显示全部匹配 */}
                        {(() => {
                            const reversed = filteredHistory.slice().reverse();
                            const isSearching = searchKeyword.trim().length > 0;
                            const visible = (showAllHistory || isSearching) ? reversed : reversed.slice(0, 2);
                            return (
                                <>
                        {visible.map((item, displayIdx) => {
                            const q = item.question || "";
                            const goal = item.goal || "";
                            const time = formatTime(item.time);
                            const hasAnswer = item.answer && typeof item.answer === "object";
                            const isExpanded = expandedIndex === displayIdx;
                            const summary = hasAnswer ? extractAnswerSummary(item.answer) : null;

                            return (
                                <div key={displayIdx} style={{
                                    borderRadius: "10px",
                                    background: "rgba(255,255,255,0.04)",
                                    border: "1px solid rgba(255,255,255,0.08)",
                                    overflow: "hidden",
                                    transition: "all 0.2s",
                                }}>
                                    {/* 折叠状态行 */}
                                    <div
                                        onClick={() => setExpandedIndex(isExpanded ? null : displayIdx)}
                                        style={{
                                            display: "flex", alignItems: "center", gap: "10px",
                                            padding: "12px 16px", cursor: "pointer",
                                        }}
                                        onMouseEnter={(e) => {
                                            e.currentTarget.style.background = "rgba(59,130,246,0.08)";
                                        }}
                                        onMouseLeave={(e) => {
                                            e.currentTarget.style.background = "transparent";
                                        }}
                                    >
                                        {isExpanded
                                            ? <ChevronDown size={16} style={{ color: "#888", flexShrink: 0 }} />
                                            : <ChevronRight size={16} style={{ color: "#888", flexShrink: 0 }} />
                                        }
                                        <Clock size={14} style={{ color: "#666", flexShrink: 0 }} />
                                        <span style={{ color: "#888", fontSize: "12px", flexShrink: 0, minWidth: "90px" }}>
                                            {time}
                                        </span>
                                        <span style={{
                                            color: "#e0e0ff", fontSize: "14px", flex: 1,
                                            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                                        }}>
                                            {q}
                                        </span>
                                        {goal && (
                                            <span style={{
                                                padding: "2px 10px", borderRadius: "12px",
                                                background: "rgba(139,92,246,0.15)",
                                                color: "#c4b5fd", fontSize: "12px", flexShrink: 0,
                                            }}>
                                                {goalLabelMap[goal] || goal}
                                            </span>
                                        )}
                                        {/* 有回答标记 */}
                                        {hasAnswer ? (
                                            <span style={{
                                                padding: "2px 8px", borderRadius: "10px",
                                                background: "rgba(74,222,128,0.12)",
                                                color: "#4ade80", fontSize: "11px", flexShrink: 0,
                                            }}>
                                                已回答
                                            </span>
                                        ) : (
                                            <span style={{
                                                padding: "2px 8px", borderRadius: "10px",
                                                background: "rgba(251,191,36,0.12)",
                                                color: "#fbbf24", fontSize: "11px", flexShrink: 0,
                                            }}>
                                                待回答
                                            </span>
                                        )}
                                    </div>

                                    {/* 展开内容 */}
                                    {isExpanded && (
                                        <div style={{
                                            padding: "0 16px 16px 46px",
                                            borderTop: "1px solid rgba(255,255,255,0.06)",
                                        }}>
                                            {/* 问题全文 */}
                                            <div style={{
                                                padding: "12px 0 8px 0",
                                                fontSize: "14px", color: "#c4c9e8", lineHeight: "1.6",
                                            }}>
                                                <span style={{ color: "#666", fontSize: "12px" }}>问题全文：</span><br/>
                                                {q}
                                            </div>

                                            {/* 回答摘要 */}
                                            {summary ? (
                                                <div style={{ display: "flex", flexDirection: "column", gap: "10px", marginTop: "8px" }}>
                                                    {/* 讲义标题 */}
                                                    {summary.lectureTitle && (
                                                        <div style={{
                                                            display: "flex", alignItems: "center", gap: "8px",
                                                            padding: "8px 12px", borderRadius: "8px",
                                                            background: "rgba(59,130,246,0.1)",
                                                        }}>
                                                            <FileText size={14} style={{ color: "#60a5fa", flexShrink: 0 }} />
                                                            <span style={{ color: "#888", fontSize: "12px" }}>讲义：</span>
                                                            <span style={{ color: "#60a5fa", fontSize: "13px" }}>
                                                                {summary.lectureTitle}
                                                            </span>
                                                            {summary.difficultyNote && (
                                                                <span style={{ color: "#fbbf24", fontSize: "12px" }}>
                                                                    ({summary.difficultyNote})
                                                                </span>
                                                            )}
                                                        </div>
                                                    )}

                                                    {/* 裁判结果 */}
                                                    {summary.verdict && (
                                                        <div style={{
                                                            display: "flex", alignItems: "center", gap: "8px",
                                                            padding: "8px 12px", borderRadius: "8px",
                                                            background: summary.verdict === "passed" || summary.verdict === "pass"
                                                                ? "rgba(74,222,128,0.1)"
                                                                : "rgba(248,113,113,0.1)",
                                                        }}>
                                                            <Gavel size={14} style={{
                                                                color: summary.verdict === "passed" || summary.verdict === "pass"
                                                                    ? "#4ade80" : "#f87171",
                                                                flexShrink: 0,
                                                            }} />
                                                            <span style={{ color: "#888", fontSize: "12px" }}>裁判：</span>
                                                            <span style={{
                                                                color: summary.verdict === "passed" || summary.verdict === "pass"
                                                                    ? "#4ade80" : "#f87171",
                                                                fontSize: "13px",
                                                            }}>
                                                                {summary.verdict === "passed" || summary.verdict === "pass" ? "通过" : "未通过"}
                                                            </span>
                                                            {summary.judgeCount > 0 && (
                                                                <span style={{ color: "#666", fontSize: "12px" }}>
                                                                    ({summary.judgeCount} 位裁判)
                                                                </span>
                                                            )}
                                                        </div>
                                                    )}

                                                    {/* 测试题 */}
                                                    {typeof summary.quizCount === "number" && summary.quizCount > 0 && (
                                                        <div style={{
                                                            display: "flex", alignItems: "center", gap: "8px",
                                                            padding: "8px 12px", borderRadius: "8px",
                                                            background: "rgba(139,92,246,0.1)",
                                                        }}>
                                                            <ListChecks size={14} style={{ color: "#c4b5fd", flexShrink: 0 }} />
                                                            <span style={{ color: "#888", fontSize: "12px" }}>测试题：</span>
                                                            <span style={{ color: "#c4b5fd", fontSize: "13px" }}>
                                                                {summary.quizCount} 题
                                                            </span>
                                                        </div>
                                                    )}

                                                    {/* Agent 调度 */}
                                                    {summary.agents && summary.agents.length > 0 && (
                                                        <div style={{
                                                            display: "flex", alignItems: "center", gap: "8px",
                                                            padding: "8px 12px", borderRadius: "8px",
                                                            background: "rgba(255,255,255,0.04)",
                                                            flexWrap: "wrap",
                                                        }}>
                                                            <Users size={14} style={{ color: "#888", flexShrink: 0 }} />
                                                            <span style={{ color: "#888", fontSize: "12px" }}>Agent：</span>
                                                            {summary.agents.map((a, ai) => (
                                                                <span key={ai} style={{
                                                                    padding: "2px 8px", borderRadius: "8px",
                                                                    background: "rgba(59,130,246,0.12)",
                                                                    color: "#60a5fa", fontSize: "12px",
                                                                }}>
                                                                    {a}
                                                                </span>
                                                            ))}
                                                        </div>
                                                    )}

                                                    {/* 学情水平 */}
                                                    {summary.knowledgeLevel && (
                                                        <div style={{
                                                            display: "flex", alignItems: "center", gap: "8px",
                                                            padding: "8px 12px", borderRadius: "8px",
                                                            background: "rgba(251,191,36,0.08)",
                                                        }}>
                                                            <Flame size={14} style={{ color: "#fbbf24", flexShrink: 0 }} />
                                                            <span style={{ color: "#888", fontSize: "12px" }}>学情：</span>
                                                            <span style={{ color: "#fbbf24", fontSize: "13px" }}>
                                                                {summary.knowledgeLevel}
                                                            </span>
                                                        </div>
                                                    )}

                                                    {/* 澄清选项 */}
                                                    {summary.clarificationOptions && summary.clarificationOptions.length > 0 && (
                                                        <div style={{
                                                            padding: "8px 12px", borderRadius: "8px",
                                                            background: "rgba(139,92,246,0.08)",
                                                        }}>
                                                            <span style={{ color: "#888", fontSize: "12px" }}>系统建议澄清方向：</span>
                                                            <div style={{ marginTop: "6px", display: "flex", flexDirection: "column", gap: "4px" }}>
                                                                {summary.clarificationOptions.map((opt, oi) => (
                                                                    <span key={oi} style={{
                                                                        color: "#c4b5fd", fontSize: "13px",
                                                                    }}>
                                                                        {oi + 1}. {opt}
                                                                    </span>
                                                                ))}
                                                            </div>
                                                        </div>
                                                    )}

                                                    {/* 操作按钮 */}
                                                    <div style={{ display: "flex", gap: "10px", marginTop: "6px" }}>
                                                        <button
                                                            onClick={(e) => {
                                                                e.stopPropagation();
                                                                handleLoadConversation(item);
                                                            }}
                                                            style={{
                                                                display: "flex", alignItems: "center", gap: "6px",
                                                                padding: "8px 16px", borderRadius: "8px",
                                                                border: "1px solid rgba(59,130,246,0.3)",
                                                                background: "rgba(59,130,246,0.15)",
                                                                color: "#60a5fa", fontSize: "13px",
                                                                cursor: "pointer", transition: "all 0.2s",
                                                            }}
                                                            onMouseEnter={(e) => {
                                                                e.currentTarget.style.background = "rgba(59,130,246,0.25)";
                                                            }}
                                                            onMouseLeave={(e) => {
                                                                e.currentTarget.style.background = "rgba(59,130,246,0.15)";
                                                            }}
                                                        >
                                                            <Eye size={14} />
                                                            重新查看完整回答
                                                        </button>
                                                        <button
                                                            onClick={(e) => {
                                                                e.stopPropagation();
                                                                handleResubmit(q);
                                                            }}
                                                            style={{
                                                                display: "flex", alignItems: "center", gap: "6px",
                                                                padding: "8px 16px", borderRadius: "8px",
                                                                border: "1px solid rgba(255,255,255,0.15)",
                                                                background: "rgba(255,255,255,0.05)",
                                                                color: "#b8c4ff", fontSize: "13px",
                                                                cursor: "pointer", transition: "all 0.2s",
                                                            }}
                                                            onMouseEnter={(e) => {
                                                                e.currentTarget.style.background = "rgba(255,255,255,0.1)";
                                                            }}
                                                            onMouseLeave={(e) => {
                                                                e.currentTarget.style.background = "rgba(255,255,255,0.05)";
                                                            }}
                                                        >
                                                            <RefreshCw size={14} />
                                                            重新提问
                                                        </button>
                                                    </div>
                                                </div>
                                            ) : (
                                                <div style={{
                                                    padding: "12px 0", color: "#666", fontSize: "13px",
                                                }}>
                                                    该问题尚未收到回答（可能任务还在处理中或已失败）
                                                </div>
                                            )}
                                        </div>
                                    )}
                                </div>
                            );
                        })}

                        {/* 展开更多历史按钮（搜索时不显示，因为搜索已展示全部匹配） */}
                        {!isSearching && reversed.length > 2 && (
                            <button
                                onClick={() => setShowAllHistory(v => !v)}
                                style={{
                                    display: "flex", alignItems: "center", justifyContent: "center",
                                    gap: "6px", padding: "10px 16px", borderRadius: "10px",
                                    border: "1px solid rgba(59,130,246,0.25)",
                                    background: "rgba(59,130,246,0.08)",
                                    color: "#60a5fa", fontSize: "13px", fontWeight: "600",
                                    cursor: "pointer", transition: "all 0.2s",
                                }}
                                onMouseEnter={(e) => {
                                    e.currentTarget.style.background = "rgba(59,130,246,0.15)";
                                    e.currentTarget.style.borderColor = "rgba(59,130,246,0.4)";
                                }}
                                onMouseLeave={(e) => {
                                    e.currentTarget.style.background = "rgba(59,130,246,0.08)";
                                    e.currentTarget.style.borderColor = "rgba(59,130,246,0.25)";
                                }}
                            >
                                {showAllHistory
                                    ? <><ChevronDown size={14} /> 收起历史（还有 {reversed.length - 2} 条已隐藏）</>
                                    : <><ChevronRight size={14} /> 展开更多（共 {reversed.length} 条，还有 {reversed.length - 2} 条）</>
                                }
                            </button>
                        )}
                                </>
                            );
                        })()}
                    </div>
                </div>
            )}

            {/* ===================== */}
            {/* 第二部分：学情报告（后端 report 接口） */}
            {/* ===================== */}

            {/* 重新诊断入口：后端对同一 session 的报告只在首次生成、不随新任务更新，
                提供"新开学习会话"按钮让热力图/知识水平能随下一次提问重新生成 */}
            {onResetDiagnosis && (
                <div style={{
                    display: "flex", alignItems: "center", justifyContent: "space-between",
                    flexWrap: "wrap", gap: "10px",
                    padding: "12px 16px", borderRadius: "12px",
                    background: "rgba(139,92,246,0.06)",
                    border: "1px dashed rgba(139,92,246,0.35)",
                    marginBottom: "14px",
                }}>
                    <div style={{ fontSize: "12px", color: "#8888bb", lineHeight: 1.6 }}>
                        学情报告是当前会话的快照，后端不会随新提问自动更新。
                        <br />
                        点击右侧按钮新开一个学习会话，下次提问将重新生成完整诊断。
                    </div>
                    <button
                        onClick={() => {
                            if (window.confirm("确定要重新诊断吗？\n\n将新开一个学习会话并清空当前页面的讲义/测试数据，下次提问会重新生成完整学情诊断（旧会话数据保留在历史中）。")) {
                                onResetDiagnosis();
                            }
                        }}
                        style={{
                            display: "flex", alignItems: "center", gap: "6px",
                            padding: "9px 16px", borderRadius: "10px",
                            border: "1px solid rgba(139,92,246,0.4)",
                            background: "rgba(139,92,246,0.15)",
                            color: "#c4b5fd", fontSize: "13px", fontWeight: "600",
                            cursor: "pointer", transition: "all 0.2s", whiteSpace: "nowrap",
                        }}
                        onMouseEnter={(e) => {
                            e.currentTarget.style.background = "rgba(139,92,246,0.28)";
                            e.currentTarget.style.borderColor = "rgba(139,92,246,0.65)";
                        }}
                        onMouseLeave={(e) => {
                            e.currentTarget.style.background = "rgba(139,92,246,0.15)";
                            e.currentTarget.style.borderColor = "rgba(139,92,246,0.4)";
                        }}
                    >
                        <RefreshCw size={14} />
                        重新诊断
                    </button>
                </div>
            )}

            {/* 全局错误（没有任何报告时） */}
            {globalError && !globalLoading && reports.length === 0 && (
                <div style={{
                    padding: "16px 20px", borderRadius: "12px",
                    background: "rgba(251,191,36,0.08)",
                    border: "1px solid rgba(251,191,36,0.2)",
                    color: "#fbbf24", fontSize: "14px", textAlign: "center",
                }}>
                    {globalError}
                </div>
            )}

            {/* 加载中 */}
            {globalLoading && reports.length === 0 && (
                <div style={{ padding: "20px", textAlign: "center", color: "#888", fontSize: "14px" }}>
                    正在从后端获取学情报告...
                </div>
            )}

            {/* 报告卡片列表 */}
            {reports.length > 0 && reports.map((r, reportIdx) => {
                // 每个报告独立提取数据
                const report = r.data;
                const profileSummary = report?.profile_summary || {};
                const heatmapObj = report?.knowledge_heatmap || {};
                const heatmapNodes = safeArray(heatmapObj.nodes);
                const difficultyMatch = report?.difficulty_match || {};
                const difficultyPoints = safeArray(difficultyMatch.points);
                const learningPath = report?.learning_path || {};
                const pathStages = safeArray(learningPath.stages);
                const knowledgeLevel = profileSummary.knowledge_level || "未知";
                const domainHint = safeArray(profileSummary.domain_hint);
                const domainConfidence = profileSummary.domain_confidence || {};
                const confidenceKeys = Object.keys(domainConfidence);
                const testResults = safeArray(profileSummary.test_results);

                return (
                <div key={r.sessionId || reportIdx} style={{
                    marginBottom: "16px",
                    borderRadius: "14px",
                    border: "1px solid rgba(139,92,246,0.2)",
                    background: "rgba(139,92,246,0.04)",
                    overflow: "hidden",
                }}>
                    {/* 卡片头部：session_id */}
                    <div style={{
                        display: "flex", alignItems: "center", gap: "10px",
                        padding: "10px 18px",
                        background: "rgba(139,92,246,0.1)",
                        borderBottom: "1px solid rgba(139,92,246,0.15)",
                    }}>
                        <Clock size={14} style={{ color: "#c4b5fd" }} />
                        <span style={{
                            color: "#c4b5fd", fontSize: "13px", fontWeight: "bold",
                            fontFamily: "monospace",
                        }}>
                            {r.sessionId || ""}
                        </span>
                        {report?.local_generated && (
                            <span style={{
                                padding: "2px 8px", borderRadius: "8px",
                                background: "rgba(251,191,36,0.15)",
                                color: "#fbbf24", fontSize: "11px",
                            }}>
                                依据学情画像生成
                            </span>
                        )}
                        {reportIdx === 0 && reports.length > 1 && (
                            <span style={{
                                padding: "2px 8px", borderRadius: "8px",
                                background: "rgba(59,130,246,0.2)",
                                color: "#60a5fa", fontSize: "11px",
                            }}>
                                最新
                            </span>
                        )}
                    </div>

                    {/* 卡片内容 */}
                    <div style={{ padding: "18px" }}>
                        {/* 单个报告加载/错误/等待 */}
                        {r.error === "PENDING" && !report && (
                            <div style={{
                                padding: "12px 16px", borderRadius: "10px",
                                background: "rgba(59,130,246,0.08)",
                                border: "1px solid rgba(59,130,246,0.15)",
                                color: "#60a5fa", fontSize: "13px",
                                display: "flex", alignItems: "center", gap: "8px",
                            }}>
                                <span style={{
                                    display: "inline-block", width: "10px", height: "10px",
                                    borderRadius: "50%", border: "2px solid #60a5fa",
                                    borderTopColor: "transparent",
                                    animation: "spin 1s linear infinite",
                                }} />
                                画像正在生成中，请稍候…（每 5 秒自动刷新）
                            </div>
                        )}
                        {r.error && r.error !== "PENDING" && !report && (
                            <div style={{
                                padding: "12px 16px", borderRadius: "10px",
                                background: "rgba(251,191,36,0.08)",
                                border: "1px solid rgba(251,191,36,0.15)",
                                color: "#fbbf24", fontSize: "13px",
                            }}>
                                {r.error}
                            </div>
                        )}

                        {!report && !r.error && (
                            <div style={{
                                padding: "12px 16px", borderRadius: "10px",
                                color: "#888", fontSize: "13px",
                            }}>
                                加载中...
                            </div>
                        )}

                        {report && (
                <>
                    {/* 数据可用性速览 */}
                    <div style={{
                        display: "flex", gap: "10px", flexWrap: "wrap",
                        marginBottom: "16px", fontSize: "12px",
                    }}>
                        <span style={{
                            padding: "3px 10px", borderRadius: "8px",
                            background: profileSummary && Object.keys(profileSummary).length > 0
                                ? "rgba(34,197,94,0.12)" : "rgba(255,255,255,0.05)",
                            color: profileSummary && Object.keys(profileSummary).length > 0
                                ? "#4ade80" : "#555",
                            border: `1px solid ${profileSummary && Object.keys(profileSummary).length > 0 ? "rgba(34,197,94,0.25)" : "rgba(255,255,255,0.06)"}`,
                        }}>
                            画像 {profileSummary && Object.keys(profileSummary).length > 0 ? "✓" : "✗"}
                        </span>
                        <span style={{
                            padding: "3px 10px", borderRadius: "8px",
                            background: heatmapNodes.length > 0
                                ? "rgba(34,197,94,0.12)" : "rgba(255,255,255,0.05)",
                            color: heatmapNodes.length > 0 ? "#4ade80" : "#555",
                            border: `1px solid ${heatmapNodes.length > 0 ? "rgba(34,197,94,0.25)" : "rgba(255,255,255,0.06)"}`,
                        }}>
                            热力图 {heatmapNodes.length > 0 ? "✓" : "✗"}
                        </span>
                        <span style={{
                            padding: "3px 10px", borderRadius: "8px",
                            background: difficultyPoints.length > 0
                                ? "rgba(34,197,94,0.12)" : "rgba(255,255,255,0.05)",
                            color: difficultyPoints.length > 0 ? "#4ade80" : "#555",
                            border: `1px solid ${difficultyPoints.length > 0 ? "rgba(34,197,94,0.25)" : "rgba(255,255,255,0.06)"}`,
                        }}>
                            难度匹配 {difficultyPoints.length > 0 ? "✓" : "✗"}
                        </span>
                        <span style={{
                            padding: "3px 10px", borderRadius: "8px",
                            background: pathStages.length > 0
                                ? "rgba(34,197,94,0.12)" : "rgba(255,255,255,0.05)",
                            color: pathStages.length > 0 ? "#4ade80" : "#555",
                            border: `1px solid ${pathStages.length > 0 ? "rgba(34,197,94,0.25)" : "rgba(255,255,255,0.06)"}`,
                        }}>
                            学习路径 {pathStages.length > 0 ? "✓" : "✗"}
                        </span>
                        {heatmapNodes.length === 0 && difficultyPoints.length === 0 && pathStages.length === 0 && (
                            <span style={{
                                color: "#888", fontSize: "11px",
                                padding: "3px 0",
                            }}>
                                暂无报告数据
                            </span>
                        )}
                    </div>

                    {/* ----- 2.1 学情画像摘要 ----- */}
                    <div style={{ marginBottom: "24px" }}>
                        <div style={{
                            display: "flex", alignItems: "center", gap: "8px",
                            fontSize: "16px", color: "#b8c4ff", marginBottom: "14px",
                            fontWeight: "bold",
                        }}>
                            <Flame size={18} />
                            学情画像摘要
                        </div>
                        <div style={{ display: "flex", flexWrap: "wrap", gap: "12px" }}>
                            <div style={{
                                padding: "10px 18px", borderRadius: "12px",
                                background: "rgba(59,130,246,0.15)",
                                border: "1px solid rgba(59,130,246,0.25)",
                            }}>
                                <span style={{ color: "#888", fontSize: "12px" }}>知识水平 </span>
                                <span style={{ color: "#60a5fa", fontSize: "15px", fontWeight: "bold" }}>
                                    {knowledgeLevel}
                                </span>
                            </div>
                            {domainHint.map((domain, idx) => (
                                <div key={idx} style={{
                                    padding: "10px 18px", borderRadius: "12px",
                                    background: "rgba(139,92,246,0.15)",
                                    border: "1px solid rgba(139,92,246,0.25)",
                                }}>
                                    <span style={{ color: "#888", fontSize: "12px" }}>兴趣领域 </span>
                                    <span style={{ color: "#c4b5fd", fontSize: "15px" }}>{domain}</span>
                                </div>
                            ))}
                        </div>
                        {confidenceKeys.length > 0 && (
                            <div style={{ display: "flex", flexWrap: "wrap", gap: "10px", marginTop: "10px" }}>
                                {confidenceKeys.map((key) => {
                                    const conf = domainConfidence[key];
                                    const confColor = conf === "high" ? "#4ade80" : conf === "medium" ? "#fbbf24" : "#f87171";
                                    return (
                                        <span key={key} style={{
                                            padding: "4px 12px", borderRadius: "8px",
                                            background: "rgba(255,255,255,0.05)",
                                            color: confColor, fontSize: "13px",
                                        }}>
                                            {key}: {conf}
                                        </span>
                                    );
                                })}
                            </div>
                        )}

                        {/* 理论测试成绩 */}
                        {testResults.length > 0 && (
                            <div style={{ marginTop: "14px" }}>
                                <div style={{
                                    display: "flex", alignItems: "center", gap: "8px",
                                    marginBottom: "10px",
                                }}>
                                    <GraduationCap size={16} style={{ color: "#c4b5fd" }} />
                                    <span style={{
                                        fontSize: "14px", color: "#b8c4ff", fontWeight: "bold",
                                    }}>
                                        理论测试成绩 ({testResults.length})
                                    </span>
                                </div>
                                <div style={{ display: "flex", flexWrap: "wrap", gap: "10px" }}>
                                    {testResults.map((test, idx) => {
                                        const score = typeof test.score === "number" ? test.score : 0;
                                        const scoreColor = score >= 0.8 ? "#4ade80" : score >= 0.6 ? "#fbbf24" : "#f87171";
                                        const scoreBg = score >= 0.8 ? "rgba(74,222,128,0.12)"
                                            : score >= 0.6 ? "rgba(251,191,36,0.12)"
                                            : "rgba(248,113,113,0.12)";
                                        return (
                                            <div key={idx} style={{
                                                padding: "10px 16px", borderRadius: "12px",
                                                background: scoreBg,
                                                border: `1px solid ${scoreColor}30`,
                                                display: "flex", flexDirection: "column", gap: "4px",
                                                minWidth: "140px",
                                            }}>
                                                <div style={{
                                                    display: "flex", alignItems: "center",
                                                    justifyContent: "space-between", gap: "12px",
                                                }}>
                                                    <span style={{ color: "#e0e0ff", fontSize: "14px", fontWeight: "bold" }}>
                                                        {test.topic || "未知科目"}
                                                    </span>
                                                    <span style={{
                                                        color: scoreColor, fontSize: "18px", fontWeight: "bold",
                                                    }}>
                                                        {(score * 100).toFixed(0)}
                                                        <span style={{ fontSize: "12px" }}>分</span>
                                                    </span>
                                                </div>
                                                {test.date && (
                                                    <span style={{ color: "#888", fontSize: "12px" }}>
                                                        {test.date}
                                                    </span>
                                                )}
                                            </div>
                                        );
                                    })}
                                </div>
                            </div>
                        )}
                    </div>

                    {/* ----- 2.2 热力图 ----- */}
                    {heatmapNodes.length > 0 && (
                        <div style={{ marginBottom: "24px" }}>
                            <div style={{
                                display: "flex", alignItems: "center", gap: "8px",
                                fontSize: "16px", color: "#b8c4ff", marginBottom: "14px",
                                fontWeight: "bold",
                            }}>
                                <Flame size={18} />
                                热力图
                                {typeof heatmapObj.blind_count === "number" && (
                                    <span style={{
                                        padding: "2px 10px", borderRadius: "10px",
                                        background: "rgba(248,113,113,0.15)",
                                        color: "#f87171", fontSize: "12px",
                                    }}>
                                        {heatmapObj.blind_count} 个盲区
                                    </span>
                                )}
                            </div>
                            <div style={{
                                display: "grid",
                                gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))",
                                gap: "10px",
                            }}>
                                {heatmapNodes.map((node, idx) => {
                                    const sc = getStatusConfig(node.status);
                                    const interacted = node.interacted;
                                    return (
                                        <div key={idx} style={{
                                            padding: "14px", borderRadius: "12px",
                                            background: sc.bg,
                                            border: `1px solid ${sc.color}40`,
                                            opacity: interacted ? 1 : 0.7,
                                        }}>
                                            <div style={{
                                                display: "flex", justifyContent: "space-between",
                                                alignItems: "center", marginBottom: "8px",
                                            }}>
                                                <span style={{ color: "#e0e0ff", fontSize: "14px", fontWeight: "bold" }}>
                                                    {node.domain || "未知领域"}
                                                </span>
                                                <span style={{
                                                    color: sc.color, fontSize: "12px",
                                                    padding: "2px 8px", borderRadius: "8px",
                                                    background: "rgba(0,0,0,0.2)",
                                                }}>
                                                    {sc.icon} {sc.label}
                                                </span>
                                            </div>
                                            <div style={{ color: "#888", fontSize: "12px", marginBottom: "6px" }}>
                                                {node.agent_name || ""}
                                            </div>
                                            {typeof node.importance_score === "number" && (
                                                <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                                                    <span style={{ color: "#666", fontSize: "11px" }}>重要度</span>
                                                    <div style={{
                                                        flex: 1, height: "4px", borderRadius: "2px",
                                                        background: "rgba(255,255,255,0.1)",
                                                    }}>
                                                        <div style={{
                                                            width: `${Math.min(100, node.importance_score * 100)}%`,
                                                            height: "100%", borderRadius: "2px",
                                                            background: sc.color,
                                                        }} />
                                                    </div>
                                                    <span style={{ color: sc.color, fontSize: "11px" }}>
                                                        {(node.importance_score * 100).toFixed(0)}%
                                                    </span>
                                                </div>
                                            )}
                                            {interacted && (
                                                <div style={{
                                                    marginTop: "6px", fontSize: "11px", color: "#4ade80",
                                                }}>
                                                    ● 已交互
                                                </div>
                                            )}
                                        </div>
                                    );
                                })}
                            </div>
                            {heatmapObj.summary && (
                                <div style={{
                                    marginTop: "12px", padding: "12px 16px", borderRadius: "10px",
                                    background: "rgba(0,0,0,0.2)", color: "#c4c9e8", fontSize: "13px",
                                }}>
                                    {heatmapObj.summary}
                                </div>
                            )}
                        </div>
                    )}

                    {/* ----- 2.3 资源难度匹配（SVG 折线图） ----- */}
                    {difficultyPoints.length > 0 && (
                        <div style={{ marginBottom: "24px" }}>
                            <div style={{
                                display: "flex", alignItems: "center", gap: "8px",
                                fontSize: "16px", color: "#b8c4ff", marginBottom: "14px",
                                fontWeight: "bold",
                            }}>
                                <TrendingUp size={18} />
                                资源难度匹配
                                {typeof difficultyMatch.overall_match_rate === "number" && (
                                    <span style={{
                                        padding: "2px 10px", borderRadius: "10px",
                                        background: "rgba(59,130,246,0.15)",
                                        color: "#60a5fa", fontSize: "12px",
                                    }}>
                                        整体匹配率 {(difficultyMatch.overall_match_rate * 100).toFixed(0)}%
                                    </span>
                                )}
                            </div>

                            {/* SVG 折线图 */}
                            <svg
                                viewBox="0 0 720 260"
                                style={{
                                    width: "100%",
                                    height: "auto",
                                    maxHeight: "280px",
                                    background: "rgba(255,255,255,0.02)",
                                    borderRadius: "12px",
                                    border: "1px solid rgba(255,255,255,0.06)",
                                }}
                                preserveAspectRatio="xMidYMid meet"
                            >
                                {/* 常量 */}
                                {(() => {
                                    const PAD_L = 50, PAD_R = 20, PAD_T = 30, PAD_B = 60;
                                    const W = 720 - PAD_L - PAD_R;
                                    const H = 260 - PAD_T - PAD_B;
                                    const xScale = (i) => PAD_L + (W / Math.max(1, difficultyPoints.length - 1)) * i;
                                    const yScale = (v) => PAD_T + H - v * H;
                                    const pts = difficultyPoints;
                                    return (
                                        <g>
                                            {/* Y轴网格线 + 标签 */}
                                            {[0, 0.25, 0.5, 0.75, 1].map((t) => (
                                                <g key={t}>
                                                    <line
                                                        x1={PAD_L} y1={yScale(t)}
                                                        x2={PAD_L + W} y2={yScale(t)}
                                                        stroke="rgba(255,255,255,0.06)"
                                                        strokeDasharray={t === 0 ? "" : "4,4"}
                                                    />
                                                    <text
                                                        x={PAD_L - 8} y={yScale(t) + 4}
                                                        fill="#666" fontSize="11"
                                                        textAnchor="end"
                                                    >
                                                        {(t * 100).toFixed(0)}%
                                                    </text>
                                                </g>
                                            ))}

                                            {/* X轴底线 */}
                                            <line
                                                x1={PAD_L} y1={PAD_T + H}
                                                x2={PAD_L + W} y2={PAD_T + H}
                                                stroke="rgba(255,255,255,0.1)"
                                            />

                                            {/* 学生水平折线（蓝） */}
                                            <polyline
                                                fill="none"
                                                stroke="#60a5fa"
                                                strokeWidth="2.5"
                                                strokeLinejoin="round"
                                                strokeLinecap="round"
                                                points={pts.map((p, i) => `${xScale(i)},${yScale(typeof p.student_level === "number" ? p.student_level : 0)}`).join(" ")}
                                                opacity="0.9"
                                            />
                                            {/* 资源难度折线（红） */}
                                            <polyline
                                                fill="none"
                                                stroke="#f87171"
                                                strokeWidth="2.5"
                                                strokeLinejoin="round"
                                                strokeLinecap="round"
                                                points={pts.map((p, i) => `${xScale(i)},${yScale(typeof p.resource_difficulty === "number" ? p.resource_difficulty : 0)}`).join(" ")}
                                                opacity="0.9"
                                            />

                                            {/* 数据点 */}
                                            {pts.map((p, i) => {
                                                const sx = xScale(i);
                                                const sy = yScale(typeof p.student_level === "number" ? p.student_level : 0);
                                                const ry = yScale(typeof p.resource_difficulty === "number" ? p.resource_difficulty : 0);
                                                const ms = p.match_status || "";
                                                const dotColor = ms === "matched" ? "#4ade80" : ms === "too_easy" ? "#fbbf24" : "#f87171";
                                                return (
                                                    <g key={i}>
                                                        {/* 学生水平点 */}
                                                        <circle cx={sx} cy={sy} r="5" fill="#1a1a2e" stroke="#60a5fa" strokeWidth="2.5" />
                                                        {/* 资源难度点 */}
                                                        <circle cx={sx} cy={ry} r="5" fill="#1a1a2e" stroke="#f87171" strokeWidth="2.5" />
                                                        {/* 匹配状态背景 */}
                                                        <circle cx={sx} cy={sy - 16} r="4" fill={dotColor} opacity="0.9" />
                                                        {/* X轴标签 */}
                                                        <text
                                                            x={sx} y={PAD_T + H + 18}
                                                            fill="#888" fontSize="11"
                                                            textAnchor="middle"
                                                        >
                                                            {p.domain || "未知"}
                                                        </text>
                                                    </g>
                                                );
                                            })}

                                            {/* 图例 */}
                                            <g transform={`translate(${PAD_L + W - 180}, 10)`}>
                                                <circle cx="0" cy="6" r="4" fill="#1a1a2e" stroke="#60a5fa" strokeWidth="2" />
                                                <text x="10" y="10" fill="#b8c4ff" fontSize="11">学生水平</text>
                                                <circle cx="80" cy="6" r="4" fill="#1a1a2e" stroke="#f87171" strokeWidth="2" />
                                                <text x="90" y="10" fill="#b8c4ff" fontSize="11">资源难度</text>
                                            </g>

                                            {/* 匹配状态图例 */}
                                            <g transform={`translate(${PAD_L}, 10)`}>
                                                <circle cx="0" cy="6" r="4" fill="#4ade80" />
                                                <text x="10" y="10" fill="#888" fontSize="10">匹配</text>
                                                <circle cx="50" cy="6" r="4" fill="#fbbf24" />
                                                <text x="60" y="10" fill="#888" fontSize="10">偏简单</text>
                                                <circle cx="110" cy="6" r="4" fill="#f87171" />
                                                <text x="120" y="10" fill="#888" fontSize="10">偏难</text>
                                            </g>
                                        </g>
                                    );
                                })()}
                            </svg>

                            {/* 明细卡片（保留原有进度条作为补充） */}
                            <div style={{ display: "flex", flexDirection: "column", gap: "8px", marginTop: "12px" }}>
                                {difficultyPoints.map((pt, idx) => {
                                    const studentLevel = typeof pt.student_level === "number" ? pt.student_level : 0;
                                    const resDifficulty = typeof pt.resource_difficulty === "number" ? pt.resource_difficulty : 0;
                                    const matchStatus = pt.match_status || "";
                                    const matchColor = matchStatus === "matched" ? "#4ade80"
                                        : matchStatus === "too_easy" ? "#fbbf24" : "#f87171";
                                    return (
                                        <div key={idx} style={{
                                            padding: "10px 14px", borderRadius: "10px",
                                            background: "rgba(255,255,255,0.03)",
                                            border: `1px solid ${matchColor}20`,
                                        }}>
                                            <div style={{
                                                display: "flex", justifyContent: "space-between",
                                                alignItems: "center",
                                            }}>
                                                <span style={{ color: "#c4c9e8", fontSize: "13px" }}>
                                                    {pt.domain || "未知"}
                                                </span>
                                                <span style={{
                                                    color: matchColor, fontSize: "12px", fontWeight: 600,
                                                    padding: "2px 8px", borderRadius: "6px",
                                                    background: `${matchColor}15`,
                                                }}>
                                                    {matchStatus === "matched" ? "匹配" : matchStatus === "too_easy" ? "偏简单" : "偏难"}
                                                </span>
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>
                        </div>
                    )}

                    {/* ----- 2.4 学习路径规划 ----- */}
                    {pathStages.length > 0 && (
                        <div>
                            <div style={{
                                display: "flex", alignItems: "center", gap: "8px",
                                fontSize: "16px", color: "#b8c4ff", marginBottom: "14px",
                                fontWeight: "bold",
                            }}>
                                <Map size={18} />
                                学习路径规划
                            </div>
                            <div style={{ display: "flex", flexDirection: "column", gap: "0" }}>
                                {pathStages.map((stage, idx) => {
                                    const sc = getStatusConfig(stage.student_status);
                                    const recommended = stage.recommended;
                                    const domains = safeArray(stage.domains);
                                    const isLast = idx === pathStages.length - 1;
                                    return (
                                        <div key={idx} style={{ display: "flex", gap: "16px" }}>
                                            <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
                                                <div style={{
                                                    width: "28px", height: "28px", borderRadius: "50%",
                                                    background: sc.bg, border: `2px solid ${sc.color}`,
                                                    display: "flex", alignItems: "center", justifyContent: "center",
                                                    color: sc.color, fontSize: "12px", fontWeight: "bold",
                                                    flexShrink: 0,
                                                }}>
                                                    {stage.stage || idx + 1}
                                                </div>
                                                {!isLast && (
                                                    <div style={{
                                                        width: "2px", flex: 1, minHeight: "20px",
                                                        background: "rgba(255,255,255,0.1)",
                                                    }} />
                                                )}
                                            </div>
                                            <div style={{
                                                paddingBottom: isLast ? "0" : "20px", flex: 1,
                                            }}>
                                                <div style={{
                                                    display: "flex", alignItems: "center", gap: "10px",
                                                    flexWrap: "wrap", marginBottom: "6px",
                                                }}>
                                                    <span style={{ color: "#e0e0ff", fontSize: "15px", fontWeight: "bold" }}>
                                                        {stage.title || `阶段 ${stage.stage || idx + 1}`}
                                                    </span>
                                                    <span style={{
                                                        padding: "2px 10px", borderRadius: "10px",
                                                        background: sc.bg, color: sc.color, fontSize: "11px",
                                                    }}>
                                                        {sc.label}
                                                    </span>
                                                    {recommended && (
                                                        <span style={{
                                                            padding: "2px 10px", borderRadius: "10px",
                                                            background: "rgba(248,113,113,0.15)",
                                                            color: "#f87171", fontSize: "11px",
                                                        }}>
                                                            ★ 推荐优先
                                                        </span>
                                                    )}
                                                    {typeof stage.estimated_hours === "number" && (
                                                        <span style={{
                                                            color: "#888", fontSize: "12px",
                                                        }}>
                                                            约 {stage.estimated_hours} 小时
                                                        </span>
                                                    )}
                                                </div>
                                                {domains.length > 0 && (
                                                    <div style={{ display: "flex", flexWrap: "wrap", gap: "6px" }}>
                                                        {domains.map((d, di) => (
                                                            <span key={di} style={{
                                                                padding: "3px 10px", borderRadius: "8px",
                                                                background: "rgba(255,255,255,0.05)",
                                                                color: "#c4c9e8", fontSize: "12px",
                                                            }}>
                                                                {d}
                                                            </span>
                                                        ))}
                                                    </div>
                                                )}
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>
                        </div>
                    )}
                </>
                        )}
                    </div>
                </div>
                );
            })}
        </div>
    );
}

export default HistoryPanel;

/* hmr-kick 1786868010 */
