import React, { useState, Component, useRef } from "react";

import { askQuestion, getTaskStatus } from "./api/api";


// 页面组件

import Header from "./components/Header";

import TaskInput from "./components/TaskInput";

import StudentProfile from "./components/StudentProfile";

import AgentPanel from "./components/AgentPanel";

import FSMFlow from "./components/FSMFlow";

import AnswerPanel from "./components/AnswerPanel";

import JudgePanel from "./components/JudgePanel";

import Quiz from "./components/Quiz";

import Feedback from "./components/Feedback";

import HistoryPanel from "./components/HistoryPanel";

import LecturePage from "./components/LecturePage";

import QuizPage from "./components/QuizPage";

import MemoryStatsPanel from "./components/MemoryStatsPanel";

import UserSwitcher from "./components/UserSwitcher";

import {
    getCurrentUserId,
    getSessionForUser,
    bindSession,
    createUser,
    setCurrentUserId,
    getUsers,
    migrateLegacySession,
    resetUserSession,
} from "./utils/userStore";


import "./App.css";


class ErrorBoundary extends Component {
    constructor(props) {
        super(props);
        this.state = { hasError: false, error: null, errorInfo: null };
    }

    static getDerivedStateFromError(error) {
        return { hasError: true, error };
    }

    componentDidCatch(error, errorInfo) {
        console.error("组件渲染崩溃:", error, errorInfo);
        this.setState({ errorInfo });
    }

    render() {
        if (this.state.hasError) {
            return (
                <div style={{ padding: "40px", color: "#ff6b6b", background: "#1a1a2e", minHeight: "100vh", fontFamily: "monospace" }}>
                    <h2 style={{ fontSize: "20px", marginBottom: "16px" }}>页面渲染崩溃</h2>
                    <p style={{ fontSize: "14px", wordBreak: "break-all" }}>{this.state.error && this.state.error.toString()}</p>
                    <pre style={{ fontSize: "12px", marginTop: "16px", whiteSpace: "pre-wrap", color: "#aaa" }}>
                        {this.state.errorInfo && this.state.errorInfo.componentStack}
                    </pre>
                </div>
            );
        }
        return this.props.children;
    }
}


function App() {


    // ===============================
    // 后端任务完整数据
    // 对应 /api/ask 返回结果
    // ===============================

    const [taskData, setTaskData] = useState(null);



    // 当前任务ID

    const [taskId, setTaskId] = useState("");



    // 当前会话ID

    // 多学员身份层（multi_tenant_isolation_spec FR-1/FR-2）：
    //  - currentUser：当前学员标识（学号/姓名），localStorage 持久化
    //  - sessionId：由当前学员的映射派生；切换学员即切换 session，互不干扰
    //  - 首次运行时把旧的 persistentSessionId 迁移给默认学员"学员一"，进度不丢失
    const [currentUser, setCurrentUser] = useState(() => {
        migrateLegacySession();
        return getCurrentUserId();
    });

    const [sessionId, setSessionId] = useState(() => {
        const uid = getCurrentUserId();
        return uid ? getSessionForUser(uid) : "";
    });

    // 已保存的学员列表（切换下拉用），切换/新增后刷新
    const [userList, setUserList] = useState(() => Object.keys(getUsers()));

    // 切换学员：session 跟随学员映射，清空上一个学员的任务残留，避免串数据
    const handleSwitchUser = (userId) => {
        if (!userId || userId === currentUser) return;
        setCurrentUser(userId);
        setCurrentUserId(userId);
        setSessionId(getSessionForUser(userId) || "");
        // 清空旧学员的任务/页面/自适应状态
        setTaskData(null);
        setTaskId("");
        setUiProfile(null);
        setFsmState("");
        setActivePage(null);
        resetAdaptive();
        console.log("[学员] 切换到:", userId, "session:", getSessionForUser(userId));
    };

    // 新增学员：写入映射（session 留空，首次提问时生成并绑定），并切换过去
    const handleCreateUser = (userId) => {
        if (!userId || !userId.trim()) return;
        const uid = userId.trim();
        createUser(uid, "");
        setUserList(Object.keys(getUsers()));
        handleSwitchUser(uid);
    };

    // 重新诊断：为当前学员换一个新 session（覆盖旧绑定），清空本页任务残留。
    // 后端对同一 session 的报告只在首次生成、不随新任务更新（实测确认），
    // 换新 session 后下次提问会触发后端重新诊断 → 热力图/知识水平随之更新。
    const handleResetDiagnosis = () => {
        if (!currentUser) return;
        const newSid = resetUserSession(currentUser);
        setSessionId(newSid);
        setTaskData(null);
        setTaskId("");
        setUiProfile(null);
        setFsmState("");
        setActivePage(null);
        resetAdaptive();
        console.log("[学员] 重新诊断:", currentUser, "新 session:", newSid);
    };



    // 当前激活的全屏页面："lecture"（讲义）| "quiz"（测试题）| null（首页）
    // 生成完成后由 TaskInput 的 onPageReady 触发，点叉/关闭测试后回 null
    const [activePage, setActivePage] = useState(null);

    // 启发式追问注入：Quiz 里点击追问 → 填入 TaskInput 并自动开启新一轮生成
    const [pendingQuestion, setPendingQuestion] = useState(null);



    // FSM实时状态

    const [fsmState, setFsmState] = useState("");





    // ===============================
    // TaskInput 创建任务后的回调
    // 异步模式：此时只有 task_id，还没有完整数据
    // ===============================
    // 前端填写的学情画像（TaskInput 提交时带上）
    // 后端回显会清空 domain_hint，HistoryPanel 本地合成报告时优先用这个原始值
    const [uiProfile, setUiProfile] = useState(null);

    const handleTaskStart = (data) => {
        console.log("任务创建成功:", data);
        setTaskId(data.taskId);
        setSessionId(data.sessionId);
        // 把新生成的 session 绑定到当前学员（FR-2 学员↔session 映射）
        if (currentUser && data.sessionId) {
            bindSession(currentUser, data.sessionId);
            setUserList(Object.keys(getUsers()));
        }
        setUiProfile(data.profile || null);
        // 不设置 taskData —— 等轮询返回 COMPLETE 后才设置
    };

    // ===============================
    // 自适应出题（按正确率调整难度）
    // 提交测试后：正确率 <85% → 生成更简单的一组；≥85% → 在当前级别上限内小幅上调难度
    // 阈值对齐后端 orchestrator.py 的 0.85 单阈值：accuracy < 0.85 → REDIMENSION；≥ 0.85 → ADVANCE
    // 实现方式：把难度指令拼进 question 文本，复用 POST /api/tasks + 轮询
    // ===============================
    const [adaptiveQuiz, setAdaptiveQuiz] = useState(null);      // 自适应生成的新题目
    const [adaptiveState, setAdaptiveState] = useState("idle");  // idle | generating | ready | error
    const [adaptiveRound, setAdaptiveRound] = useState(0);       // 第几轮（0 = 原始题）
    const [adaptiveDirection, setAdaptiveDirection] = useState(""); // easier | harder
    const adaptivePollRef = useRef(null);

    const resetAdaptive = () => {
        if (adaptivePollRef.current) {
            clearInterval(adaptivePollRef.current);
            adaptivePollRef.current = null;
        }
        setAdaptiveQuiz(null);
        setAdaptiveState("idle");
        setAdaptiveRound(0);
        setAdaptiveDirection("");
    };

    const handleRegenerateQuiz = async (accuracy) => {
        if (adaptiveState === "generating") return;

        // 用户当前知识水平（前端填写的画像优先，其次后端诊断结果）
        const level =
            uiProfile?.knowledge_level ||
            taskData?.profile?.knowledge_level ||
            "入门";
        const isLow = accuracy < 85;
        setAdaptiveDirection(isLow ? "easier" : "harder");
        setAdaptiveState("generating");

        // 难度指令拼进 question（复用学情背景的文本注入模式，后端无需改造）
        const difficultyText = isLow
            ? "比上一组明显更简单：聚焦最基础的核心概念理解和直接套用，题干表述直白、干扰项少，帮助夯实基础"
            : `在当前「${level}」水平基础上难度小幅上调：题目灵活度略有增加、可含少量综合应用，但整体不得超过「${level}」级别的难度上限，不得出现更高级别的内容`;
        const question = `【自适应出题】刚完成一组学习测试题，正确率 ${accuracy}%（${
            isLow ? "低于85%" : "达到85%以上"
        }）。请围绕同一主题再生成一组新的测试题（5道左右，需包含题目、选项、答案、解析）。难度要求：${difficultyText}。本次只需生成测试题，不需要长篇讲义。`;

        try {
            const resp = await askQuestion({
                question,
                session_id: sessionId,
            });
            const newTaskId = resp?.task_id;
            if (!newTaskId) throw new Error("后端未返回 task_id");
            console.log("[自适应出题] 任务已提交, task_id:", newTaskId);

            // 轮询新任务，直到 COMPLETE（2s 一次，最多 3 分钟）
            let polling = false;
            let pollCount = 0;
            let pollFailCount = 0;
            const MAX_POLLS = 90;
            const MAX_FAILS = 6;

            const timer = setInterval(async () => {
                if (polling) return;
                polling = true;
                pollCount++;
                try {
                    const res = await getTaskStatus(newTaskId);
                    const stateUpper = (res.state || "").toUpperCase();

                    if (
                        stateUpper === "COMPLETE" ||
                        stateUpper === "COMPLETED" ||
                        stateUpper === "DONE" ||
                        stateUpper === "SUCCESS"
                    ) {
                        clearInterval(timer);
                        adaptivePollRef.current = null;
                        const fullData = res.result || res;
                        const newQuiz = fullData?.resource_package?.quiz;
                        console.log("[自适应出题] 完成, 新题目:", newQuiz);
                        if (newQuiz) {
                            setAdaptiveQuiz(newQuiz);
                            setAdaptiveRound((r) => r + 1);
                            setAdaptiveState("ready");
                        } else {
                            console.warn("[自适应出题] 后端未返回 quiz 字段");
                            setAdaptiveState("error");
                        }
                    } else if (
                        stateUpper === "FAILED" ||
                        stateUpper === "ERROR"
                    ) {
                        clearInterval(timer);
                        adaptivePollRef.current = null;
                        console.error("[自适应出题] 任务失败:", res);
                        setAdaptiveState("error");
                    } else if (pollCount >= MAX_POLLS) {
                        clearInterval(timer);
                        adaptivePollRef.current = null;
                        console.error("[自适应出题] 轮询超时");
                        setAdaptiveState("error");
                    }
                } catch (e) {
                    console.error("[自适应出题] 轮询出错:", e);
                    pollFailCount++;
                    if (pollFailCount >= MAX_FAILS) {
                        clearInterval(timer);
                        adaptivePollRef.current = null;
                        setAdaptiveState("error");
                    }
                } finally {
                    polling = false;
                }
            }, 2000);
            adaptivePollRef.current = timer;
        } catch (e) {
            console.error("[自适应出题] 任务提交失败:", e);
            setAdaptiveState("error");
        }
    };


    // ===============================
    // 任务完成后的回调
    // 异步模式：轮询到 COMPLETE 后，拿到完整数据才渲染各面板
    // ===============================
    const handleTaskComplete = (data) => {
        console.log("任务完成，完整数据:", data);
        setTaskData(data);
    };

    // ===============================
    // 生成完成后，自动打开对应全屏页面
    // pageType: "lecture" 讲义 | "guide" 实操指南 | "quiz" 测试题
    // ===============================
    const handlePageReady = (pageType) => {
        console.log("打开全屏页面:", pageType);
        setActivePage(pageType);
        window.scrollTo({ top: 0, behavior: "smooth" });
    };





    // ===============================
    // WebSocket FSM状态更新
    // ===============================

    const handleFSMUpdate = (message) => {


        console.log(
            "FSM状态:",
            message
        );



        if(message?.state){


            setFsmState(

                message.state

            );


        }


    };





    // 检测是否为澄清意图（后端返回 clarification_options 但无 resource_package）
    const isClarification = taskData?.dispatch_info?.intent === "clarification"
        && taskData?.clarification_options?.length > 0;

    // 检测所有内容字段是否都为空（任务完成但后端没返回有效内容）
    const hasResourcePackage = taskData?.resource_package && (
        taskData.resource_package.lecture ||
        taskData.resource_package.guide ||
        taskData.resource_package.quiz ||
        taskData.resource_package.content_markdown
    );
    const hasDispatchInfo = taskData?.dispatch_info && Object.keys(taskData.dispatch_info).length > 0;
    const hasJudgeVerdict = taskData?.judge_verdict && Object.keys(taskData.judge_verdict).length > 0;
    const hasProfile = taskData?.profile && Object.keys(taskData.profile).length > 0;
    const allContentEmpty = taskData && !hasResourcePackage && !hasDispatchInfo && !hasJudgeVerdict && !hasProfile && !isClarification;

    // 从 dispatch_info 提取 feedback 所需的 agent_id 和 function_tag
    // 兼容两种结构：selected_agents 数组 / segments[].candidates[].agent_id
    const feedbackAgentId = (() => {
        const di = taskData?.dispatch_info;
        if (!di) return undefined;
        if (Array.isArray(di.selected_agents) && di.selected_agents.length > 0) {
            return di.selected_agents[0];
        }
        if (Array.isArray(di.segments)) {
            for (const seg of di.segments) {
                if (Array.isArray(seg.candidates)) {
                    for (const c of seg.candidates) {
                        if (c.agent_id) return c.agent_id;
                    }
                }
                if (seg.agent_id) return seg.agent_id;
            }
        }
        return undefined;
    })();
    const feedbackFunctionTag = taskData?.dispatch_info?.function_tag || taskData?.dispatch_info?.intent || undefined;


    return (

        <ErrorBoundary>

        <div className="app">


            {/* 顶部系统标题（右侧含学员身份切换） */}

            <Header
                rightSlot={
                    <UserSwitcher
                        currentUser={currentUser}
                        users={userList}
                        onSwitch={handleSwitchUser}
                        onCreate={handleCreateUser}
                    />
                }
            />




            <main className="dashboard">




                {/* =====================

                    第一部分：
                    学生输入任务

                ===================== */}



                <TaskInput


                    onTaskStart={handleTaskStart}

                    onFSMUpdate={handleFSMUpdate}

                    onTaskComplete={handleTaskComplete}

                    onPageReady={handlePageReady}

                    hasData={!!taskData && !!taskData.resource_package}

                    resourcesAvailable={{
                        lecture: !!(taskData?.resource_package?.lecture),
                        guide: !!(taskData?.resource_package?.practice_guide || taskData?.resource_package?.guide),
                        quiz: !!(taskData?.resource_package?.quiz)
                    }}

                    sessionId={sessionId}

                    currentUser={currentUser}

                    pendingQuestion={pendingQuestion}

                    onPendingConsumed={() => setPendingQuestion(null)}

                />



                {/* =====================

                    历史记录：
                    学习历史 + 学情报告

                ===================== */}



                <HistoryPanel

                    sessionId={sessionId}

                    currentUser={currentUser}

                    onResetDiagnosis={handleResetDiagnosis}

                    taskProfile={uiProfile || taskData?.profile}

                    onLoadConversation={(data) => {
                        setTaskData(data);
                        setTaskId(data?.task_id || "");
                        window.scrollTo({ top: 0, behavior: "smooth" });
                    }}

                />



                {/* =====================

                    第二部分：
                    FSM流程展示

                ===================== */}



                <FSMFlow


                    currentState={fsmState}


                />




                {

                    taskData &&

                    <>




                        {/* =====================

                            学情画像

                        ===================== */}


                        <StudentProfile


                            profile={

                                taskData.profile

                            }


                        />






                        {/* =====================

                            Agent动态调度

                        ===================== */}


                        <AgentPanel


                            dispatchInfo={

                                taskData.dispatch_info

                            }


                        />



                        {/* =====================
                            澄清选项
                            当后端判定问题需要澄清时（intent=clarification），
                            resource_package 等字段为 null，此时展示澄清选项
                        ===================== */}
                        {isClarification && (
                            <div className="info-card">
                                <div className="card-title">
                                    <h2>💡 需要进一步明确</h2>
                                </div>
                                <p style={{ color: "#b8c4ff", fontSize: "14px", marginBottom: "16px" }}>
                                    系统检测到你的问题涉及多个方向，请选择你最感兴趣的内容，系统将为你生成更精准的学习方案：
                                </p>
                                <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                                    {taskData.clarification_options.map((opt, idx) => (
                                        <div key={idx} style={{
                                            padding: "12px 16px",
                                            borderRadius: "8px",
                                            background: "rgba(255,255,255,0.05)",
                                            border: "1px solid rgba(139,92,246,0.3)",
                                            color: "#e0e0ff",
                                            fontSize: "14px",
                                            cursor: "pointer",
                                            transition: "all 0.2s"
                                        }}
                                        onClick={() => {
                                            const input = document.querySelector('textarea');
                                            if (input) {
                                                input.value = opt;
                                                input.dispatchEvent(new Event('input', { bubbles: true }));
                                                input.scrollIntoView({ behavior: 'smooth' });
                                            }
                                        }}>
                                            {opt}
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}

                        {/* =====================
                            调试信息卡片
                            当任务完成但后端返回的所有内容字段都为空时显示，
                            展示后端实际返回的字段结构，方便排查字段名不匹配问题
                        ===================== */}
                        {allContentEmpty && (
                            <div className="info-card" style={{ borderColor: "rgba(255,193,7,0.4)" }}>
                                <div className="card-title">
                                    <h2 style={{ color: "#ffc107" }}>⚠️ 任务已完成，但未获取到方案数据</h2>
                                </div>
                                <p style={{ color: "#b8c4ff", fontSize: "14px", marginBottom: "16px" }}>
                                    后端返回了 COMPLETE 状态，但前端期望的字段（resource_package / dispatch_info / judge_verdict / profile）都为空。
                                    这通常是因为后端返回的字段名和前端期望的不一致。以下是后端实际返回的数据结构：
                                </p>
                                <pre style={{
                                    background: "rgba(0,0,0,0.3)",
                                    padding: "12px",
                                    borderRadius: "8px",
                                    color: "#e0e0ff",
                                    fontSize: "13px",
                                    overflow: "auto",
                                    maxHeight: "400px",
                                    whiteSpace: "pre-wrap",
                                    wordBreak: "break-all"
                                }}>
{JSON.stringify(taskData, (key, value) => {
    if (typeof value === "string" && value.length > 200) return value.substring(0, 200) + "...(截断)";
    return value;
}, 2)}
                                </pre>
                                <p style={{ color: "#888", fontSize: "12px", marginTop: "12px" }}>
                                    请截图发给我，我会根据实际字段名一次性修对前端代码。
                                </p>
                            </div>
                        )}





                        {/* =====================

                            AI生成内容

                        ===================== */}

                        {/* (讲义已拆为全屏页，首页不再显示)
<AnswerPanel


                            answer={

                                taskData
                                ?.resource_package
                                ?.lecture

                            }


                        />
*/}





                        {/* =====================

                            多Agent裁判

                        ===================== */}


                        <JudgePanel


                            judge={

                                taskData.judge_verdict

                            }

                            reviewSummary={taskData?.review_summary}

                        />



                        {/* =====================

                            多智能体贡献记忆闭环
                            闭环第 5 步：任务完成后展示 Agent 贡献分、
                            调度权重 α 变化、贡献流、淘汰记录

                        ===================== */}

                        <MemoryStatsPanel

                            taskComplete={!!taskData}

                        />






                        {/* =====================

                            学习测试
                            POST /api/quiz_submit

                        ===================== */}


                        {/* (测试题已拆为全屏页，首页不再显示)
<Quiz


                            quiz={

                                taskData
                                ?.resource_package
                                ?.quiz

                            }


                            taskId={taskId}


                            sessionId={sessionId}


                        />*/}






                        {/* =====================

                            学生反馈
                            POST /api/feedback

                        ===================== */}


                        {/* (反馈已移到测试题页面)
<Feedback
                            taskId={taskId}
                            sessionId={sessionId}
                            agentId={feedbackAgentId}
                            functionTag={feedbackFunctionTag}
                        />*/}



                    </>

                }



            </main>

            {/* =====================
                全屏页面（覆盖首页）
                讲义页 / 实操指南页 / 测试题页，点叉或关闭测试后回到首页
            ===================== */}

            {activePage === "lecture" && taskData?.resource_package?.lecture && (
                <LecturePage
                    lecture={taskData.resource_package.lecture}
                    onClose={() => setActivePage(null)}
                />
            )}

            {activePage === "guide" && (() => {
                // 实操指南内容兼容两种后端结构：字符串 / 对象（content_markdown 或 steps_markdown）
                const rp = taskData?.resource_package;
                const raw = rp?.practice_guide || rp?.guide;
                const guideData =
                    typeof raw === "string"
                        ? { content_markdown: raw }
                        : raw && (raw.content_markdown || raw.steps_markdown)
                            ? raw
                            : null;
                return guideData ? (
                    <LecturePage
                        lecture={guideData}
                        pageTitle="实操指南"
                        onClose={() => setActivePage(null)}
                    />
                ) : null;
            })()}

            {activePage === "quiz" && taskData?.resource_package?.quiz && (
                <QuizPage
                    quiz={taskData.resource_package.quiz}
                    taskId={taskId}
                    sessionId={sessionId}
                    feedbackAgentId={feedbackAgentId}
                    feedbackFunctionTag={feedbackFunctionTag}
                    onRegenerate={handleRegenerateQuiz}
                    adaptiveState={adaptiveState}
                    adaptiveQuiz={adaptiveQuiz}
                    adaptiveRound={adaptiveRound}
                    adaptiveDirection={adaptiveDirection}
                    userLevel={
                        uiProfile?.knowledge_level ||
                        taskData?.profile?.knowledge_level ||
                        "入门"
                    }
                    onClose={() => {
                        setActivePage(null);
                        resetAdaptive();
                    }}
                    onFollowupClick={(q) => {
                        // 点击启发式追问：关闭测试页，把问题作为新提问开启下一轮学习
                        setActivePage(null);
                        resetAdaptive();
                        setPendingQuestion(q);
                    }}
                />
            )}


        </div>

        </ErrorBoundary>

    );


}



export default App;
